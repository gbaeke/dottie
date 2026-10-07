"""Creating and tuning dotties: personality, toolkits, skills, MCP servers."""

import logging
import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import User, UserDep
from ..db import SessionDep
from ..engine import files
from ..engine.mcp import config_problems, referenced_secrets
from ..engine.seed import TEMPLATES
from ..engine.tools import DEFAULT_TOOLKITS, TOOLKITS, is_public_url
from ..models import Dottie, Message, Run, Schedule, Skill
from .access import owned_dottie
from .errors import ApiError

log = logging.getLogger(__name__)

router = APIRouter(tags=["dotties"])


class McpServer(BaseModel):
    """An MCP server a dottie may use. Values of `headers` and `query` may contain `{{secret:NAME}}`; anything that
    looks like a credential must, because a literal one would be stored and shown in clear."""

    name: Annotated[str, Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,39}$")]
    url: HttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _no_literal_credentials(self) -> McpServer:
        problems = config_problems(self.model_dump(mode="json"))
        if problems:
            raise ValueError(" ".join(problems))
        return self


class DottieIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(default="", max_length=200)
    personality: str = Field(default="", max_length=8000)
    hue: int = Field(default=250, ge=0, le=360)
    model: str | None = Field(default=None, max_length=120)
    tools: list[str] = Field(default_factory=lambda: list(DEFAULT_TOOLKITS))
    mcp_servers: list[McpServer] = Field(default_factory=list)
    skill_ids: list[int] = Field(default_factory=list)

    @field_validator("tools")
    @classmethod
    def _known_toolkits(cls, tools: list[str]) -> list[str]:
        unknown = [t for t in tools if t not in TOOLKITS]
        if unknown:
            raise ValueError(f"Unknown toolkit {unknown[0]!r}; choose from {', '.join(TOOLKITS)}.")
        return list(dict.fromkeys(tools))


class DottiePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    role: str | None = Field(default=None, max_length=200)
    personality: str | None = Field(default=None, max_length=8000)
    hue: int | None = Field(default=None, ge=0, le=360)
    model: str | None = Field(default=None, max_length=120)
    tools: list[str] | None = None
    mcp_servers: list[McpServer] | None = None
    skill_ids: list[int] | None = None

    @field_validator("tools")
    @classmethod
    def _known_toolkits(cls, tools: list[str] | None) -> list[str] | None:
        return None if tools is None else DottieIn._known_toolkits(tools)


class DottieOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    role: str
    personality: str
    hue: int
    model: str | None
    tools: list[str]
    mcp_servers: list[McpServer]
    skill_ids: list[int]
    state: str  # sleeping | idle (awake, its computer warm for follow-ups) | queued | awake
    unread: int  # messages from it the user has not read
    next_run_at: datetime | None  # its next schedule
    last_woke_at: datetime | None
    created_at: datetime


class ToolkitOut(BaseModel):
    key: str
    description: str


class TemplateOut(BaseModel):
    key: str
    name: str
    role: str
    hue: int
    personality: str
    tools: list[str]
    skills: list[str]


def _slug(session: Session, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "dottie"
    slug, n = base, 1
    while session.scalar(select(Dottie.id).where(Dottie.slug == slug)) is not None:
        n += 1
        slug = f"{base}-{n}"
    return slug


def present(session: Session, dotties: list[Dottie]) -> list[DottieOut]:
    """Dotties with their live state, from four grouped queries instead of four per dottie."""
    ids = [d.id for d in dotties]
    awake = set(session.scalars(select(Run.dottie_id).where(Run.status == "running", Run.dottie_id.in_(ids))))
    queued = set(
        session.scalars(select(Message.recipient_id).where(Message.status == "pending", Message.recipient_id.in_(ids)))
    )

    def state(d: Dottie) -> str:
        if d.id in awake:
            return "awake"
        if d.id in queued:
            return "queued"
        # no run now, but its computer still runs for follow-ups until the engine stops it (Engine.reap_idle)
        return "idle" if d.sandbox_awake else "sleeping"

    unread = dict(
        session.execute(
            select(Message.sender_id, func.count())
            .where(Message.recipient_id.is_(None), Message.read_at.is_(None), Message.sender_id.in_(ids))
            .group_by(Message.sender_id)
        ).all()
    )
    upcoming = dict(
        session.execute(
            select(Schedule.dottie_id, func.min(Schedule.next_run_at))
            .where(Schedule.enabled, Schedule.dottie_id.in_(ids))
            .group_by(Schedule.dottie_id)
        ).all()
    )
    return [
        DottieOut(
            id=d.id,
            name=d.name,
            slug=d.slug,
            role=d.role,
            personality=d.personality,
            hue=d.hue,
            model=d.model,
            tools=d.tools,
            mcp_servers=[McpServer.model_validate(m) for m in d.mcp_servers],
            skill_ids=[k.id for k in d.skills],
            state=state(d),
            unread=unread.get(d.id, 0),
            next_run_at=upcoming.get(d.id),
            last_woke_at=d.last_woke_at,
            created_at=d.created_at,
        )
        for d in dotties
    ]


def _check_servers(request: Request, user: User, servers: list[McpServer]) -> None:
    """With several users, an MCP server must be on a public address (the app is the one calling it), and every secret
    it refers to must exist, so a typo is caught now and not on the dottie's next waking."""
    known = request.app.state.secret_store.names(user.id)
    for server in servers:
        if request.app.state.settings.auth_enabled and not is_public_url(str(server.url)):
            raise ApiError("invalid", f"MCP server {server.name!r} must be on a public address.", 422)
        if missing := referenced_secrets(server.model_dump(mode="json")) - known:
            raise ApiError(
                "invalid", f"MCP server {server.name!r} uses the secret(s) {', '.join(sorted(missing))}: not set.", 422
            )


def _skills(session: Session, ids: list[int], owner_id: str) -> list[Skill]:
    """The skills to give a dottie: built in ones and the user's own, never someone else's, one per name."""
    found = list(session.scalars(select(Skill).where(Skill.id.in_(ids), Skill.owner_id.in_(["", owner_id]))))
    if len(found) != len(set(ids)):
        raise ApiError("invalid", "One of the skills does not exist.", 422)
    if len({k.name for k in found}) != len(found):
        raise ApiError("invalid", "Two of the skills have the same name.", 422)
    return found


@router.get("/toolkits")
def list_toolkits() -> list[ToolkitOut]:
    return [ToolkitOut(key=k, description=v) for k, v in TOOLKITS.items()]


@router.get("/templates")
def list_templates() -> list[TemplateOut]:
    return [TemplateOut.model_validate(t) for t in TEMPLATES]


@router.get("/dotties")
def list_dotties(session: SessionDep, user: UserDep) -> list[DottieOut]:
    mine = select(Dottie).where(Dottie.owner_id == user.id).order_by(Dottie.created_at, Dottie.id)
    dotties = list(session.scalars(mine))
    return present(session, dotties)


@router.post("/dotties", status_code=201)
def create_dottie(data: DottieIn, session: SessionDep, request: Request, user: UserDep) -> DottieOut:
    limit = request.app.state.settings.max_dotties_per_user
    if (session.scalar(select(func.count()).where(Dottie.owner_id == user.id)) or 0) >= limit:
        raise ApiError("limit_reached", f"You can have at most {limit} dotties.", 409)
    _check_servers(request, user, data.mcp_servers)
    dottie = Dottie(
        owner_id=user.id,
        **data.model_dump(exclude={"skill_ids", "mcp_servers"}),
        mcp_servers=[m.model_dump(mode="json") for m in data.mcp_servers],
        slug=_slug(session, data.name),
    )
    dottie.skills = _skills(session, data.skill_ids, user.id)
    session.add(dottie)
    session.flush()
    files.seed_wiki(session, dottie)
    session.commit()
    return present(session, [dottie])[0]


@router.get("/dotties/{dottie_id}")
def get_dottie(dottie_id: int, session: SessionDep, user: UserDep) -> DottieOut:
    return present(session, [owned_dottie(session, user, dottie_id)])[0]


@router.patch("/dotties/{dottie_id}")
def update_dottie(dottie_id: int, data: DottiePatch, session: SessionDep, request: Request, user: UserDep) -> DottieOut:
    dottie = owned_dottie(session, user, dottie_id)
    _check_servers(request, user, data.mcp_servers or [])
    changes = data.model_dump(exclude_unset=True, exclude={"skill_ids", "mcp_servers"})
    for field, value in changes.items():
        setattr(dottie, field, value)
    if data.mcp_servers is not None:
        dottie.mcp_servers = [m.model_dump(mode="json") for m in data.mcp_servers]
    if data.skill_ids is not None:
        dottie.skills = _skills(session, data.skill_ids, user.id)
    session.commit()
    return present(session, [dottie])[0]


@router.delete("/dotties/{dottie_id}", status_code=204)
def delete_dottie(dottie_id: int, session: SessionDep, request: Request, user: UserDep) -> None:
    dottie = owned_dottie(session, user, dottie_id)
    if dottie.sandbox_ref:  # its computer goes with it; its wiki and conversations are deleted by the database
        try:
            request.app.state.provider.destroy(dottie.sandbox_ref)
        except Exception:  # a sandbox that is already gone must not keep the dottie alive, but say so
            log.warning("could not delete the sandbox %s of dottie %s", dottie.sandbox_ref, dottie.id, exc_info=True)
    session.delete(dottie)
    session.commit()

"""The skill library: procedures any dottie can be given."""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..auth import UserDep
from ..db import SessionDep
from ..models import DottieSkill, Skill
from .errors import ApiError
from .util import build

router = APIRouter(prefix="/skills", tags=["skills"])

NAME = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class SkillIn(BaseModel):
    name: str = Field(pattern=NAME, max_length=64)  # also the skill's directory name, so lowercase-hyphen
    description: str = Field(min_length=1, max_length=1024)
    body: str = Field(min_length=1, max_length=50_000)


class SkillPatch(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=1024)
    body: str | None = Field(default=None, min_length=1, max_length=50_000)


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    body: str
    builtin: bool
    used_by: int  # dotties that have it
    created_at: datetime


def _out(session: SessionDep, skill: Skill) -> SkillOut:
    used = session.scalar(select(func.count()).select_from(DottieSkill).where(DottieSkill.skill_id == skill.id)) or 0
    return build(SkillOut, skill, used_by=used)


def _editable(session: SessionDep, user: UserDep, skill_id: int) -> Skill:
    """A skill of the user's own. Built-in ones are everyone's and cannot be changed; someone else's does not exist."""
    skill = session.get(Skill, skill_id)
    if skill is None or skill.owner_id not in ("", user.id):
        raise ApiError("not_found", f"Skill {skill_id} not found", 404)
    if skill.builtin:
        raise ApiError("builtin_skill", "Built-in skills ship with Dottie; copy it under a new name to change it.", 409)
    return skill


@router.get("")
def list_skills(session: SessionDep, user: UserDep) -> list[SkillOut]:
    visible = select(Skill).where(Skill.owner_id.in_(["", user.id])).order_by(Skill.builtin.desc(), Skill.name)
    return [_out(session, s) for s in session.scalars(visible)]


@router.post("", status_code=201)
def create_skill(data: SkillIn, session: SessionDep, user: UserDep) -> SkillOut:
    skill = Skill(owner_id=user.id, **data.model_dump())
    session.add(skill)
    try:
        session.commit()
    except IntegrityError:
        raise ApiError("duplicate", f"A skill called {data.name!r} already exists.", 409) from None
    return _out(session, skill)


@router.patch("/{skill_id}")
def update_skill(skill_id: int, data: SkillPatch, session: SessionDep, user: UserDep) -> SkillOut:
    skill = _editable(session, user, skill_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(skill, field, value)
    session.commit()
    return _out(session, skill)


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: int, session: SessionDep, user: UserDep) -> None:
    skill = _editable(session, user, skill_id)
    session.delete(skill)
    session.commit()

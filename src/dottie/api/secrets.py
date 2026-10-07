"""A user's secrets: write-only. The API can set, list (name and a hint) and delete them, never give a value back."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..auth import UserDep
from ..db import SessionDep
from ..engine.mcp import referenced_secrets
from ..engine.secrets import NAME_PATTERN, SecretsNotConfigured
from ..models import Dottie, Secret
from .errors import ApiError

router = APIRouter(prefix="/secrets", tags=["secrets"])

SecretName = Annotated[str, Path(pattern=f"^{NAME_PATTERN}$")]


class SecretIn(BaseModel):
    value: str = Field(min_length=1, max_length=8000)


class SecretOut(BaseModel):
    name: str
    hint: str  # the last characters, or nothing for a short value
    updated_at: datetime
    used_by: list[str]  # names of the dotties whose MCP servers use it


def _used_by(session: SessionDep, owner_id: str) -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for dottie in session.scalars(select(Dottie).where(Dottie.owner_id == owner_id)):
        for server in dottie.mcp_servers:
            for name in referenced_secrets(server):
                if dottie.name not in used.setdefault(name, []):
                    used[name].append(dottie.name)
    return used


def _out(secret: Secret, used: dict[str, list[str]]) -> SecretOut:
    return SecretOut(
        name=secret.name, hint=secret.hint, updated_at=secret.updated_at, used_by=used.get(secret.name, [])
    )


@router.get("")
def list_secrets(session: SessionDep, user: UserDep) -> list[SecretOut]:
    used = _used_by(session, user.id)
    rows = session.scalars(select(Secret).where(Secret.owner_id == user.id).order_by(Secret.name))
    return [_out(r, used) for r in rows]


@router.put("/{name}")
def set_secret(name: SecretName, data: SecretIn, session: SessionDep, request: Request, user: UserDep) -> SecretOut:
    """Create the secret, or replace its value. The value is encrypted and cannot be read back."""
    try:
        request.app.state.secret_store.put(user.id, name, data.value)
    except SecretsNotConfigured:
        raise ApiError("not_configured", "Secrets are off: the app has no SECRETS_KEY.", 503) from None
    session.expire_all()
    row = session.scalar(select(Secret).where(Secret.owner_id == user.id, Secret.name == name))
    if row is None:
        raise ApiError("not_found", f"No secret called {name!r}", 404)
    return _out(row, _used_by(session, user.id))


@router.delete("/{name}", status_code=204)
def delete_secret(name: SecretName, session: SessionDep, user: UserDep) -> None:
    row = session.scalar(select(Secret).where(Secret.owner_id == user.id, Secret.name == name))
    if row is None:
        raise ApiError("not_found", f"No secret called {name!r}", 404)
    users = _used_by(session, user.id).get(name, [])
    if users:
        raise ApiError(
            "in_use", f"{name!r} is used by {', '.join(users)}: remove it from their MCP servers first.", 409
        )
    session.delete(row)
    session.commit()

"""Personal access tokens: how a user's other tools (an MCP client such as Claude Code) act as them."""

import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..auth import UserDep
from ..db import SessionDep
from ..models import ApiToken
from .errors import ApiError

router = APIRouter(prefix="/tokens", tags=["tokens"])


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class TokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    last_used_at: datetime | None


class TokenCreated(TokenOut):
    token: str  # shown once: only its hash is kept


@router.get("")
def list_tokens(session: SessionDep, user: UserDep) -> list[TokenOut]:
    rows = session.scalars(select(ApiToken).where(ApiToken.owner_id == user.id).order_by(ApiToken.id))
    return [TokenOut.model_validate(t) for t in rows]


@router.post("", status_code=201)
def create_token(data: TokenIn, session: SessionDep, user: UserDep) -> TokenCreated:
    token = "dtk_" + secrets.token_urlsafe(32)
    row = ApiToken(owner_id=user.id, name=data.name, token_hash=hash_token(token))
    session.add(row)
    session.commit()
    return TokenCreated(**TokenOut.model_validate(row).model_dump(), token=token)


@router.delete("/{token_id}", status_code=204)
def delete_token(token_id: int, session: SessionDep, user: UserDep) -> None:
    row = session.get(ApiToken, token_id)
    if row is None or row.owner_id != user.id:
        raise ApiError("not_found", f"Token {token_id} not found", 404)
    session.delete(row)
    session.commit()

"""The skill library: procedures any dottie can be given."""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..db import SessionDep
from ..models import DottieSkill, Skill
from .errors import ApiError, get_or_404
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


def _editable(skill: Skill) -> None:
    if skill.builtin:
        raise ApiError("builtin_skill", "Built-in skills ship with Dottie; copy it under a new name to change it.", 409)


@router.get("")
def list_skills(session: SessionDep) -> list[SkillOut]:
    return [_out(session, s) for s in session.scalars(select(Skill).order_by(Skill.builtin.desc(), Skill.name))]


@router.post("", status_code=201)
def create_skill(data: SkillIn, session: SessionDep) -> SkillOut:
    skill = Skill(**data.model_dump())
    session.add(skill)
    try:
        session.commit()
    except IntegrityError:
        raise ApiError("duplicate", f"A skill called {data.name!r} already exists.", 409) from None
    return _out(session, skill)


@router.patch("/{skill_id}")
def update_skill(skill_id: int, data: SkillPatch, session: SessionDep) -> SkillOut:
    skill = get_or_404(session, Skill, skill_id)
    _editable(skill)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(skill, field, value)
    session.commit()
    return _out(session, skill)


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: int, session: SessionDep) -> None:
    skill = get_or_404(session, Skill, skill_id)
    _editable(skill)
    session.delete(skill)
    session.commit()

"""A dottie's wiki as the user sees it: browse, read and edit the same pages the dottie keeps."""

import posixpath
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import SessionDep
from ..models import Dottie, WikiPage
from .errors import ApiError, get_or_404

router = APIRouter(prefix="/dotties/{dottie_id}/wiki", tags=["wiki"])


class PageSummary(BaseModel):
    path: str
    size: int
    updated_by: str
    updated_at: datetime


class PageOut(PageSummary):
    content: str


class PageIn(BaseModel):
    content: str = Field(max_length=200_000)


def _clean(path: str) -> str:
    clean = posixpath.normpath(path.strip("/"))
    if clean in ("", ".") or clean.startswith("..") or len(clean) > 300:
        raise ApiError("invalid", "That is not a valid page path.", 422)
    return clean


def _page(session: SessionDep, dottie_id: int, path: str) -> WikiPage | None:
    return session.scalar(select(WikiPage).where(WikiPage.dottie_id == dottie_id, WikiPage.path == _clean(path)))


@router.get("")
def list_pages(dottie_id: int, session: SessionDep) -> list[PageSummary]:
    get_or_404(session, Dottie, dottie_id)
    pages = session.scalars(select(WikiPage).where(WikiPage.dottie_id == dottie_id).order_by(WikiPage.path))
    return [
        PageSummary(path=p.path, size=len(p.content), updated_by=p.updated_by, updated_at=p.updated_at) for p in pages
    ]


@router.get("/{path:path}")
def read_page(dottie_id: int, path: str, session: SessionDep) -> PageOut:
    page = _page(session, dottie_id, path)
    if page is None:
        raise ApiError("not_found", f"No page {path!r} in this wiki", 404)
    return PageOut(
        path=page.path,
        size=len(page.content),
        updated_by=page.updated_by,
        updated_at=page.updated_at,
        content=page.content,
    )


@router.put("/{path:path}")
def write_page(dottie_id: int, path: str, data: PageIn, session: SessionDep) -> PageOut:
    get_or_404(session, Dottie, dottie_id)
    page = _page(session, dottie_id, path)
    if page is None:
        page = WikiPage(dottie_id=dottie_id, path=_clean(path), content=data.content, updated_by="user")
        session.add(page)
    else:
        page.content, page.updated_by = data.content, "user"
    session.commit()
    session.refresh(page)
    return PageOut(
        path=page.path,
        size=len(page.content),
        updated_by=page.updated_by,
        updated_at=page.updated_at,
        content=page.content,
    )


@router.delete("/{path:path}", status_code=204)
def delete_page(dottie_id: int, path: str, session: SessionDep) -> None:
    page = _page(session, dottie_id, path)
    if page is None:
        raise ApiError("not_found", f"No page {path!r} in this wiki", 404)
    session.delete(page)
    session.commit()

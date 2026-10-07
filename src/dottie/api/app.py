from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import sessionmaker

from ..config import Settings, get_settings
from ..db import make_engine, run_migrations
from ..engine import checkpoints, seed
from ..engine.agent import ModelFactory, build_model
from ..engine.core import Engine
from ..engine.runner import Runner
from ..engine.sandboxes import SandboxProvider, make_provider
from ..mcp_server import build_mcp
from ..middleware import RequestContext
from . import activity, chat, dotties, schedules, skills, system, wiki
from .errors import ApiError, install_handlers

ROOT = Path(__file__).resolve().parents[3]  # the repository (or /app in the image): alembic.ini, frontend/dist


def create_app(
    settings: Settings | None = None,
    model_factory: ModelFactory = build_model,
    provider: SandboxProvider | None = None,
) -> FastAPI:
    """`model_factory` and `provider` are what tests replace: a scripted model, no sandbox."""
    settings = settings or get_settings()

    mcp = build_mcp(lambda: app.state.session_factory)
    mcp_app = mcp.streamable_http_app()  # creates mcp.session_manager, which the lifespan runs

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        run_migrations(settings)
        checkpoints.setup(settings)
        db = make_engine(settings)
        sessions = sessionmaker(db, expire_on_commit=False)
        app.state.session_factory = sessions
        app.state.provider = provider or make_provider(settings)
        with sessions() as s:
            seed.seed_skills(s)
            s.commit()
        engine = Engine(settings, db, sessions, Runner(settings, sessions, app.state.provider, model_factory))
        app.state.engine = engine
        if settings.engine_enabled:
            engine.start()
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            engine.stop()
            db.dispose()

    app = FastAPI(
        title="Dottie",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        lifespan=lifespan,
        # operation ids are the handlers' names: the generated client gets listDotties(), not listDottiesApiDottiesGet()
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.settings = settings
    install_handlers(app)
    app.add_middleware(RequestContext)  # added last, so it runs first: every response gets its id and headers

    api = APIRouter(prefix="/api")

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in (dotties, chat, wiki, schedules, skills, activity, system):
        api.include_router(module.router)
    app.include_router(api)
    app.mount("/mcp", mcp_app)  # Dottie as an MCP server: see mcp_server.py
    _serve_frontend(app, ROOT / "frontend" / "dist")
    return app


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """The built SPA: real files as they are, every other path gets index.html (the router takes it from there)."""
    if not dist.is_dir():
        return  # not built (tests, or `npm run dev` serves it)
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise ApiError("not_found", f"No API endpoint /{path}", 404)  # never the SPA for a mistyped API call
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist.resolve()):
            return FileResponse(file)
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

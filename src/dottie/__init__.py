def main() -> None:
    import uvicorn

    from .api.app import create_app
    from .config import get_settings
    from .middleware import setup_logging

    settings = get_settings()
    setup_logging(settings.log_json)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_config=None)

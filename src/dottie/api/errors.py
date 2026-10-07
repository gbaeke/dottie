from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException


class ApiError(Exception):
    """The one way to fail a request on purpose."""

    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status


def error_response(code: str, message: str, status: int, **extra: object) -> JSONResponse:
    """Every failure has this shape: {"error": {"code", "message", ...}}."""
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status)


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.code, exc.message, exc.status)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [{"loc": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return error_response("invalid", "The request is not valid.", 422, fields=fields)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, f"http_{exc.status_code}")
        return error_response(code, str(exc.detail), exc.status_code)


def get_or_404[T](session: Session, model: type[T], pk: object) -> T:
    """The row with this primary key, or a 404 naming it ("Note 3 not found")."""
    obj = session.get(model, pk)
    if obj is None:
        raise ApiError("not_found", f"{model.__name__} {pk} not found", 404)
    return obj

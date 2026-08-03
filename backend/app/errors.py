from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError


class AppError(Exception):
    """Единый прикладной эксепшн -> конверт {"error": {...}}."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        field: str | None = None,
        retry_after: int | None = None,
    ):
        self.status = status
        self.code = code
        self.message = message
        self.field = field
        self.retry_after = retry_after


def install_error_handlers(app) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        body = {"error": {"code": exc.code, "message": exc.message}}
        if exc.field:
            body["error"]["fields"] = {exc.field: exc.message}
        headers = {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(status_code=exc.status, content=body, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        fields = {}
        for e in exc.errors():
            loc = ".".join(str(p) for p in e["loc"] if p != "body")
            fields[loc] = e["msg"]
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "validation_error", "fields": fields}},
        )

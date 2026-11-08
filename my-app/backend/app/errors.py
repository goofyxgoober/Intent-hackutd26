"""Every error response carries a machine-readable `code` next to `detail`.

The chat layer (CHATBOT_INTEGRATION.md section 4.4) branches on these codes, so
it never has to parse message text.
"""
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

DEFAULT_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "TOO_LARGE",
    415: "UNSUPPORTED",
    422: "VALIDATION",
    428: "CONFIRMATION_REQUIRED",
    429: "RATE_LIMITED",
    502: "GITHUB_ERROR",
    503: "NOT_CONFIGURED",
}


class EngineError(HTTPException):
    def __init__(self, status_code: int, detail, code: Optional[str] = None):
        super().__init__(status_code, detail)
        self.code = code


async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = getattr(exc, "code", None) or DEFAULT_CODES.get(exc.status_code, "ERROR")
    return JSONResponse({"detail": exc.detail, "code": code}, status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{k: v for k, v in e.items() if k in ("loc", "msg", "type")} for e in exc.errors()]
    return JSONResponse({"detail": errors, "code": "VALIDATION"}, status_code=422)


def install(app) -> None:
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)

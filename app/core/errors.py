from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class ApiError(HTTPException):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(status, message, headers)
        self.code = code


def error_response(request, status, code, message, *, details=None, headers=None):
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message, "details": details or []},
            "request_id": request.state.request_id,
        },
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(
            request,
            exc.status_code,
            getattr(exc, "code", f"HTTP_{exc.status_code}"),
            exc.detail,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [
            {
                "location": [
                    "<extra>" if error["type"] == "extra_forbidden" and i else part
                    for i, part in enumerate(error["loc"])
                ],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return error_response(
            request,
            422,
            "VALIDATION_ERROR",
            "Request validation failed",
            details=details,
        )

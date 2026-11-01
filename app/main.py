from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.logging_setup import setup_logging
from app.runtime import Runtime
from app.web import api_router

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
log = logging.getLogger("frabot.web")

CSP = (
    "default-src 'self'; img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
    "frame-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'"
)


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    runtime_holder: dict[str, Runtime] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logs = setup_logging(os.getenv("LOG_LEVEL", "INFO"))
        directory = Path(data_dir or os.getenv("FRABOT_DATA_DIR", "/data"))
        runtime = Runtime(directory, logs)
        runtime_holder["runtime"] = runtime
        app.state.runtime = runtime
        await runtime.start()
        log.info(
            "Pannello in ascolto",
            extra={"ctx_version": __version__, "ctx_data_dir": str(directory)},
        )
        try:
            yield
        finally:
            await runtime.shutdown()

    app = FastAPI(
        title="FraBot",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.include_router(api_router)

    @app.get("/health", include_in_schema=False)
    async def health(request: Request):
        runtime = getattr(request.app.state, "runtime", None)
        ok = bool(runtime and runtime.db.healthcheck())
        return JSONResponse(
            status_code=200 if ok else 503,
            content={
                "status": "ok" if ok else "error",
                "version": __version__,
                "database": "ok" if ok else "error",
            },
        )

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def middleware(request: Request, call_next):
        started = time.perf_counter()
        path = request.url.path
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api"):
            # Umbrel's proxy authenticates the browser, but we still block
            # cross-site form posts: a custom header cannot be set by them.
            if request.headers.get("x-requested-with") != "FraBot":
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Richiesta non autorizzata."},
                    headers={"X-Content-Type-Options": "nosniff"},
                )
        try:
            response = await call_next(request)
        except Exception:
            log.exception("Errore non gestito su %s %s", request.method, path)
            return JSONResponse(
                status_code=500, content={"detail": "Errore interno del pannello."}
            )
        elapsed = (time.perf_counter() - started) * 1000
        if path.startswith("/api") and (request.method != "GET" or response.status_code >= 400):
            if response.status_code >= 500:
                log.error(
                    "Richiesta %s %s -> %s (%.0f ms)",
                    request.method, path, response.status_code, elapsed,
                )
            else:
                # Expected client errors (offline bot, validation) are not
                # panel events; keeping them at DEBUG leaves the log readable.
                log.debug(
                    "Richiesta %s %s -> %s (%.0f ms)",
                    request.method, path, response.status_code, elapsed,
                )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("Content-Security-Policy", CSP)
        if path.startswith("/api") or path == "/health":
            response.headers.setdefault("Cache-Control", "no-store")
        elif path.startswith("/static"):
            # No hashed asset names: revalidate so a container update cannot
            # leave an old JS bundle talking to a newer API.
            response.headers.setdefault("Cache-Control", "no-cache")
        else:
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": "Dati non validi: controlla i campi del modulo."},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.exception("Errore API non gestito su %s", request.url.path)
        return JSONResponse(
            status_code=500, content={"detail": "Errore interno del pannello."}
        )

    return app


app = create_app()

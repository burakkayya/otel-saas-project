"""FastAPI uygulama girişi."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.db import SessionLocal, init_db
from app.routers import admin, api, auth, hotel, public
from app.web import CsrfError, Forbidden, LoginRequired, render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    from app.seed import ensure_base

    with SessionLocal() as db:
        ensure_base(db)
    scheduler = None
    if settings.scheduler_enabled:
        from app.scheduler import start_scheduler

        scheduler = start_scheduler()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title=f"{settings.app_name} API", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.add_middleware(
        SessionMiddleware, secret_key=settings.secret_key, session_cookie="or_session",
        max_age=settings.session_max_age, same_site="lax", https_only=settings.secure_cookies,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(public.router)
    app.include_router(auth.router)
    app.include_router(hotel.router)
    app.include_router(admin.router)
    app.include_router(api.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Oturum gerekli"}, status_code=401)
        return RedirectResponse(f"/giris?next={exc.next_url}", status_code=303)

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc: Forbidden):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Yetkisiz"}, status_code=403)
        return render(request, "errors/error.html", status_code=403, code=403,
                      title="Bu sayfaya erişim yetkiniz yok",
                      message="Hesabınızın rolü bu ekranı görüntülemeye izin vermiyor.")

    @app.exception_handler(CsrfError)
    async def _csrf(request: Request, exc: CsrfError):
        return render(request, "errors/error.html", status_code=400, code=400,
                      title="Oturum doğrulaması başarısız",
                      message="Form süresi dolmuş olabilir. Sayfayı yenileyip tekrar deneyin.")

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        title = "Sayfa bulunamadı" if exc.status_code == 404 else "Bir hata oluştu"
        return render(request, "errors/error.html", status_code=exc.status_code, code=exc.status_code,
                      title=title, message=str(exc.detail) if exc.status_code != 404 else
                      "Aradığınız sayfa taşınmış ya da hiç var olmamış olabilir.")

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.errors()}, status_code=422)
        return render(request, "errors/error.html", status_code=422, code=422, title="Geçersiz istek",
                      message="Gönderilen bilgiler eksik ya da hatalı biçimde.")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # pragma: no cover - savunma
        log.exception("Beklenmeyen hata: %s", request.url.path)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Sunucu hatası"}, status_code=500)
        return render(request, "errors/error.html", status_code=500, code=500, title="Beklenmeyen bir hata oluştu",
                      message="Hata kaydedildi. Lütfen birkaç dakika sonra tekrar deneyin.")

    return app


app = create_app()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.auth_routes import router as auth_router
from app.api.routes import router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine
from app.models import Anomaly, CostRecord, Recommendation, ResourceSnapshot, User
from app.services.auth import AuthService
from app.db.session import SessionLocal
from app.tasks.scheduler import scheduler_service

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        AuthService(db).ensure_bootstrap_admin()
    finally:
        db.close()
    if settings.scheduler_enabled:
        scheduler_service.start()
    try:
        yield
    finally:
        scheduler_service.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(auth_router)
app.include_router(router)

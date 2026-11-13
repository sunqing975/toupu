# 投谱 Toupu API 入口。模块化单体：路由按业务模块挂载，启动时执行未应用的迁移。
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from fastapi import FastAPI

from alembic import command
from app.accounts.router import router as accounts_router
from app.core import errors
from app.core.config import get_settings
from app.funds.router import router as funds_router
from app.imports.router import router as imports_router
from app.instruments.router import router as instruments_router
from app.market_data.router import router as market_data_router
from app.performance.router import router as performance_router
from app.positions.router import router as positions_router
from app.snapshots.router import router as snapshots_router
from app.transactions.router import router as transactions_router

BACKEND_DIR = Path(__file__).resolve().parents[1]


def run_migrations() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if get_settings().run_migrations_on_startup:
        run_migrations()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="投谱 Toupu", version=settings.app_version, lifespan=lifespan)

    errors.register_error_handlers(app)
    app.include_router(accounts_router)
    app.include_router(instruments_router)
    app.include_router(transactions_router)
    app.include_router(funds_router)
    app.include_router(imports_router)
    app.include_router(positions_router)
    app.include_router(market_data_router)
    app.include_router(performance_router)
    app.include_router(snapshots_router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "app": settings.app_name, "version": settings.app_version}

    return app


app = create_app()

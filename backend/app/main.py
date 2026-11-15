# 投谱 Toupu API 入口。模块化单体：路由按业务模块挂载，启动时执行未应用的迁移。
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from fastapi import FastAPI

from alembic import command
from app.accounts.router import router as accounts_router
from app.agent.chat_router import router as agent_chat_router
from app.agent.conversations import router as agent_conversations_router
from app.agent.definitions_router import router as agent_definitions_router
from app.agent.mcp_router import router as agent_mcp_router
from app.agent.mcp_server import mcp_server, mount_mcp
from app.agent.models_router import router as agent_models_router
from app.agent.router import router as agent_router
from app.agent.runs import recover_interrupted
from app.agent.runs import router as agent_runs_router
from app.agent.skill_packages import router as skill_packages_router
from app.core import errors
from app.core.config import get_settings
from app.db.backup import router as backups_router
from app.funds.advisory import router as advisory_router
from app.funds.router import router as funds_router
from app.imports.platform_assets import router as platform_assets_router
from app.imports.router import router as imports_router
from app.instruments.router import router as instruments_router
from app.ledger.router import router as ledger_router
from app.market_data.router import router as market_data_router
from app.performance.holdings_overview import router as holdings_overview_router
from app.performance.overview import router as overview_router
from app.performance.router import router as performance_router
from app.plans.router import router as plans_router
from app.positions.router import router as positions_router
from app.risk.router import router as risk_router
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
    recover_interrupted()
    # FastAPI/Starlette 的 Mount 不会触发被挂载子应用（MCP）的 lifespan，
    # 因此显式运行 MCP 的 session_manager 生命周期。session_manager 是单例，
    # 同一进程内 lifespan 被多次进入（测试用 TestClient 多次开合）时不可重复
    # run()，第二次起会抛 RuntimeError，直接忽略以保持应用可启动。
    if mcp_server is not None and mcp_server._session_manager is not None:
        try:
            async with mcp_server._session_manager.run():
                yield
        except RuntimeError:
            yield
    else:
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="投谱 Toupu", version=settings.app_version, lifespan=lifespan)

    errors.register_error_handlers(app)
    app.include_router(backups_router)
    app.include_router(accounts_router)
    app.include_router(instruments_router)
    app.include_router(transactions_router)
    app.include_router(funds_router)
    app.include_router(advisory_router)
    app.include_router(imports_router)
    app.include_router(platform_assets_router)
    app.include_router(ledger_router)
    app.include_router(positions_router)
    app.include_router(market_data_router)
    app.include_router(performance_router)
    app.include_router(overview_router)
    app.include_router(holdings_overview_router)
    app.include_router(snapshots_router)
    app.include_router(risk_router)
    app.include_router(agent_router)
    app.include_router(agent_models_router)
    app.include_router(agent_definitions_router)
    app.include_router(skill_packages_router)
    app.include_router(agent_conversations_router)
    app.include_router(agent_chat_router)
    app.include_router(agent_runs_router)
    app.include_router(agent_mcp_router)
    app.include_router(plans_router)

    if mcp_server is not None:
        mount_mcp(app)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "app": settings.app_name, "version": settings.app_version}

    return app


app = create_app()

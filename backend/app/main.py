# 投谱 Toupu API 入口。模块化单体：路由按业务模块逐步挂载。
from fastapi import FastAPI

from app.core import errors
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="投谱 Toupu", debug=settings.debug)

    errors.register_error_handlers(app)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()

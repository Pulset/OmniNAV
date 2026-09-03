"""OmniNAV API 入口：路由挂载 + 调度器生命周期 + 前端静态托管。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import all_routers
from app.core.config import get_settings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 部署约束：API 与调度器同进程，必须以单 worker 运行
    # （uvicorn --workers N 或多副本会重复调度：重复推送与快照并发写冲突）
    scheduler = None
    if get_settings().enable_scheduler:
        from app.jobs.scheduler import build_scheduler

        scheduler = build_scheduler()
        scheduler.start()
        logger.info("APScheduler 已启动（22:00 简报 / 06:00 清算 / 盘中监控）")
    yield
    if scheduler:
        scheduler.shutdown(wait=False)
    from app.core.db import engine

    await engine.dispose()


app = FastAPI(
    title="OmniNAV API",
    description="个人全资产净值化复盘系统",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,  # Cookie 会话跨端口开发联调必需；生产同源不依赖 CORS
)

for router in all_routers:
    app.include_router(router, prefix="/api")

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    logger.info("已托管前端静态文件: %s", FRONTEND_DIST)

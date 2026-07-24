from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.analyze import router as analyze_router
from .config import settings

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router, prefix="/api")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


# ============================================================
# 一体化部署：后端同时托管前端 dist（单进程单端口）
# ============================================================
# dev 模式（未 build 前端）时此目录不存在，不挂载，仍可单独 `npx vite` 开发。
# 离线分发包里 frontend/dist 已 build，此处自动托管，访问 http://localhost:8000
# 同时拿到前端页面和 /api/* 接口（同源，无 CORS 问题）。
# 必须放在所有 /api/* 路由注册之后，否则会拦截 API 请求。
#
# 路径解析顺序：
#   1. 环境变量 LINEAGE_FRONTEND_DIST（桌面打包版由 desktop.py 设置，指向 exe 同级 frontend/dist）
#   2. 默认：相对 main.py 回溯三级的 frontend/dist（dev 与便携包布局）
import os
_FRONTEND_DIST = Path(
    os.environ.get("LINEAGE_FRONTEND_DIST")
    or (Path(__file__).resolve().parent.parent.parent / "frontend" / "dist")
)
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")

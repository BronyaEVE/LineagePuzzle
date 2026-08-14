from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.analyze import router as analyze_router
from .config import settings
from .services import store


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动预热实体图缓存：首次请求即可 O(1) 查询上下游
    store.warm_cache()
    # 安全提示：绑非回环地址且未配置令牌时，LAN 内任何人可无鉴权访问全部 API
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

# 响应压缩：/api/graph、/api/column-mappings 等大 JSON 载荷（可到数 MB）
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def token_auth_middleware(request: Request, call_next):
    """可选 API 令牌鉴权（LINEAGE_TOKEN 环境变量设置后生效）。

    用于便携版 0.0.0.0 LAN 共享模式的最小防护：未携带令牌的 /api/* 请求
    一律 401。令牌可通过 ?token= 查询参数或 Authorization: Bearer 头携带
    （前端从自身 URL 的 ?token= 读取并附加，launcher 生成的 URL 自带）。
    未配置令牌时本中间件直通（本地/桌面模式），静态资源不受影响。
    """
    token = settings.api_token
    if token and request.url.path.startswith("/api"):
        provided = request.query_params.get("token") or _bearer(request)
        if provided != token:
            return JSONResponse({"detail": "未授权：缺少或错误的 API 令牌"}, status_code=401)
    return await call_next(request)


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):]
    return None


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

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec —— LineagePuzzle 桌面版打包配置。

产出布局（--onedir）：
    dist/LineagePuzzle/
      ├─ LineagePuzzle.exe          ← 入口（desktop.py 编译）
      ├─ _internal/                  ← 所有 Python 依赖 + app 包 + frontend/dist
      └─ backend/data/              ← 用户数据（运行时创建，store.py 写这里）

关键设计：
- desktop.py 在函数内部 `import uvicorn` / `import webview`，且用字符串
  "app.main:app" 让 uvicorn 动态加载 → PyInstaller 静态分析发现不了完整依赖链。
  所以这里用 collect_all 强制收集整个 web 栈，并把 backend/app 作为 datas 拷入。
- sqlglot[c] 有 204 个 mypyc 编译的 .pyd，collect_all 能完整收集。

打包命令（在项目根，已 build 前端后）：
    pyinstaller LineagePuzzle.spec --noconfirm
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []

# ---- 核心 web 栈：collect_all 强制完整收集（静态分析漏掉的延迟 import 链）----
# 每个 collect_all 返回 (datas, binaries, hiddenimports)
_CORE_PKGS = [
    "fastapi", "starlette", "uvicorn", "anyio",
    "pydantic", "pydantic_core", "pydantic_settings",
    "networkx", "filelock",
    "sqlglot",                 # 204 个 mypyc .pyd
    "webview",                 # pywebview + 平台后端
]
for pkg in _CORE_PKGS:
    try:
        _d, _b, _h = collect_all(pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception as e:
        print(f"WARN: collect_all({pkg}) failed: {e}")

# pywebview 的 Windows 后端依赖（pythonnet/clr_loader，含 C 扩展）
for pkg in ["clr_loader", "pythonnet"]:
    try:
        _d, _b, _h = collect_all(pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass

# ---- 可选在线 PG 模式（若装了 psycopg2/SQLAlchemy 才收集）----
for pkg in ["sqlalchemy", "psycopg2", "greenlet"]:
    try:
        _d, _b, _h = collect_all(pkg)
        if _d or _b or _h:
            datas += _d
            binaries += _b
            hiddenimports += _h
    except Exception:
        pass

# ---- uvicorn 运行时动态 import 的协议模块（显式补充）----
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan", "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    "httptools", "websockets",
]

# ---- backend/app 包：字符串 "app.main:app" 静态分析发现不了，显式拷入 ----
datas += [
    ("backend/app", "app"),
]

# ---- 前端构建产物：拷到 _internal/frontend/dist（desktop.py 在 _MEIPASS 下找）----
datas += [
    ("frontend/dist", "frontend/dist"),
]


a = Analysis(
    ["desktop.py"],
    pathex=["backend"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 只排除确定无用的测试工具。distutils/setuptools 被多个运行时包引用，
        # 排除会导致 collect_all 冲突（ValueError: already imported as ExcludedModule）。
        "pytest", "tests", "unittest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LineagePuzzle",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                   # UPX 压缩易触发杀软误报，关闭
    console=False,               # 桌面应用：无控制台窗口
    icon=None,                   # TODO: 可加 docs/images/favicon.ico
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LineagePuzzle",
)

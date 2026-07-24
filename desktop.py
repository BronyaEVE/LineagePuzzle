# -*- coding: utf-8 -*-
"""LineagePuzzle 桌面版入口（PyWebView 窗口模式）。

与 launcher.pyw（便携包：开浏览器访问 localhost）并列，这是「桌面窗口」形态：
    Python 主进程
      ├─ daemon 线程：跑 uvicorn（host 127.0.0.1:8000）
      └─ 主线程：PyWebView 开窗口加载 http://127.0.0.1:8000（阻塞）

关窗 = 主线程 webview.start() 返回 = 主进程退出 = daemon 线程随之终止。
从而从架构上根除「关浏览器后 uvicorn 后台残留」的痛点。

布局约定（PyInstaller --onedir 产出）：
    LineagePuzzle/
      ├─ LineagePuzzle.exe          ← 本脚本编译产物
      ├─ _internal/                  ← PyInstaller 依赖（含 app/、sqlglot 等）
      └─ frontend/dist/             ← 前端构建产物（spec 的 datas 拷进来）

开发态运行（未打包）：直接 `python desktop.py`，按项目根/frontend/dist 找前端。
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

# ============================================================
# 路径与环境准备（必须在 import uvicorn / app 之前完成）
# ============================================================

# 本脚本所在目录：开发态是项目根，打包态是 LineagePuzzle/（exe 同级）
if getattr(sys, "frozen", False):
    # PyInstaller 打包后：exe 同级目录（用户可见、可写，放数据/日志）
    BASE_DIR = Path(sys.executable).resolve().parent
    # _MEIPASS 指向 _internal，所有依赖（含 app/、frontend/dist）都在里面
    _INTERNAL = Path(getattr(sys, "_MEIPASS", BASE_DIR / "_internal"))
    # 让 uvicorn 能 import app.main:app（app 包在 _internal 里）
    sys.path.insert(0, str(_INTERNAL))
else:
    # 开发态：项目根，把 backend/ 加入 path 才能找到 app.main
    BASE_DIR = Path(__file__).resolve().parent
    _INTERNAL = BASE_DIR
    sys.path.insert(0, str(BASE_DIR / "backend"))

# 前端 dist 路径：
#   打包态在 _internal/frontend/dist（spec datas 落点）
#   开发态在项目根 frontend/dist
FRONTEND_DIST = _INTERNAL / "frontend" / "dist"
if FRONTEND_DIST.exists():
    os.environ["LINEAGE_FRONTEND_DIST"] = str(FRONTEND_DIST)

# 数据目录：用户数据与程序分离，放 exe 同级（打包态）或 backend/data（开发态）
# 注意：base_library.zip 和 .pyd 在 _internal 里是只读的，数据必须写到 BASE_DIR
DATA_DIR = BASE_DIR / "backend" / "data"
os.environ["LINEAGE_DATA_DIR"] = str(DATA_DIR)
DATA_DIR.mkdir(parents=True, exist_ok=True)

HOST = "127.0.0.1"   # 桌面单机模式，无需对外暴露
PORT = 8000
URL = f"http://{HOST}:{PORT}"
START_TIMEOUT = 20   # uvicorn 启动 + sqlglot 首次加载留足余量


# ============================================================
# 工具函数
# ============================================================

def is_port_in_use(port: int = PORT) -> bool:
    """socket connect 精确检测端口是否被监听。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex((HOST, port)) == 0
    finally:
        s.close()


def wait_port_ready(timeout: float = START_TIMEOUT) -> bool:
    """轮询等待端口就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_in_use():
            return True
        time.sleep(0.3)
    return False


def check_webview2_runtime() -> bool:
    """检测 WebView2 运行时是否安装（Win10 1803+/Win11 通常预装）。"""
    try:
        import winreg
    except ImportError:
        return True  # 非 Windows，跳过检测
    # WebView2 运行时注册表键（系统级 + 用户级）
    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_CURRENT_USER,
         r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    ]
    for root, subkey in reg_paths:
        try:
            with winreg.OpenKey(root, subkey) as k:
                ver, _ = winreg.QueryValueEx(k, "pv")
                if ver and ver != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def log(msg: str) -> None:
    """桌面版日志：打包后写 exe 同级 logs/desktop.log；开发态打到 stderr。"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "desktop.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line, file=sys.stderr)


# ============================================================
# 主流程
# ============================================================

# uvicorn Server 实例：关窗后主动 should_exit 让它优雅关闭、立即释放端口，
# 而非依赖 daemon 线程在进程退出时被 OS 强杀（后者会拖延端口 TIME_WAIT）。
_server: "uvicorn.Server | None" = None
_server_thread: "threading.Thread | None" = None


def start_server() -> None:
    """在 daemon 线程里跑 uvicorn（用 Server 实例，便于关窗后主动停止）。"""
    global _server
    import uvicorn
    from uvicorn import Config
    log(f"starting uvicorn on {HOST}:{PORT}")
    _server = uvicorn.Server(
        Config("app.main:app", host=HOST, port=PORT, log_level="warning", access_log=False)
    )
    _server.run()


def shutdown_server() -> None:
    """关窗后调用：通知 uvicorn 退出并等待其线程结束，确保端口立即释放。"""
    global _server, _server_thread
    if _server is not None:
        log("shutting down uvicorn")
        _server.should_exit = True
    if _server_thread is not None and _server_thread.is_alive():
        _server_thread.join(timeout=5)


def main() -> int:
    import webview

    # 1) WebView2 运行时检测（缺失则无法开窗）
    if not check_webview2_runtime():
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "未检测到 Microsoft Edge WebView2 运行时。\n\n"
                "LineagePuzzle 桌面版需要 WebView2 才能显示界面。\n"
                "请从微软官网下载安装后重试：\n"
                "https://developer.microsoft.com/microsoft-edge/webview2/",
                "LineagePuzzle 启动失败",
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass
        log("ERROR: WebView2 runtime not found")
        return 1

    # 2) 前端 dist 检测
    if not FRONTEND_DIST.exists():
        log(f"ERROR: frontend dist not found at {FRONTEND_DIST}")
        return 1

    # 3) 单实例：端口已被监听 = 已有实例在跑 → 只开窗口加载，不重复起服务
    if is_port_in_use():
        log("another instance running, opening window only")
        webview.create_window(
            "LineagePuzzle", URL,
            width=1400, height=900, min_size=(1000, 600),
        )
        webview.start()
        return 0

    # 4) 起 uvicorn daemon 线程（引用存模块级，关窗后主动停止用）
    global _server_thread
    _server_thread = threading.Thread(target=start_server, daemon=True)
    _server_thread.start()

    # 5) 等端口就绪
    if not wait_port_ready():
        log(f"ERROR: server not ready within {START_TIMEOUT}s")
        shutdown_server()
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"服务在 {START_TIMEOUT} 秒内未启动成功。\n"
                f"请查看 logs/desktop.log 排查（可能是端口被占用）。",
                "LineagePuzzle 启动失败",
                0x10,
            )
        except Exception:
            pass
        return 1

    # 6) 开窗口（主线程阻塞）。关窗后此行返回，再主动停 uvicorn 释放端口。
    log("server ready, opening window")
    webview.create_window(
        "LineagePuzzle", URL,
        width=1400, height=900, min_size=(1000, 600),
    )
    webview.start()
    log("window closed, shutting down")
    shutdown_server()
    log("exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())

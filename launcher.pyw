# -*- coding: utf-8 -*-
"""LineagePuzzle 便携包启动器（无窗口）。

由 run.bat / stop.bat 通过 pythonw.exe 调用，避免控制台窗口弹出。
所有用户可见输出写到 logs/launcher.log（launcher 自身日志）和
logs/lineage.log（uvicorn 输出重定向）。

用法:
    pythonw.exe launcher.pyw start    # 启动 uvicorn 后台 + 自动开浏览器
    pythonw.exe launcher.pyw stop     # 按 PID 文件停止（兜底按端口查）
    pythonw.exe launcher.pyw status   # 查询运行状态（写入 launcher.log）

设计要点:
    - 用 subprocess.Popen 启动 uvicorn 子进程，进程对象在内存里，
      但同时写 PID 文件做兜底（用户硬关电脑后下次能清理）。
    - 端口就绪轮询避免 PID 查询时序问题（uvicorn 启动到监听有延迟）。
    - 单实例靠检测 uvicorn 端口本身：端口已占用 = 服务已在跑，
      直接开浏览器而非重复启动。
"""
from __future__ import annotations

import os
import sys
import socket
import subprocess
import time
import webbrowser
from pathlib import Path

# === 路径常量（基于 launcher.pyw 所在目录）===
ROOT = Path(__file__).resolve().parent
PY_EXE = ROOT / "python" / "pythonw.exe"        # 用无窗口版 Python 跑 uvicorn
APP_DIR = ROOT / "app"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "lineage.log"              # uvicorn stdout/stderr
LAUNCHER_LOG = LOG_DIR / "launcher.log"         # 启动器自身日志（调试用）
PID_FILE = LOG_DIR / "lineage.pid"

HOST = "0.0.0.0"
PORT = 8000
URL = f"http://localhost:{PORT}"
START_TIMEOUT = 15  # 等待端口就绪的最大秒数


def log(msg: str) -> None:
    """写到启动器日志（追加），便于排查问题。用户不可见（pythonw 无窗口）。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LAUNCHER_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def is_port_in_use(port: int = PORT) -> bool:
    """精确检测端口是否被监听（socket connect，不受 netstat 格式影响）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def wait_port_ready(timeout: int = START_TIMEOUT) -> bool:
    """轮询等待端口就绪，返回是否在超时内就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_in_use():
            return True
        time.sleep(0.5)
    return False


def read_pid() -> int | None:
    """从 PID 文件读取 PID，文件不存在/损坏返回 None。"""
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def write_pid(pid: int) -> None:
    PID_FILE.write_text(str(pid), encoding="utf-8")


def clear_pid() -> None:
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def find_pid_by_port(port: int = PORT) -> int | None:
    """用 PowerShell Get-NetTCPConnection 按端口查监听进程 PID（兜底）。"""
    cmd = (
        "try { "
        "(Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue "
        "| Select-Object -First 1).OwningProcess "
        "} catch { '' }" % port
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=5,
        )
        out = result.stdout.strip()
        return int(out) if out else None
    except (subprocess.SubprocessError, ValueError):
        return None


def taskkill(pid: int) -> bool:
    """taskkill /F /PID 强制结束进程，返回是否成功。"""
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except subprocess.SubprocessError:
        return False


# ============================================================
# 命令实现
# ============================================================

def cmd_start() -> int:
    """启动 uvicorn 后台 + 自动开浏览器。已运行则只开浏览器。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 已有服务在跑 → 直接开浏览器，不重复启动
    if is_port_in_use():
        log("start: service already running, opening browser only")
        webbrowser.open(URL)
        return 0

    if not PY_EXE.exists():
        log(f"start: ERROR pythonw.exe not found at {PY_EXE}")
        return 1

    # 启动 uvicorn 子进程：pythonw.exe 跑 uvicorn，stdout/stderr 重定向到日志
    # CREATE_NO_WINDOW 确保即使被某种方式唤起也不弹窗（pythonw 本身无窗口，双保险）
    log(f"start: launching uvicorn via {PY_EXE}")
    with open(LOG_FILE, "w", encoding="utf-8") as log_fp:
        proc = subprocess.Popen(
            [str(PY_EXE), "-m", "uvicorn", "app.main:app",
             "--host", HOST, "--port", str(PORT)],
            cwd=str(APP_DIR),
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    write_pid(proc.pid)
    log(f"start: uvicorn started pid={proc.pid}, waiting for port ready")

    # 等端口就绪后查 PID（更准：避免 uvicorn 还没监听就查不到）
    if not wait_port_ready(START_TIMEOUT):
        log(f"start: WARNING port not ready within {START_TIMEOUT}s, "
            f"uvicorn may still be starting; check {LOG_FILE}")
        # 不算失败——uvicorn 可能仍在启动，让用户手动开浏览器
        webbrowser.open(URL)
        return 0

    # 端口已就绪：记录真正的监听 PID（Popen 的 pid 可能是父进程，
    # Get-NetTCPConnection 拿到的是真正监听端口的进程，更精确）
    listener_pid = find_pid_by_port()
    if listener_pid:
        write_pid(listener_pid)
        log(f"start: port ready, listener pid={listener_pid}")
    webbrowser.open(URL)
    return 0


def cmd_stop() -> int:
    """停止 uvicorn 服务。优先按 PID 文件，兜底按端口查。"""
    stopped = False

    # 策略 1：PID 文件
    pid = read_pid()
    if pid:
        log(f"stop: trying pid file pid={pid}")
        if taskkill(pid):
            stopped = True
            log(f"stop: killed pid={pid} via pid file")

    # 策略 2：端口查（PID 文件失效或 taskkill 失败时）
    if not stopped:
        pid = find_pid_by_port()
        if pid:
            log(f"stop: fallback to port lookup, pid={pid}")
            if taskkill(pid):
                stopped = True
                log(f"stop: killed pid={pid} via port lookup")

    clear_pid()

    # 等端口真正释放（taskkill 后端口可能 TIME_WAIT 一会儿）
    if stopped:
        for _ in range(10):
            if not is_port_in_use():
                break
            time.sleep(0.3)

    if stopped:
        log("stop: service stopped successfully")
    else:
        log("stop: no running service found")
    return 0 if stopped else 1


def cmd_status() -> int:
    """查询运行状态，结果写日志（调试用）。"""
    running = is_port_in_use()
    pid_file = read_pid()
    pid_port = find_pid_by_port()
    log(f"status: running={running}, pid_file={pid_file}, pid_port={pid_port}")
    return 0 if running else 1


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    try:
        if cmd == "start":
            return cmd_start()
        elif cmd == "stop":
            return cmd_stop()
        elif cmd == "status":
            return cmd_status()
        else:
            log(f"unknown command: {cmd}")
            return 2
    except Exception as e:
        log(f"ERROR in {cmd}: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

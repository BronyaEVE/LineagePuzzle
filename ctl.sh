#!/usr/bin/env bash
# ============================================================
# DataLineage Visualizer 启停脚本
# 用法:
#   ./ctl.sh start                      # 默认端口: 后端 8000, 前端 5173
#   ./ctl.sh start -b 9000 -f 3000      # 指定后端和前端端口
#   ./ctl.sh stop                       # 停止所有服务（优雅关闭）
#   ./ctl.sh restart                    # 重启（保留端口配置）
#   ./ctl.sh status                     # 查看服务状态
# ============================================================

set -e

# === 默认配置 ===
BACKEND_PORT=8000
FRONTEND_PORT=5173
PID_DIR="./run"
PID_FILE="$PID_DIR/pids"
LOG_DIR="./logs"
GRACE_TIMEOUT=5

# === 颜色 ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# === 参数解析 ===
ACTION=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        start|stop|restart|status) ACTION="$1"; shift ;;
        -b|--backend-port) BACKEND_PORT="$2"; shift 2 ;;
        -f|--frontend-port) FRONTEND_PORT="$2"; shift 2 ;;
        -h|--help)
            echo "用法: $0 {start|stop|restart|status} [-b 后端端口] [-f 前端端口]"
            echo ""
            echo "命令:"
            echo "  start    启动后端和前端服务"
            echo "  stop     停止所有服务（优雅关闭 → 强制清理）"
            echo "  restart  重启所有服务（保留端口配置）"
            echo "  status   查看服务状态"
            echo ""
            echo "选项:"
            echo "  -b, --backend-port PORT    后端端口 (默认: 8000)"
            echo "  -f, --frontend-port PORT   前端端口 (默认: 5173)"
            exit 0 ;;
        *) error "未知参数: $1"; exit 1 ;;
    esac
done

[[ -z "$ACTION" ]] && { error "请指定操作: start | stop | restart | status"; exit 1; }

# === 工具函数 ===
save_ports() {
    mkdir -p "$PID_DIR"
    echo "BACKEND_PORT=$BACKEND_PORT" > "$PID_DIR/ports"
    echo "FRONTEND_PORT=$FRONTEND_PORT" >> "$PID_DIR/ports"
}
load_ports() { [[ -f "$PID_DIR/ports" ]] && source "$PID_DIR/ports"; }

check_port() {
    local port=$1
    netstat -an 2>/dev/null | grep -q ":${port}.*LISTEN" 2>/dev/null && return 0
    return 1
}

wait_for_port() {
    local port=$1 name=$2 max_wait=${3:-15} count=0
    while ! check_port "$port"; do
        sleep 1; count=$((count + 1))
        [[ $count -ge $max_wait ]] && { warn "$name 在 ${max_wait}s 内未就绪 (端口 $port)"; return 1; }
    done
    return 0
}

wait_for_port_free() {
    local port=$1 name=$2 max_wait=${3:-8} count=0
    while check_port "$port"; do
        sleep 1; count=$((count + 1))
        [[ $count -ge $max_wait ]] && { warn "$name 端口 $port 未释放"; return 1; }
    done
    return 0
}

check_health() { curl -s "http://localhost:${BACKEND_PORT}/api/health" > /dev/null 2>&1; }

# 递归获取进程及其所有子进程的 PID
_get_all_descendants() {
    local pid=$1
    echo "$pid"
    local children
    children=$(ps -o pid= --ppid "$pid" 2>/dev/null || true)
    for child in $children; do
        _get_all_descendants "$child"
    done
}

# 通过端口查找监听进程的 PID
_pid_on_port() {
    netstat -ano 2>/dev/null | grep ":${1}.*LISTEN" | awk '{print $5}' | sort -u | head -1
}

# 强制杀进程（Windows 上用 taskkill，兼容 Git Bash）
_force_kill() {
    local pid=$1
    if command -v taskkill &>/dev/null; then
        taskkill //F //PID "$pid" &>/dev/null || true
    else
        kill -9 "$pid" 2>/dev/null || true
    fi
}

# 强制杀进程及其子进程树（Windows taskkill //T 杀进程树）
_force_kill_tree() {
    local pid=$1
    if command -v taskkill &>/dev/null; then
        taskkill //F //T //PID "$pid" &>/dev/null || true
    else
        kill -9 "$pid" 2>/dev/null || true
    fi
}

# ============================================================
# START
# ============================================================
do_start() {
    mkdir -p "$PID_DIR" "$LOG_DIR"

    if [[ -f "$PID_FILE" ]]; then
        if do_status_quiet; then info "服务已在运行中"; do_status; return 0; fi
        warn "清理残留 PID 文件"; rm -f "$PID_FILE"
    fi

    info "=============================="
    info "  DataLineage Visualizer 启动"
    info "=============================="
    echo ""

    check_port "$BACKEND_PORT"  && { error "后端端口 $BACKEND_PORT 已被占用"; exit 1; }
    check_port "$FRONTEND_PORT" && { error "前端端口 $FRONTEND_PORT 已被占用"; exit 1; }

    save_ports

    # 启动后端
    info "启动后端服务 (端口: $BACKEND_PORT)..."
    cd "$SCRIPT_DIR/backend"
    nohup python -m uvicorn app.main:app \
        --host 0.0.0.0 --port "$BACKEND_PORT" \
        > "$SCRIPT_DIR/$LOG_DIR/backend.log" 2>&1 &
    BACKEND_PID=$!
    cd "$SCRIPT_DIR"
    wait_for_port "$BACKEND_PORT" "后端"
    info "后端服务已就绪 (PID: ${CYAN}$BACKEND_PID${NC})"

    # 启动前端
    info "启动前端服务 (端口: $FRONTEND_PORT)..."
    cd "$SCRIPT_DIR/frontend"
    nohup npx vite --port "$FRONTEND_PORT" \
        > "$SCRIPT_DIR/$LOG_DIR/frontend.log" 2>&1 &
    FRONTEND_PID=$!
    cd "$SCRIPT_DIR"
    wait_for_port "$FRONTEND_PORT" "前端"
    info "前端服务已就绪 (PID: ${CYAN}$FRONTEND_PID${NC})"

    # 保存 PID
    cat > "$PID_FILE" <<EOF
BACKEND_PID=$BACKEND_PID
FRONTEND_PID=$FRONTEND_PID
EOF

    echo ""
    info "=============================="
    info "  所有服务已启动"
    info "=============================="
    do_status
}

# ============================================================
# STOP（优雅关闭）
# ============================================================
do_stop() {
    if [[ ! -f "$PID_FILE" ]]; then
        warn "未找到 PID 文件，尝试端口清理..."
        load_ports
        _cleanup_by_ports
        return 0
    fi

    source "$PID_FILE"
    load_ports
    info "停止服务..."

    _graceful_stop "$FRONTEND_PID" "前端" "$FRONTEND_PORT"
    _graceful_stop "$BACKEND_PID"  "后端" "$BACKEND_PORT"

    rm -f "$PID_FILE" "$PID_DIR/ports"
    info "已清理 PID 文件"
}

# 优雅关闭单个服务
_graceful_stop() {
    local pid=$1 name=$2 port=$3

    if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
        warn "$name 进程已不存在"
        return 0
    fi

    # 阶段1: SIGTERM 主进程 + 所有子进程
    info "优雅关闭 $name (PID: $pid)..."
    local all_pids
    all_pids=$(_get_all_descendants "$pid")
    for p in $all_pids; do
        kill "$p" 2>/dev/null || true
    done
    # 同时用 taskkill /T 优雅关闭进程树
    if command -v taskkill &>/dev/null; then
        taskkill //PID "$pid" &>/dev/null || true
    fi

    # 等待端口释放
    if wait_for_port_free "$port" "$name" "$GRACE_TIMEOUT"; then
        info "$name 已优雅关闭"
        return 0
    fi

    # 阶段2: SIGKILL 强制终止所有子进程
    warn "$name 未在 ${GRACE_TIMEOUT}s 内关闭，强制终止..."
    # 用 taskkill /F /T 强制杀整个进程树
    _force_kill_tree "$pid"

    # 最终清理：通过端口杀残留进程
    sleep 1
    local stale_pid
    stale_pid=$(_pid_on_port "$port")
    if [[ -n "$stale_pid" && "$stale_pid" != "0" ]]; then
        _force_kill "$stale_pid"
        info "$name 残留进程已清理 (PID: $stale_pid)"
    fi
}

# 通过端口清理所有残留进程
_cleanup_by_ports() {
    for pair in "$FRONTEND_PORT:前端" "$BACKEND_PORT:后端"; do
        local port=${pair%%:*} name=${pair##*:}
        local pid
        pid=$(_pid_on_port "$port")
        if [[ -n "$pid" && "$pid" != "0" ]]; then
            _force_kill_tree "$pid"
            info "$name 残留进程已终止 (PID: $pid)"
        fi
    done
}

# ============================================================
# STATUS
# ============================================================
do_status_quiet() {
    [[ ! -f "$PID_FILE" ]] && return 1
    source "$PID_FILE"
    kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null
}

do_status() {
    if [[ ! -f "$PID_FILE" ]]; then
        echo -e "  ${RED}服务未运行${NC} (无 PID 文件)"
        return 1
    fi
    source "$PID_FILE"
    load_ports

    echo ""
    printf "  %-8s %-6s %-8s %-10s %s\n" "服务" "PID" "端口" "状态" "地址"
    echo "  ----------------------------------------------------------"

    local bs fs
    if kill -0 "$BACKEND_PID" 2>/dev/null; then
        check_health && bs="${GREEN}运行中${NC}" || bs="${YELLOW}启动中${NC}"
    else
        bs="${RED}已停止${NC}"
    fi
    printf "  %-8s %-6s %-8s " "后端" "$BACKEND_PID" "${BACKEND_PORT:-8000}"
    echo -e "$bs  http://localhost:${BACKEND_PORT:-8000}"

    if kill -0 "$FRONTEND_PID" 2>/dev/null; then
        fs="${GREEN}运行中${NC}"
    else
        fs="${RED}已停止${NC}"
    fi
    printf "  %-8s %-6s %-8s " "前端" "$FRONTEND_PID" "${FRONTEND_PORT:-5173}"
    echo -e "$fs  http://localhost:${FRONTEND_PORT:-5173}"

    echo ""
    echo -e "  API 文档:  ${CYAN}http://localhost:${BACKEND_PORT:-8000}/docs${NC}"
    echo -e "  日志目录:  ${CYAN}$LOG_DIR/${NC}"
    echo ""
}

# ============================================================
# RESTART
# ============================================================
do_restart() {
    load_ports
    info "重启服务..."
    do_stop
    info "等待端口释放..."
    sleep 3
    # 先清理残留
    _cleanup_by_ports
    sleep 2
    wait_for_port_free "$BACKEND_PORT"  "后端" 5 2>/dev/null || true
    wait_for_port_free "$FRONTEND_PORT" "前端" 10 2>/dev/null || true
    do_start
}

# ============================================================
case "$ACTION" in
    start)   do_start   ;;
    stop)    do_stop    ;;
    restart) do_restart ;;
    status)  do_status  ;;
esac

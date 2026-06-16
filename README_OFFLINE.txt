============================================================
DataLineage Visualizer 离线部署说明 / Offline Deployment Guide
============================================================

【系统要求 / Requirements】
  - 操作系统 / OS: Windows x64
  - Python: 3.11.5（3.10 / 3.12 也可运行，建议 3.11.5）
    * 安装时勾选 "Add Python to PATH"
    * 验证 / verify: 命令行执行 python --version
  - PostgreSQL（可选 / optional）:
    * 内网有 PG → 分析时可填连接配置，启用表结构校验/列补充
    * 内网无 PG → 工具支持纯离线分析（基于 SQL 语法解析，无需数据库）

------------------------------------------------------------
【启动步骤 / Quick Start】
------------------------------------------------------------

  1. 解压本分发包到任意目录
     Extract this package to any folder (avoid Chinese/spaces in path)

  2. 双击 start.bat / Double-click start.bat

  3. 等待出现以下字样即表示启动成功：
     Wait until you see:
     ============================================================
       Service starting, please wait...
       Browser URL: http://localhost:8000
     ============================================================

  4. 浏览器打开 http://localhost:8000
     Open http://localhost:8000 in browser

  5. 停止服务：在命令行窗口按 Ctrl+C
     Stop: press Ctrl+C in the console window

------------------------------------------------------------
【两种分析模式 / Two Analysis Modes】
------------------------------------------------------------

  新建分析时，"高级选项：数据库连接（可选）" 默认折叠：
  The "Advanced: Database Connection (optional)" panel is collapsed by default.

  ■ 离线模式（默认）/ Offline mode (default, try first)
    - 不展开数据库配置，直接粘贴 DML 脚本点"分析血缘"
      Don't expand DB config, paste DML script and click analyze.
    - 基于 sqlglot 语法解析提取表级血缘，无需数据库
      Pure AST parsing, no DB needed.
    - 提示 / toast: "分析完成（离线模式）"

  ■ 在线模式（需内网有 PostgreSQL）/ Online mode (needs intranet PG)
    - 展开"高级选项"，填写 host/port/库名/用户名/密码
      Expand "Advanced", fill host/port/db/user/password.
    - 额外校验表是否真实存在、补充列信息
      Validates table existence, enriches column info.
    - 提示 / toast: "分析完成（已连接数据库校验）"

------------------------------------------------------------
【常见问题 / FAQ】
------------------------------------------------------------

  Q: 启动报错 "python not found"
  A: Python 未安装或未加入 PATH。重装时勾选 "Add Python to PATH"。
     Python not installed or not in PATH. Reinstall with "Add to PATH" checked.

  Q: 启动报错 "Python version mismatch"
  A: 本包 wheel 为 Python 3.11 编译。若你的 Python 是 3.12，部分含 C 扩展的包
     (psycopg2/greenlet) 可能装不上。解决：改装 Python 3.11.5。
     Wheels are built for 3.11. On 3.12 some C-extension wheels may not install.

  Q: 启动报错 "端口 8000 被占用" / port 8000 in use
  A: 编辑 start.bat，把 set "PORT=8000" 改成其他端口（如 8888）。
     Edit start.bat, change PORT=8000 to another value (e.g. 8888).

  Q: 填了数据库配置但提示连接失败 / DB connection failed
  A: 检查：① PG 服务是否启动 ② host/port/库名/账号是否正确 ③ 防火墙。
     连不上时会自动降级为离线模式，不影响出血缘。
     Falls back to offline mode automatically if DB unreachable.

  Q: 数据保存在哪 / where is data stored
  A: backend\data\ 目录 (tables.json / edges.jsonl / scripts/*.json)。
     删除脚本会自动回收相关数据。备份此目录即可备份所有结果。

  Q: 如何让同事访问 / share with colleagues
  A: start.bat 监听 0.0.0.0:8000，同事用 http://你的IP:8000 访问。
     把 backend\data\ 拷给他，他启动后能看到相同全局图谱。

------------------------------------------------------------
【目录结构 / Structure】
------------------------------------------------------------
  (your extract dir)
    +-- backend\           backend code (do not modify)
    +-- frontend\dist\     frontend pages (do not modify)
    +-- wheels\            offline deps (auto-installed on first run, keep)
    +-- requirements.txt   dependency manifest
    +-- start.bat          launcher (double-click to run)
    +-- this README

============================================================

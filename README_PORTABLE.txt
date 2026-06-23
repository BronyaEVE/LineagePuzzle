============================================================
DataLineage Visualizer - 便携版 / Portable Edition
============================================================

【特点 / Features】
  - 开箱即用：双击 run.bat 即可，无需安装任何软件
  - 自带 Python：内嵌 Python 3.13.12 运行时，不依赖系统 Python
  - 自带全部依赖：FastAPI + 数据分析库（pandas/numpy/matplotlib）+ 办公文档库（docx/xlsx/pptx）等
  - 浏览器访问：http://localhost:8000

  Zero install: double-click run.bat, nothing to install.
  Bundled Python 3.13.12 runtime, all deps included.

------------------------------------------------------------
【启动 / Quick Start】
------------------------------------------------------------

  1. 解压本包到任意目录（路径避免中文和空格更稳妥）
     Extract to any folder.

  2. 双击 run.bat / Double-click run.bat

  3. 等待出现：
     Wait until you see:
     ============================================================
       Browser: http://localhost:8000
     ============================================================

  4. 浏览器打开 http://localhost:8000
     Open http://localhost:8000 in browser.

  5. 停止：在命令行窗口按 Ctrl+C
     Stop: press Ctrl+C in the console.

------------------------------------------------------------
【目录结构 / Structure】
------------------------------------------------------------
  (your extract folder)
    +-- python\              内嵌 Python 3.13.12 + 全部依赖 (do not modify)
    |   +-- python.exe
    |   +-- Lib\site-packages\   fastapi/pandas/numpy/... 等
    |   +-- python313._pth       已配置好，勿改
    +-- app\                 后端代码 (do not modify)
    +-- frontend\dist\       前端页面 (do not modify)
    +-- run.bat              启动脚本 (double-click to run)
    +-- this README

------------------------------------------------------------
【两种分析模式 / Two Analysis Modes】
------------------------------------------------------------
  新建分析时，"高级选项：数据库连接（可选）" 默认折叠。

  ■ 离线模式（默认，推荐先试）
    - 不填数据库配置，直接粘贴 DML 脚本点"分析血缘"
    - 纯 SQL 语法解析提取表级+列级血缘，无需数据库
    - 提示："分析完成（离线模式）"

  ■ 在线模式（需内网有 PostgreSQL）
    - 展开"高级选项"，填写 host/port/库名/用户名/密码
    - 额外校验表是否存在、补充列信息
    - 提示："分析完成（已连接数据库校验）"

------------------------------------------------------------
【列级血缘 / Column-level Lineage】
------------------------------------------------------------
  - 点血缘图上任意一条边 → 右侧弹出该边的列级映射
    （目标列 <- 源列 + 变换表达式）
  - 支持 INSERT INTO t(a,b) SELECT x,y、JOIN、聚合 SUM、表达式 price*qty
  - SELECT * 无法解析列级，会显示"无列级映射"（表级血缘仍正常）

------------------------------------------------------------
【内置 Python 库 / Bundled Libraries】
------------------------------------------------------------
  便携版自带以下库，可直接在 app 代码中使用：
    - Web: fastapi, uvicorn, pydantic
    - 数据分析: numpy, pandas, matplotlib
    - 办公文档: openpyxl, xlsxwriter, python-docx, python-pptx
    - SQL 解析: sqlglot
    - 数据库: sqlalchemy, psycopg2-binary
    - 工具: requests, jinja2, filelock

------------------------------------------------------------
【常见问题 / FAQ】
------------------------------------------------------------

  Q: 启动报错 "python.exe not found"
  A: run.bat 找不到内嵌 Python。确认 python\ 子目录存在且含 python.exe。
     这通常意味着包不完整，重新解压。

  Q: 端口 8000 被占用 / port in use
  A: 编辑 run.bat，把 set "PORT=8000" 改成其他端口（如 8888）。

  Q: 启动报 DLL 错误
  A: 极少见。确认解压完整、未损坏。Windows 需有 VC++ 运行时（一般自带）。

  Q: 数据保存在哪
  A: app\data\ 目录（tables.json / edges.jsonl / scripts/*.json）。
     备份此目录即备份所有分析结果。

  Q: 让同事访问
  A: run.bat 监听 0.0.0.0:8000，同事用 http://你的IP:8000 访问。
     拷贝 app\data\ 给他，他启动后能看到相同全局图谱。

  Q: 如何在内网无 PG 环境用
  A: 直接用，离线模式不需要数据库。DB 配置留空即可。

============================================================

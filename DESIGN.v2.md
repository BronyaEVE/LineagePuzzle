# DataLineage Visualizer — 项目设计文档（v2）

> 本文档反映当前已实现的功能状态，不再是纯设计稿。

## 1. 项目概述

### 1.1 背景

在数据仓库和数据库管理场景中，DML（Data Manipulation Language）脚本（如 `INSERT INTO ... SELECT`、`UPDATE`、`MERGE` 等）广泛用于数据加工和流转。随着脚本数量和复杂度增长，理清表与表之间的数据血缘关系（Data Lineage）变得越来越困难。

### 1.2 目标

构建一个 **DML 脚本血缘关系分析与可视化工具**，采用 **增量拼图** 模式：

- 每次分析一个 DML 脚本，自动提取其血缘关系
- 多次分析结果累积到全局血缘图谱中，像拼图一样逐步构建完整的数据库血缘关系
- 支持脚本管理（查看、重命名、删除），删除脚本后全局图谱自动更新
- 支持按脚本筛选查看，或查看全部累积图谱

### 1.3 核心价值

- **增量式构建**：每次分析一个脚本，逐步拼凑完整的血缘图谱，无需一次性提交所有脚本
- **离线优先**：以静态 AST 解析为主，**无需数据库连接即可完成血缘提取**；数据库连接仅用于结构校验与列信息补充
- **表级 + 列级血缘**：不仅追踪表间流转，还解析到列级映射（目标列 ← 源列 + 变换表达式）
- **参数化 SQL 支持**：支持 ETL 模板占位符 `${param}`，配合全局参数映射表替换成实际值
- **数据治理**：快速定位数据的来源和去向
- **影响分析**：评估上游表变更对下游的影响范围
- **代码审计**：直观展示复杂 ETL 脚本的数据流转逻辑
- **临时表追踪**：识别脚本中的临时表（`CREATE TEMP/TABLE`），还原完整的中间数据流转链路
- **持久化存储**：分析结果保存在 JSON 文件中，写操作受文件锁保护，支持并发安全
- **开箱即用**：绿色包携带嵌入式 Python 运行时，目标机零安装

### 1.4 设计原则

| 原则 | 说明 |
|------|------|
| **AST 唯一血缘来源** | 血缘提取统一走 `sqlglot` AST，确定性强、无外部依赖；EXPLAIN 路径已移除 |
| **全限定命名** | 所有表以 `schema.table` 作为唯一标识，杜绝同名表冲突；裸表名补 `public` |
| **可离线** | 即使没有数据库连接，也能完成血缘分析（`ast_only` 模式） |
| **列级与表级解耦** | 列级血缘是表级的增强层，列级失败/降级不影响表级（保底） |
| **并发安全** | 所有写操作在 `store.lock` 文件锁保护下原子完成 |

---

## 2. 系统架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                          前端页面（React + antd v6）                    │
│                                                                      │
│  Header: [搜索框] [参数映射] [新建分析]                                │
│                                                                      │
│  ┌──────────┐  ┌──────────────────────────┐  ┌──────────────────┐   │
│  │ 脚本列表  │  │     全局/脚本血缘图谱      │  │  语句分段面板     │   │
│  │ (左栏)    │  │     React Flow 可视化     │  │  (右栏)          │   │
│  │          │  │  + 列级 Drawer + 搜索聚焦  │  │                  │   │
│  └──────────┘  └──────────────────────────┘  └──────────────────┘   │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ REST API (FastAPI, 同源)
┌──────────────────────────────▼───────────────────────────────────────┐
│                     后端分析器（FastAPI）                              │
│                                                                      │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌──────────────────────┐   │
│  │ 预处理器  │ │ 语句拆分  │ │ 血缘提取   │ │  Store 持久化存储     │   │
│  │+参数替换 │ │          │ │AST 表+列级│ │  (文件锁+JSONL+反向索引)│   │
│  └──────────┘ └──────────┘ └───────────┘ └──────────────────────┘   │
│                                   │                  │               │
│                          ┌────────▼────────┐ ┌───────▼─────────┐    │
│                          │ sqlglot AST     │ │ data/            │    │
│                          │ (纯静态,可离线)  │ │ ├── tables.json  │    │
│                          └────────┬────────┘ │ ├── edges.jsonl  │    │
│                                   │          │ ├── param_mapping│    │
│                          ┌────────▼────────┐ │ └── scripts/*.json│   │
│                          │ DB 校验器(可选)  │ └─────────────────┘    │
│                          │ INFO_SCHEMA     │                        │
│                          └─────────────────┘                        │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│                      PostgreSQL 数据库（可选）                        │
│  - 表结构校验 + 列信息补充（不参与血缘提取）                            │
└──────────────────────────────────────────────────────────────────────┘
```

四层架构：

| 层级 | 职责 |
|------|------|
| **前端页面层** | 三栏布局 + Header 工具栏（搜索/参数映射/新建分析）。血缘图用 React Flow 渲染，支持点边看列级、搜索聚焦、节点展开 |
| **分析器层（后端）** | 预处理（含 `${param}` 替换）→ 语句拆分 → AST 血缘提取（表级 + 列级）→ 可选 DB 校验 |
| **持久化存储层（Store）** | JSON/JSONL 文件存储，带文件锁、script_ids 反向索引、全表扫孤立表清理 |
| **数据库层（PostgreSQL，可选）** | 表结构校验与列信息补充；不参与血缘提取 |

---

## 3. 核心流程

### 3.1 整体分析流程

```
用户提交脚本
     │
     ▼
步骤1: 参数替换 → ${param} 用全局映射表替换成实际值（保留参数名当标识符）
     │
     ▼
步骤2: 预处理 → 去注释、压缩空格
     │
     ▼
步骤3: 语句拆分 → 保留 CREATE/INSERT/UPDATE/DELETE/MERGE
     │
     ▼
步骤4: AST 血缘提取 → 表级（源→目标）+ 列级（目标列←源列+变换）
     │
     ▼
步骤5: 数据库校验(可选) → 表是否存在、列信息补充、校验 AST 结果
     │
     ▼
步骤6: 持久化存储 → 保存到 JSON + 更新全局图谱（文件锁保护）
     │
     ▼
步骤7: 前端展示 → 刷新脚本列表和全局图谱
```

### 3.2 增量拼图机制

每次分析一个脚本后：
1. 脚本保存为 `data/scripts/{script_id}.json`
2. 表合并到 `data/tables.json`（以 `schema.table` 为 key，带 `script_ids` 反向索引）
3. 边追加到 `data/edges.jsonl`（每行一条，带 `script_id` + `column_mappings`）

删除一个脚本后：
1. 删除脚本文件
2. 重写 `edges.jsonl`，移除该脚本的边
3. **全表扫** `tables.json`，移除该 script_id，`script_ids` 变空的表删除（孤立表清理）

### 3.3 参数占位符替换

ETL 脚本常用 `${icl_schema}`、`${batch_date}` 等模板占位符，sqlglot 无法解析（ParseError）。在预处理阶段替换：

| 占位符类型 | 替换规则 | 示例 |
|-----------|---------|------|
| schema 参数（无映射） | 保留参数名当标识符 | `${icl_schema}.orders` → `icl_schema.orders` |
| schema 参数（有映射） | 用映射实际值 | `icl_schema=ods` → `ods.orders` |
| 参数拼表名 | 各自替换后拼接 | `${schema}_${env}.report` → `dw_prod.report` |
| 时间/值参数 | 替换成标识符 | `WHERE dt=${batch_date}` → `dt = batch_date` |

全局参数映射表通过 API 管理（`GET/PUT /api/param-mapping`），存 `data/param_mapping.json`，分析时自动应用。

### 3.4 列级血缘提取

独立模块 `column_lineage.py`，与表级解耦。能力边界：

| 场景 | 能力 |
|------|------|
| 显式列 `INSERT INTO t(a,b) SELECT x,y` | ✅ 完整映射 |
| JOIN + 别名 `o.id, c.name` | ✅ 解析到各自物理表 |
| 表达式 `price*qty` | ✅ 多源列 + transform |
| 聚合 `SUM(x)` | ✅ 源列 + transform |
| CTAS / 子查询 | ✅ 支持 |
| UPDATE SET | ✅ 左=目标列，右表达式找源列 |
| 单表无别名 `SELECT x FROM src` | ✅ 回退到唯一源表 |
| `SELECT *` | ⚠️ 降级为空（表级边保底） |

### 3.5 DML 表级血缘提取规则

| 语句类型 | 目标表 | 源表 | 提取规则 |
|----------|--------|------|----------|
| `CREATE [TEMP] TABLE t AS SELECT` | `t` | SELECT 的 FROM/JOIN | CTAS |
| `INSERT INTO t SELECT ...` | `t` | SELECT 的 FROM/JOIN | INSERT-SELECT |
| `UPDATE t SET ... FROM s` | `t` | FROM 子句 | PG 扩展 |
| `DELETE FROM t USING s` | `t` | USING | PG 扩展 |
| `MERGE INTO t USING src` | `t` | `src` | MERGE |

CTE 内部的表照常提取为源；CTE 名本身不作为全局节点（除非物化为 temp table）。`schema1.t` 与 `schema2.t` 视为两个不同节点。

---

## 4. 存储设计（JSON 文件 + 文件锁）

### 4.1 目录结构

```
backend/data/
├── tables.json              # 全局表注册表（schema.table 为 key，带 script_ids 反向索引）
├── edges.jsonl              # 全局血缘边（JSON Lines，追加写，带 column_mappings）
├── param_mapping.json       # 全局参数映射表（${param} → 实际值）
├── store.lock               # 文件锁
└── scripts/
    └── {script_id}.json     # 单个脚本分析结果
```

### 4.2 全局表注册表 tables.json

以 `schema.table` 为 key，每个表带 `script_ids` 反向索引：

```json
{
  "public.orders": {
    "schema": "public", "name": "orders", "type": "source",
    "columns": [{"name": "id", "type": "INTEGER"}],
    "source": "database", "resolved": true,
    "script_ids": ["abc-123", "def-456"], "script_count": 2,
    "first_seen": "...", "last_seen": "..."
  }
}
```

### 4.3 全局血缘边 edges.jsonl

```jsonl
{"edge_id":"uuid","source":"public.orders","target":"public.report","operation":"INSERT","script_id":"abc-123","statement_seq":1,"created_at":"...","column_mappings":[{"target_table":"public.report","target_column":"a","source_table":"public.orders","source_columns":["x"],"transformation":null}]}
```

### 4.4 并发与一致性

| 机制 | 说明 |
|------|------|
| **文件锁**（`filelock`） | 所有写操作在 `store.lock` 保护下原子完成 |
| **追加写** | 新边 append 到 `edges.jsonl` 尾部，O(1) |
| **删除重写** | 删除脚本时过滤重写 edges.jsonl（低频） |
| **script_ids 全表扫** | 孤立表清理遍历 tables.json，移除 script_id，空的删表 |

> **设计要点**：孤立表清理用全表扫而非"只看 edges 涉及的表"，因为表可能从 database_info 或无源表 lineage 登记进 tables.json 但不在 edges 里（UPDATE 无源表场景，边不写 edges.jsonl）。这是修复孤立节点残留 bug 的关键。

### 4.5 向后兼容

`VisEdge` / `GlobalEdge` 的 `column_mappings` 字段用 `Field(default_factory=list)`，旧数据（无此字段）反序列化为空数组，不报错。

---

## 5. 模块设计

### 5.1 前端页面

| 子模块 | 功能 |
|--------|------|
| Header 工具栏 | 搜索框（表名+字段名模糊匹配）、参数映射配置、新建分析 |
| 脚本列表（左栏） | 脚本增删改查，点选切换视图 |
| 血缘图谱（中栏） | React Flow 渲染，节点自适应宽度、点击展开全名、点边弹列级 Drawer、搜索聚焦 |
| 语句分段面板（右栏） | 语句列表，点击高亮对应边 |
| 参数映射弹窗 | 动态表格行编辑 `${param}` → 实际值映射 |
| 搜索框 | AutoComplete 模糊匹配，选中后 React Flow fitView 聚焦 + 高亮 |

**交互逻辑：**

| 操作 | 效果 |
|------|------|
| 点击左侧脚本 | 中栏切换为该脚本血缘图，右栏显示语句分段 |
| 点击语句 | 该 seq 的所有边高亮蓝色粗线 |
| 点击节点 | 展开完整表名（再点收起），白边框发光 |
| 点击边 | 弹列级 Drawer（目标列←源列+变换），单边高亮 |
| 搜索选中表 | fitView 聚焦该节点 + 展开高亮 |
| 搜索选中字段 | fitView 聚焦相关边两端 + 单边高亮 + 弹 Drawer |
| 全局图选中脚本 | 该脚本的所有边高亮（script_id 匹配） |
| 删除脚本 | 全局图自动更新（移除边，全表扫清理孤立表） |

### 5.2 后端服务

| 模块 | 职责 |
|------|------|
| `preprocessor.py` | 参数替换 + 去注释/空格 |
| `splitter.py` | 语句拆分（考虑 dollar-quote） |
| `lineage_extractor.py` | 表级血缘（AST），调用 column_lineage |
| `column_lineage.py` | 列级血缘（AST，独立模块） |
| `analyzer.py` | 编排：预处理→拆分→提取→校验→组装 |
| `store.py` | 持久化（文件锁 + JSONL + script_ids 全表扫） |
| `db_connector.py` | 可选 DB 校验（INFORMATION_SCHEMA） |
| `normalize.py` | 表名归一化（schema.table 全限定） |

### 5.3 可视化模块

- **节点**：颜色按角色（source 绿/intermediate 黄/target 蓝），宽度自适应（fit-content + min/max 上下限 + label 截断）
- **边**：流动动画（animated），高亮优先级：单边 > 语句级 > 脚本级 > 默认全流动
- **布局**：自定义拓扑分层，TB/LR 参数分离（TB 层内水平按宽度，LR 层内垂直按高度）
- **聚焦**：React Flow fitView 程序化平移缩放

---

## 6. 数据模型

### 6.1 列级血缘映射 ColumnMapping

```json
{
  "target_table": "public.report",
  "target_column": "total",
  "source_table": "public.orders",
  "source_columns": ["amount"],
  "transformation": "SUM(amount)"
}
```

`source_columns` 是数组（表达式可能多源列，如 `price*qty` → `["price","qty"]`）。纯列引用时 transformation 为 null。

### 6.2 边（携带列级映射）

`VisEdge` / `GlobalEdge` 都有 `column_mappings: ColumnMapping[]` 字段，点边时前端展示。

---

## 7. API 设计

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/analyze` | POST | 提交脚本分析（database_config 可选，None 为离线模式） |
| `/api/scripts` | GET | 脚本列表 |
| `/api/scripts/{id}` | GET/DELETE | 脚本详情/删除 |
| `/api/scripts/{id}/name` | PUT | 重命名 |
| `/api/scripts/{id}/statements/{seq}` | PUT | 修正语句解析 |
| `/api/global-graph` | GET | 全局图谱（含 column_mappings） |
| `/api/tables` | GET | 全局表注册表 |
| `/api/param-mapping` | GET/PUT | 参数映射表 |
| `/api/health` | GET | 健康检查 |

---

## 8. 部署

### 8.1 开发模式

```bash
ctl.sh start    # 前端 vite dev :5173 + 后端 uvicorn :8000
```

### 8.2 一体化部署（FastAPI 托管前端）

`main.py` mount `frontend/dist` 为静态文件，单进程单端口（:8000）同时服务 API + 页面。dev 模式（未 build）不挂载，不影响 vite 开发。

### 8.3 绿色包（便携版，零安装）

`pack_portable.bat` 产出 `dist-portable/`：

| 文件 | 作用 |
|------|------|
| `pack_portable.bat` | 开发机打包（华为镜像下 embeddable + 清华源装依赖） |
| `run.bat` | 内网双击启动（用绿色 Python） |
| `README_PORTABLE.txt` | 部署说明 |

- 内嵌 Python 3.13.12 embeddable（解压即用，不依赖系统 Python）
- 全量依赖装到嵌入 Python 的 site-packages（含数据分析 + 办公文档库）
- 目标机双击 `run.bat` 即用，浏览器开 http://localhost:8000

---

## 9. 技术选型

| 组件 | 技术 |
|------|------|
| 前端框架 | React + TypeScript + antd v6 |
| 可视化 | @xyflow/react (React Flow v12) |
| 后端框架 | Python FastAPI |
| SQL 解析 | sqlglot（AST，唯一血缘来源） |
| 数据库驱动 | SQLAlchemy + psycopg2（仅校验用） |
| 布局 | 自定义拓扑分层（TB/LR 分离参数） |
| 文件锁 | filelock |
| 持久化 | JSON / JSONL |
| 绿色包 | Python embeddable distribution |

---

## 10. 验证方案

### 10.1 单元测试（151 passed）

| 测试对象 | 用例数 |
|----------|--------|
| 预处理（含参数替换） | ~10 |
| 语句拆分 | ~12 |
| AST 表级血缘 | ~20 |
| 列级血缘 | 15 |
| DB 校验 | ~6 |
| Store 持久化（含孤立表全表扫清理、JSONL、script_ids、并发） | ~35 |
| 参数映射 | 19 |
| normalize（全限定名） | 13 |

### 10.2 集成测试

- 离线模式：无 DB 连接纯 AST 完成血缘提取
- 在线模式：DB 校验表存在性
- 端到端：提交脚本 → 全局图更新 → 删除脚本 → 全表扫清理孤立表
- 参数化：`${param}` 映射后血缘正确

### 10.3 绿色包验证

- 嵌入式 Python 17/17 C 扩展 import OK（pydantic_core/numpy/pandas/matplotlib 等）
- run.bat 启动后 API + 前端都通

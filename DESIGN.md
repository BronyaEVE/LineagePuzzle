# DataLineage Visualizer — 项目设计文档

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
- **数据治理**：快速定位数据的来源和去向
- **影响分析**：评估上游表变更对下游的影响范围
- **代码审计**：直观展示复杂 ETL 脚本的数据流转逻辑
- **临时表追踪**：识别脚本中的临时表（`CREATE TEMP/TABLE`），还原完整的中间数据流转链路
- **持久化存储**：分析结果保存在 JSON 文件中，刷新页面或重启服务后数据不丢失

---

## 2. 系统架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                          前端页面（React）                            │
│                                                                      │
│  ┌──────────┐  ┌──────────────────────────┐  ┌──────────────────┐   │
│  │ 脚本列表  │  │     全局血缘图谱          │  │  语句分段面板     │   │
│  │ (左栏)    │  │     （累积拼图）          │  │  (右栏)          │   │
│  └──────────┘  └──────────────────────────┘  └──────────────────┘   │
│                                                                      │
│  [新建分析] → 弹窗: 数据库配置 + 脚本输入 → 分析血缘                    │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ REST API
┌──────────────────────────────▼───────────────────────────────────────┐
│                     后端分析器（FastAPI）                              │
│                                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────────────┐   │
│  │ 预处理器  │ │ 语句拆分  │ │ 血缘提取  │ │  Store 持久化存储层    │   │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────────────┘   │
│                                                    │                 │
│                                          ┌─────────▼──────────┐     │
│                                          │  data/              │     │
│                                          │  ├── tables.json    │     │
│                                          │  ├── edges.json     │     │
│                                          │  └── scripts/*.json │     │
│                                          └────────────────────┘     │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│                      PostgreSQL 数据库                                │
│                                                                      │
│  - 表结构（INFORMATION_SCHEMA）                                       │
│  - 执行计划（EXPLAIN，不修改数据）                                      │
└──────────────────────────────────────────────────────────────────────┘
```

系统采用 **前后端分离** 架构，包含四个核心层：

| 层级 | 职责 |
|------|------|
| **前端页面层** | 三栏布局：脚本列表、全局血缘图谱、语句分段面板。新建分析通过弹窗完成 |
| **分析器层（后端）** | 核心逻辑：脚本预处理、语句解析、血缘提取 |
| **持久化存储层（Store）** | JSON 文件存储：全局表注册表、全局血缘边、各脚本分析结果 |
| **数据库层（PostgreSQL）** | 数据支撑：提供表结构信息、执行计划 |

---

## 3. 核心流程

### 3.1 整体分析流程

```
用户提交脚本
     │
     ▼
步骤1: 预处理 → 去注释、压缩空格
     │
     ▼
步骤2: 语句拆分 → 保留 CREATE/INSERT/UPDATE/DELETE/MERGE
     │
     ▼
步骤3: 数据库分析 → 表结构 + 执行计划（EXPLAIN）
     │
     ▼
步骤4: 血缘提取 → 源表 → 中间表 → 目标表
     │
     ▼
步骤5: 持久化存储 → 保存到 JSON + 更新全局图谱
     │
     ▼
步骤6: 前端展示 → 刷新脚本列表和全局图谱
```

### 3.2 增量拼图机制

每次分析一个脚本后：

1. **脚本保存**：分析结果保存为 `data/scripts/{script_id}.json`
2. **全局表更新**：脚本涉及的表合并到 `data/tables.json`（全局表注册表）
3. **全局边累积**：血缘边添加到 `data/edges.json`（标注来源脚本）
4. **前端刷新**：脚本列表和全局图谱同时更新

删除一个脚本后：

1. **移除脚本文件**：删除 `data/scripts/{script_id}.json`
2. **移除关联边**：从 `data/edges.json` 中移除该脚本的所有边
3. **清理孤立表**：从 `data/tables.json` 中移除不再被任何边引用的表
4. **前端刷新**：全局图谱自动更新

### 3.3 步骤详解

**步骤1 — 预处理**

分析器对 DML 脚本进行预处理：

- 去除注释（`--` 单行注释、`/* */` 多行注释）
- 压缩连续空格和空白行
- 按语句分隔符（`;`）拆分为独立语句
- **保留 CREATE 语句**：不过滤 `CREATE TABLE` / `CREATE TEMP TABLE`
- 过滤与数据流转无关的 DDL（`ALTER`、`DROP`）
- 为每条语句标注序号（`#1`, `#2`, `#3`...），以一个完整的 DML 脚本为一组

**步骤2 — 语句拆分**

对预处理后的脚本按 `;` 分割，保留 `CREATE`/`INSERT`/`UPDATE`/`DELETE`/`MERGE` 语句。

**步骤3 — 数据库分析**

对每条拆分后的语句，从数据库获取两类信息：

**第一类：已知的表结构信息**

| 操作 | 说明 |
|------|------|
| 读取表结构 | 查询 `INFORMATION_SCHEMA`，获取已存在表的元信息 |
| 记录临时表 | 对于脚本中 `CREATE TABLE` 定义的新表/临时表，记录其结构信息 |

**第二类：DML 执行计划**

| 操作 | 说明 |
|------|------|
| 获取执行计划 | 对 DML 语句使用 `EXPLAIN` 获取执行计划（不实际修改数据） |
| 提取血缘 | 从执行计划中提取表引用关系 |

> **优先级**：基于执行计划的血缘提取 > 基于静态语法解析的补充。

**步骤4 — 血缘提取**

提取策略（按优先级排列）：

| 优先级 | 策略 | 说明 |
|--------|------|------|
| **高** | 基于执行计划 | 解析 `EXPLAIN` 输出中的表引用节点，准确度最高 |
| **低** | 基于静态语法解析 | 通过 SQL AST 解析器识别表关系，作为补充 |

中间表/临时表处理：当脚本中出现 `CREATE TABLE` 定义的临时表时，血缘链路为：

```
源表 ──CREATE──▶ 临时表/中间表 ──INSERT──▶ 目标表
```

中间表作为独立节点保留在血缘关系中，不会被折叠或省略。

**步骤5 — 持久化存储**

分析结果存入三层 JSON 文件：

| 文件 | 内容 | 说明 |
|------|------|------|
| `scripts/{id}.json` | 完整的 AnalysisResult | 包含语句、血缘、可视化等全部信息 |
| `tables.json` | 全局表注册表 | 所有唯一表的元信息，支持表类型演化 |
| `edges.json` | 全局血缘边 | 所有脚本的血缘边，每条边标注 script_id |

**步骤6 — 前端展示**

前端三栏布局同时更新：

- **左栏脚本列表**：新增一条脚本记录
- **中栏全局图谱**：新增的节点和边自动出现在全局图中
- **状态栏**：表数量、血缘数量、脚本数量实时更新

---

## 4. 存储设计（JSON 文件）

### 4.1 目录结构

```
backend/data/
├── tables.json              # 全局表注册表（所有唯一表）
├── edges.json               # 全局血缘边（累积所有脚本的血缘关系）
└── scripts/
    ├── {script_id}.json     # 单个脚本分析结果
    └── ...
```

### 4.2 全局表注册表 `tables.json`

```json
{
  "orders": {
    "schema": "public",
    "name": "orders",
    "type": "source",
    "columns": [{"name": "id", "type": "INTEGER"}, ...],
    "source": "database",
    "first_seen": "2026-04-28T10:00:00",
    "script_count": 3,
    "last_seen": "2026-04-28T12:00:00"
  },
  "tmp_order_detail": {
    "schema": "public",
    "name": "tmp_order_detail",
    "type": "intermediate",
    "columns": [],
    "source": "script_created",
    "first_seen": "2026-04-28T10:00:00",
    "script_count": 1,
    "last_seen": "2026-04-28T10:00:00"
  }
}
```

> 表类型随使用演化：如果一个表先作为 target 出现，后来又被其他脚本引用为 source，类型更新为更综合的角色。

### 4.3 单个脚本 `scripts/{script_id}.json`

```json
{
  "analysis_id": "uuid",
  "name": "ETL_订单汇总",
  "created_at": "2026-04-28T10:00:00",
  "updated_at": "2026-04-28T10:00:00",
  "input_script": "原始脚本",
  "database_info": { ... },
  "statement_group": {
    "group_id": "uuid",
    "original_script": "...",
    "preprocessed_script": "...",
    "statements": [
      { "seq": 1, "type": "CREATE", "text": "...", "tables_referenced": [...], ... },
      { "seq": 2, "type": "INSERT", "text": "...", ... }
    ]
  },
  "lineages": [ ... ],
  "visualization": { ... }
}
```

### 4.4 全局血缘边 `edges.json`

```json
[
  {
    "edge_id": "uuid",
    "source": "orders",
    "target": "tmp_order_detail",
    "operation": "CREATE",
    "script_id": "abc-123",
    "statement_seq": 1,
    "created_at": "2026-04-28T10:00:00"
  },
  {
    "edge_id": "uuid",
    "source": "customers",
    "target": "tmp_order_detail",
    "operation": "CREATE",
    "script_id": "abc-123",
    "statement_seq": 1,
    "created_at": "2026-04-28T10:00:00"
  }
]
```

> 每条边都关联到具体的 script_id，点击边可定位到对应脚本和语句。

---

## 5. 模块设计

### 5.1 前端页面模块

**页面布局（三栏 + 弹窗）：**

```
┌──────────────────────────────────────────────────────────────────┐
│  DataLineage Visualizer                          [新建分析]       │
├──────────┬───────────────────────────────────┬───────────────────┤
│          │                                   │                   │
│  脚本列表 │     全局血缘图谱                   │  语句分段面板      │
│  (左栏)   │     （累积拼图）                   │  (右栏)           │
│          │                                   │                   │
│  ▸ ETL_  │  [orders]──▶[tmp]──▶[report]     │  选中脚本的        │
│    订单汇总│  [customers]──▶[report]          │  语句列表          │
│  ▸ 每日   │                                   │                   │
│    汇总   │  [全部] 选中脚本高亮               │  #1 CREATE ...    │
│          │                                   │  #2 INSERT ...    │
│  [+新建]  │                                   │                   │
├──────────┴───────────────────────────────────┴───────────────────┤
│  状态栏: 12 张表 | 18 条血缘 | 5 个脚本                           │
└──────────────────────────────────────────────────────────────────┘
```

| 子模块 | 功能 |
|--------|------|
| 脚本列表（左栏） | 展示所有已分析脚本的列表，支持选中、重命名、删除。点击「全部」查看全局图谱 |
| 全局血缘图谱（中栏） | 累积所有脚本的血缘关系。选中脚本时高亮该脚本的边，支持垂直/水平布局切换 |
| 语句分段面板（右栏） | 展示选中脚本的语句分段，支持点击语句高亮对应的血缘边 |
| 新建分析弹窗 | 数据库配置 + 脚本输入，分析完成后自动添加到列表并刷新全局图 |
| 状态栏 | 实时显示表数量、血缘数量、脚本数量 |

**交互逻辑：**

| 操作 | 效果 |
|------|------|
| 点击左侧脚本 | 中栏切换为该脚本的血缘图（边高亮），右栏显示该脚本的语句分段 |
| 点击「全部」按钮 | 中栏恢复为全局累积图谱 |
| 点击语句分段中的语句 | 中栏中对应的血缘边高亮为蓝色粗线 |
| 点击「新建分析」 | 弹出 Modal，填写数据库配置和脚本后分析 |
| 删除脚本 | 全局图谱自动更新（移除边，清理孤立表） |
| 重命名脚本 | 左侧脚本名称更新 |

### 5.2 DML 脚本分析器模块

**职责**：核心解析引擎

```
输入: 原始 DML 脚本文本
      │
      ▼
┌─────────────────┐
│   预处理器       │  去注释、去空格、去多余分析
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   语句拆分器     │  按 ";" 分割，保留 CREATE TABLE
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   分段存储       │  以脚本为组，每条语句标注序号单独存储
└────────┬────────┘
         │
         ▼
输出: StatementGroup
```

### 5.3 持久化存储模块（Store）

**职责**：JSON 文件的读写和全局数据管理

```
方法:
  # 脚本管理
  save_script(result: AnalysisResult)          # 保存单个脚本 + 更新全局表/边
  list_scripts() -> list[ScriptSummary]        # 列表（id, name, created_at, table_count）
  get_script(script_id) -> AnalysisResult      # 读取单个
  delete_script(script_id)                     # 删除脚本 + 清理关联的全局边和孤立表
  update_script_name(script_id, name)          # 重命名

  # 全局图谱
  get_global_graph() -> GlobalGraph            # 返回所有节点 + 所有边（带 script_id 标注）
  get_tables() -> dict[str, TableRecord]       # 全局表注册表

  # 内部方法
  _merge_tables(result)                        # 合并新表到全局注册表
  _merge_edges(result)                         # 添加新边到全局边
  _remove_edges_for_script(script_id)          # 删除脚本关联的边
  _cleanup_orphan_tables()                     # 清理不再被任何边引用的表
```

### 5.4 数据库连接模块

**职责**：与 PostgreSQL 数据库交互

分为两个子模块：

**子模块 A — 表结构信息获取**

| 操作 | 说明 |
|------|------|
| 读取已有表结构 | 查询 `INFORMATION_SCHEMA` 获取已存在表的元数据 |
| 记录脚本中的新表 | 识别脚本中 `CREATE TABLE` 定义的中间表 |
| 构建表元信息索引 | 将所有表的结构信息缓存为索引 |

**子模块 B — 执行计划获取**

| 操作 | 说明 |
|------|------|
| EXPLAIN DML 语句 | 对每条 DML 语句执行 `EXPLAIN`，获取执行计划 |
| 解析执行计划 | 从执行计划输出中提取表扫描和表操作节点 |
| 提取表引用关系 | 从执行计划中还原源表 → 目标表的映射关系 |

### 5.5 血缘关系提取模块

**职责**：从执行计划和 AST 中提取表间血缘关系

**中间表/临时表处理**：

```
源表 ──INSERT──▶ 临时表/中间表 ──INSERT──▶ 目标表
```

中间表作为独立节点保留在血缘关系中，不会被折叠或省略。

**语句与血缘的关联**：

每条血缘关系都关联到具体的语句序号，便于前端展示时定位到对应的 DML 语句。

### 5.6 可视化模块

**职责**：将血缘关系渲染为可交互的有向图

图元素定义：

- **节点类型**：
  - **源表节点**（Source）：数据来源的物理表，绿色
  - **中间表节点**（Intermediate）：脚本中 CREATE 定义的临时表，黄色
  - **目标表节点**（Target）：数据最终写入的表，蓝色
- **边**：表间的数据流向（有向箭头），标注操作类型
- **布局**：自定义拓扑排序 BFS 布局，支持垂直（TB）和水平（LR）切换

**全局图谱节点颜色规则**：

| 节点类型 | 颜色 | 判定 |
|----------|------|------|
| 纯源表 | 绿色 | 只在边的 source 端出现 |
| 纯目标表 | 蓝色 | 只在边的 target 端出现 |
| 中间表 | 黄色 | 既作为 source 又作为 target |

---

## 6. 数据模型

### 6.1 分析结果（AnalysisResult）

```json
{
  "analysis_id": "uuid",
  "name": "ETL_订单汇总",
  "created_at": "2026-04-28T10:00:00",
  "updated_at": "2026-04-28T10:00:00",
  "input_script": "原始 DML 脚本",
  "database_info": {
    "tables_from_db": [
      { "schema": "public", "table": "orders", "table_type": "source", "source": "database" }
    ],
    "tables_from_script": [
      { "schema": "public", "table": "tmp_orders", "table_type": "intermediate", "source": "script_created" }
    ]
  },
  "statement_group": {
    "group_id": "uuid",
    "original_script": "原始脚本",
    "preprocessed_script": "预处理后脚本",
    "statements": [
      { "seq": 1, "type": "CREATE", "text": "CREATE TEMP TABLE tmp_orders ...", "tables_referenced": ["orders"], "tables_created": ["tmp_orders"] },
      { "seq": 2, "type": "INSERT", "text": "INSERT INTO order_summary ...", "tables_referenced": ["tmp_orders"], "tables_modified": ["order_summary"] }
    ]
  },
  "lineages": [
    { "lineage_id": "uuid", "source_table": "orders", "target_table": "tmp_orders", "operation_type": "CREATE", "extraction_method": "execution_plan", "statement_seq": 1 },
    { "lineage_id": "uuid", "source_table": "tmp_orders", "target_table": "order_summary", "operation_type": "INSERT", "extraction_method": "execution_plan", "statement_seq": 2 }
  ],
  "visualization": {
    "nodes": [
      { "id": "orders", "label": "orders", "type": "source" },
      { "id": "tmp_orders", "label": "tmp_orders", "type": "intermediate" },
      { "id": "order_summary", "label": "order_summary", "type": "target" }
    ],
    "edges": [
      { "source": "orders", "target": "tmp_orders", "label": "CREATE", "statement_seq": 1 },
      { "source": "tmp_orders", "target": "order_summary", "label": "INSERT", "statement_seq": 2 }
    ]
  }
}
```

### 6.2 脚本摘要（ScriptSummary）

```json
{
  "analysis_id": "uuid",
  "name": "ETL_订单汇总",
  "statement_count": 2,
  "table_count": 3,
  "created_at": "2026-04-28T10:00:00",
  "updated_at": "2026-04-28T10:00:00"
}
```

### 6.3 全局图谱（GlobalGraph）

```json
{
  "nodes": [
    { "id": "orders", "label": "orders", "type": "source" },
    { "id": "tmp_orders", "label": "tmp_orders", "type": "intermediate" },
    { "id": "order_summary", "label": "order_summary", "type": "target" }
  ],
  "edges": [
    {
      "source": "orders",
      "target": "tmp_orders",
      "operation": "CREATE",
      "script_id": "abc-123",
      "statement_seq": 1
    },
    {
      "source": "tmp_orders",
      "target": "order_summary",
      "operation": "INSERT",
      "script_id": "abc-123",
      "statement_seq": 2
    }
  ]
}
```

> 全局图中的每条边都带有 `script_id`，用于按脚本筛选和高亮。

---

## 7. API 设计

### 7.1 提交分析任务

```
POST /api/analyze
```

分析完成后自动存入 Store 层，更新全局表和边。

**请求体：**

```json
{
  "script": "INSERT INTO target_table SELECT * FROM source_table;",
  "database_config": {
    "host": "localhost",
    "port": 5432,
    "database": "mydb",
    "username": "user",
    "password": "pass"
  }
}
```

**响应体：** 返回完整的 AnalysisResult。

### 7.2 脚本管理

```
GET    /api/scripts              # 脚本列表（摘要信息）
GET    /api/scripts/{id}         # 脚本详情（完整 AnalysisResult）
DELETE /api/scripts/{id}         # 删除脚本 + 清理关联边和孤立表
PUT    /api/scripts/{id}/name    # 重命名脚本
```

**脚本列表响应：**

```json
[
  {
    "analysis_id": "uuid",
    "name": "ETL_订单汇总",
    "statement_count": 2,
    "table_count": 3,
    "created_at": "2026-04-28T10:00:00",
    "updated_at": "2026-04-28T10:00:00"
  }
]
```

### 7.3 全局图谱

```
GET /api/global-graph            # 全局累积图谱（所有节点 + 所有边）
GET /api/tables                  # 全局表注册表
```

**全局图谱响应：**

```json
{
  "nodes": [...],
  "edges": [
    { "source": "orders", "target": "report", "operation": "INSERT", "script_id": "abc", "statement_seq": 1 }
  ]
}
```

### 7.4 语句管理

```
GET /api/scripts/{id}/statements              # 获取语句分段
PUT /api/scripts/{id}/statements/{seq}        # 修正语句解析结果
```

---

## 8. 技术选型

| 组件 | 推荐技术 | 说明 |
|------|----------|------|
| **前端框架** | React + TypeScript | 函数组件 + Hooks |
| **UI 组件库** | Ant Design | 表单、列表、弹窗等 |
| **可视化库** | @xyflow/react (React Flow) | 有向图渲染 |
| **代码编辑器** | Monaco Editor | SQL 编辑 |
| **后端框架** | Python FastAPI | REST API |
| **SQL 解析** | sqlglot | AST 解析 |
| **数据库驱动** | SQLAlchemy + psycopg2 | PostgreSQL 连接 |
| **布局算法** | 自定义拓扑 BFS | 无第三方依赖 |
| **持久化存储** | JSON 文件 | 轻量级，无需额外数据库 |

---

## 9. 验证方案

### 9.1 单元测试

| 测试对象 | 测试内容 | 测试数量 |
|----------|----------|----------|
| 预处理模块 | 注释移除、空格压缩、语句过滤 | 13 |
| 语句拆分器 | 多语句脚本正确拆分、边界情况 | 28 |
| 血缘提取器 | 各类 DML 语句的血缘关系提取 | 18 |
| Store 持久化层 | 保存/列表/读取/删除、全局图谱、重命名 | 16 |

### 9.2 集成测试

- 连接真实数据库，执行 `EXPLAIN` 验证执行计划解析
- 端到端测试：提交脚本 → 脚本列表新增 → 全局图谱更新 → 删除脚本 → 图谱自动清理

### 9.3 测试用例（增量拼图验证）

详见 `backend/tests/test_scripts.sql`，包含 6 个测试场景：

1. 简单 INSERT-SELECT（双源表 JOIN）
2. 包含临时表的完整流程
3. 多语句混合操作（INSERT + UPDATE）
4. 带注释的复杂 ETL 脚本
5. 多层临时表嵌套
6. 包含被过滤的 DDL（ALTER/DROP 应被忽略）

**验证流程**：依次提交 6 个用例，验证全局图谱逐步累积，删除脚本后自动清理。

# DataLineage Visualizer — 项目设计文档

## 1. 项目概述

### 1.1 背景

在数据仓库和数据库管理场景中，DML（Data Manipulation Language）脚本（如 `INSERT INTO ... SELECT`、`UPDATE`、`MERGE` 等）广泛用于数据加工和流转。随着脚本数量和复杂度增长，理清表与表之间的数据血缘关系（Data Lineage）变得越来越困难。

### 1.2 目标

构建一个 **DML 脚本血缘关系分析与可视化工具**，能够：

- 接收用户提交的 DML 脚本
- 自动解析脚本，提取表之间的数据流向关系
- 以可视化图的形式呈现血缘关系

### 1.3 核心价值

- **数据治理**：快速定位数据的来源和去向
- **影响分析**：评估上游表变更对下游的影响范围
- **代码审计**：直观展示复杂 ETL 脚本的数据流转逻辑
- **临时表追踪**：识别脚本中的临时表（`CREATE TEMP/TABLE`），还原完整的中间数据流转链路

---

## 2. 系统架构

```
┌─────────────┐      ┌──────────────────────┐      ┌─────────────┐
│             │      │                      │      │             │
│  前端页面    │─────▶│  DML 脚本分析器       │─────▶│  PVC 数据库  │
│             │      │                      │      │             │
│  - 脚本输入  │      │  - 脚本预处理         │      │  - 表结构    │
│  - 结果展示  │◀─────│  - 语句拆分           │◀─────│  - 执行计划  │
│  - 可视化    │      │  - 血缘提取           │      │             │
│             │      │                      │      │             │
└─────────────┘      └──────────────────────┘      └─────────────┘
```

系统采用 **前后端分离** 架构，包含三个核心层：

| 层级 | 职责 |
|------|------|
| **前端页面层** | 用户交互：脚本输入、参数配置、可视化结果展示 |
| **分析器层（后端）** | 核心逻辑：脚本预处理、语句解析、血缘提取 |
| **数据库层（PVC）** | 数据支撑：提供表结构信息、执行 DML 脚本、返回执行计划 |

---

## 3. 核心流程

整个分析流程分为 5 个步骤：

```
步骤1: 分析器处理 DML 脚本
         │
         ▼
步骤2: 分析器将 DML 脚本拆分为一系列可执行语句
         │
         ▼
步骤3: 遍历数据库进行分析，读取边缘信息
         │  ① 读取表结构
         │  ② 执行 DML 脚本
         │  ③ 读取执行计划
         ▼
步骤4: 保存表之间的血缘关系
         │
         ▼
步骤5: 根据血缘关系输出可视化图
```

### 3.1 步骤详解

**步骤1 — 分析器处理 DML 脚本**

前端页面接收用户提交的 DML 脚本文本，传递给后端分析器。

**步骤2 — 脚本拆分为可执行语句**

分析器对 DML 脚本进行预处理，将完整的脚本拆分为多条独立的可执行 SQL 语句。

预处理操作包括：
- 去除注释（`--` 单行注释、`/* */` 多行注释）
- 去除多余空格和空白行
- 按语句分隔符（`;`）拆分为独立语句
- **保留 CREATE 语句**：不过滤 `CREATE TABLE` / `CREATE TEMP TABLE`，因为这些语句定义的临时表/中间表会出现在后续 DML 中，影响血缘链路
- 为每条语句标注序号（`#1`, `#2`, `#3`...），并单独存储，以一个完整的 DML 脚本为一组

**步骤3 — 遍历数据库进行分析**

对每条拆分后的语句，从数据库获取两类信息：

**第一类：已知的表结构信息**

| 操作 | 说明 |
|------|------|
| 读取表结构 | 查询 `INFORMATION_SCHEMA`，获取已存在表的元信息（表名、列名、列类型、约束等） |
| 记录临时表 | 对于脚本中 `CREATE TABLE` 定义的新表/临时表，记录其结构信息，供后续语句引用 |

**第二类：DML 执行计划**

| 操作 | 说明 |
|------|------|
| 获取执行计划 | 对 DML 语句使用 `EXPLAIN` 获取执行计划（不实际修改数据） |
| 提取血缘 | 从执行计划中提取表引用关系——执行计划反映的是数据库实际解析结果，比纯静态语法分析更准确 |

> **优先级**：基于执行计划的血缘提取 > 基于静态语法解析的补充。执行计划由数据库引擎生成，能正确处理视图展开、别名解析、子查询等复杂情况。

**步骤4 — 保存血缘关系**

从执行计划和表结构中提取的表间关系，以结构化形式保存，包括：
- 源表 → 中间表 → 目标表的完整映射（中间表/临时表作为独立节点保存）
- 列级别的映射关系（如可提取）
- 关系类型（INSERT、UPDATE、DELETE、CREATE 等）

**步骤5 — 输出可视化结果**

将血缘关系数据和分段语句信息传递给前端：
- **可视化图**：以有向图形式渲染血缘关系，包含源表、中间表、目标表三种节点类型
- **分段语句面板**：展示完成拆分的每条语句（带序号标注），支持人工检查和修正

---

## 4. 模块设计

### 4.1 前端页面模块

**职责**：提供用户交互界面

| 子模块 | 功能 |
|--------|------|
| 脚本编辑器 | 提供代码编辑区域，支持 SQL 语法高亮，用户在此输入或粘贴 DML 脚本 |
| 数据库配置 | 配置 PVC 数据库连接信息（主机、端口、用户名、密码、数据库名） |
| 分析触发 | 提交按钮，将脚本和配置发送给后端分析器 |
| 可视化画布 | 展示血缘关系有向图（含源表、中间表、目标表三种节点），支持缩放、拖拽、点击节点查看详情 |
| 语句分段面板 | 展示预处理后的语句分段列表，支持人工检查、血缘关联高亮、修正后重新生成 |

### 4.2 DML 脚本分析器模块

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
      - group_id: 脚本唯一标识
      - original_script: 原始脚本原文
      - preprocessed_script: 预处理后的脚本
      - statements: [
          { seq: 1, type: "CREATE", text: "CREATE TEMP TABLE tmp ..." },
          { seq: 2, type: "INSERT", text: "INSERT INTO tmp SELECT ..." },
          { seq: 3, type: "INSERT", text: "INSERT INTO target SELECT ..." }
        ]
```

> **分段存储的意义**：保留预处理和拆分结果，方便后续血缘分析时逐条关联语句，也方便前端展示给用户进行人工检查和修正。

### 4.3 PVC 预处理模块

**职责**：对输入脚本进行清洗

| 操作 | 说明 |
|------|------|
| 去注释 | 移除 `--` 和 `/* */` 注释 |
| 去空格 | 压缩连续空格，移除首尾空白 |
| 去多余分析 | 过滤空语句，但 **保留 `CREATE TABLE` / `CREATE TEMP TABLE`**（这些语句定义的中间表会影响后续 DML 的血缘关系），仅移除与数据流转无关的 DDL（如 `ALTER`、`DROP` 纯结构变更） |

> **为什么保留 CREATE**：许多 DML 脚本会先创建临时表或中间表，再通过 INSERT 将数据写入。如果过滤掉 CREATE，后续 DML 中引用的临时表就无法识别，导致血缘链路断裂。

### 4.4 数据库连接模块

**职责**：与 PVC 数据库交互，提供两类独立的数据支撑

本模块明确分为两个子模块，各自独立工作：

**子模块 A — 表结构信息获取**

| 操作 | 说明 |
|------|------|
| 读取已有表结构 | 查询 `INFORMATION_SCHEMA` 获取已存在表的元数据（表名、列名、列类型、约束） |
| 记录脚本中的新表 | 识别脚本中 `CREATE TABLE` / `CREATE TEMP TABLE` 定义的中间表，记录其结构信息 |
| 构建表元信息索引 | 将所有表（已有 + 脚本新建）的结构信息缓存为索引，供血缘分析时查找列映射关系 |

**子模块 B — 执行计划获取**

| 操作 | 说明 |
|------|------|
| EXPLAIN DML 语句 | 对每条 DML 语句执行 `EXPLAIN`，获取数据库引擎生成的执行计划 |
| 解析执行计划 | 从执行计划输出中提取表扫描节点（Seq Scan、Index Scan）和表操作节点 |
| 提取表引用关系 | 从执行计划中还原源表 → 目标表的映射关系 |

> **执行计划优于静态解析**：执行计划由数据库引擎实际解析生成，能正确处理视图展开、别名解析、子查询展开、CTE 内联等复杂情况。静态语法解析作为补充，仅在执行计划不可用时使用。

### 4.5 血缘关系提取模块

**职责**：从执行计划和 AST 中提取表间血缘关系

提取策略（按优先级排列）：

| 优先级 | 策略 | 说明 |
|--------|------|------|
| **高** | 基于执行计划 | 解析 `EXPLAIN` 输出中的表引用节点，准确度最高 |
| **低** | 基于静态语法解析 | 通过 SQL AST 解析器识别 `INSERT INTO target SELECT ... FROM source` 中的源表和目标表，作为执行计划不可用时的补充 |

**中间表/临时表处理**：

当脚本中出现 `CREATE TABLE` 定义的临时表时，血缘链路为：

```
源表 ──INSERT──▶ 临时表/中间表 ──INSERT──▶ 目标表
```

中间表作为独立节点保留在血缘关系中，不会被折叠或省略。这样可以完整还原数据的多步流转过程。

**语句与血缘的关联**：

每条血缘关系都会关联到具体的语句序号，便于前端展示时定位到对应的 DML 语句。

### 4.6 可视化模块

**职责**：将血缘关系渲染为可交互的有向图

图元素定义：
- **节点类型**：
  - **源表节点**（Source）：数据来源的物理表，绿色
  - **中间表节点**（Intermediate）：脚本中 CREATE 定义的临时表/中间表，黄色
  - **目标表节点**（Target）：数据最终写入的表，蓝色
- **边**：表间的数据流向（有向箭头），标注操作类型（INSERT、UPDATE 等）
- **布局**：采用分层布局（DAG），源表在上游，中间表在中间层，目标表在下游

### 4.7 语句分段展示模块

**职责**：在前端展示预处理后的语句分段，支持人工检查和修正

| 功能 | 说明 |
|------|------|
| 语句列表展示 | 将预处理后的语句按序号展示，每条语句显示类型标签（CREATE/INSERT/UPDATE 等）和完整文本 |
| 语法高亮 | 对 SQL 关键字进行语法高亮，提升可读性 |
| 血缘关联高亮 | 点击某条语句时，在血缘图中高亮该语句产生的血缘边 |
| 人工修正 | 支持编辑语句的解析结果（如修正识别错误的表名），修正后重新生成血缘图 |
| 原文对比 | 展示原始脚本与预处理后脚本的对比，方便用户确认预处理是否正确 |

**前端页面布局建议**：

```
┌─────────────────────────────────────────────────────┐
│  数据库配置  │  脚本输入区                              │
├──────────────────────┬──────────────────────────────┤
│                      │                              │
│   血缘关系可视化图    │   语句分段面板                │
│   （可缩放/拖拽）     │   #1 CREATE TEMP TABLE ...   │
│                      │   #2 INSERT INTO tmp ...     │
│                      │   #3 INSERT INTO target ...  │
│                      │                              │
└──────────────────────┴──────────────────────────────┘
```

---

## 5. 数据模型

### 5.1 表信息（TableInfo）

```json
{
  "schema": "public",
  "table": "tmp_orders",
  "table_type": "intermediate",
  "source": "script_created",
  "columns": [
    { "name": "order_id", "type": "INTEGER" },
    { "name": "total_amount", "type": "DECIMAL" }
  ]
}
```

> `table_type` 取值：`source`（已有的物理源表）、`intermediate`（脚本中 CREATE 的中间表/临时表）、`target`（最终目标表）
> `source` 取值：`database`（从数据库 INFORMATION_SCHEMA 读取）、`script_created`（从脚本 CREATE 语句解析）

### 5.2 语句分段（StatementGroup）

```json
{
  "group_id": "uuid",
  "original_script": "原始 DML 脚本全文",
  "preprocessed_script": "预处理后的脚本（去注释、去空格后）",
  "statements": [
    {
      "seq": 1,
      "type": "CREATE",
      "text": "CREATE TEMP TABLE tmp_orders AS SELECT order_id, SUM(amount) AS total_amount FROM orders GROUP BY order_id",
      "tables_referenced": ["orders"],
      "tables_created": ["tmp_orders"]
    },
    {
      "seq": 2,
      "type": "INSERT",
      "text": "INSERT INTO order_summary (id, total_amount) SELECT order_id, total_amount FROM tmp_orders",
      "tables_referenced": ["tmp_orders"],
      "tables_modified": ["order_summary"]
    }
  ]
}
```

### 5.3 血缘关系（Lineage）

```json
{
  "lineage_id": "uuid",
  "source_table": {
    "schema": "public",
    "table": "orders"
  },
  "target_table": {
    "schema": "public",
    "table": "tmp_orders"
  },
  "operation_type": "CREATE",
  "extraction_method": "execution_plan",
  "statement_seq": 1,
  "column_mappings": [
    {
      "source_column": "order_id",
      "target_column": "order_id"
    },
    {
      "source_column": "amount",
      "target_column": "total_amount",
      "transformation": "SUM"
    }
  ],
  "dml_statement": "CREATE TEMP TABLE tmp_orders AS SELECT order_id, SUM(amount) AS total_amount FROM orders GROUP BY order_id"
}
```

> `extraction_method` 取值：`execution_plan`（从执行计划提取，优先级高）、`static_analysis`（静态语法解析补充）
> `statement_seq`：关联到 StatementGroup 中的语句序号，方便前端定位

### 5.4 分析结果（AnalysisResult）

```json
{
  "analysis_id": "uuid",
  "created_at": "2026-04-27T12:00:00Z",
  "input_script": "原始 DML 脚本",
  "database_info": {
    "tables_from_db": [
      {
        "schema": "public",
        "table": "orders",
        "columns": ["order_id", "amount", "customer_id"]
      }
    ],
    "tables_from_script": [
      {
        "schema": "public",
        "table": "tmp_orders",
        "columns": ["order_id", "total_amount"],
        "table_type": "intermediate"
      }
    ]
  },
  "statement_group": {
    "group_id": "uuid",
    "original_script": "原始 DML 脚本",
    "preprocessed_script": "预处理后脚本",
    "statements": [
      { "seq": 1, "type": "CREATE", "text": "CREATE TEMP TABLE tmp_orders ..." },
      { "seq": 2, "type": "INSERT", "text": "INSERT INTO order_summary ..." }
    ]
  },
  "lineages": [
    {
      "source": "orders",
      "target": "tmp_orders",
      "operation": "CREATE",
      "method": "execution_plan",
      "statement_seq": 1
    },
    {
      "source": "tmp_orders",
      "target": "order_summary",
      "operation": "INSERT",
      "method": "execution_plan",
      "statement_seq": 2
    }
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

---

## 6. 技术选型建议

| 组件 | 推荐技术 | 备选 |
|------|----------|------|
| **前端框架** | React + TypeScript | Vue 3 |
| **可视化库** | React Flow（基于 D3） | AntV G6, Cytoscape.js |
| **代码编辑器** | Monaco Editor | CodeMirror |
| **后端框架** | Python FastAPI | Node.js Express |
| **SQL 解析** | sqlglot（Python） | sqlparse |
| **数据库驱动** | SQLAlchemy | psycopg2（PostgreSQL 专用） |
| **图布局算法** | Dagre（分层 DAG 布局） | ELK |

---

## 7. API 设计

### 7.1 提交分析任务

```
POST /api/analyze
```

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

**响应体：**

```json
{
  "analysis_id": "uuid",
  "status": "completed",
  "statement_group": {
    "group_id": "uuid",
    "statements": [
      { "seq": 1, "type": "CREATE", "text": "CREATE TEMP TABLE tmp AS SELECT * FROM source_table" },
      { "seq": 2, "type": "INSERT", "text": "INSERT INTO target_table SELECT * FROM tmp" }
    ]
  },
  "tables": {
    "from_database": ["source_table", "target_table"],
    "from_script": ["tmp"]
  },
  "lineages": [
    { "source": "source_table", "target": "tmp", "operation": "CREATE", "method": "execution_plan", "statement_seq": 1 },
    { "source": "tmp", "target": "target_table", "operation": "INSERT", "method": "execution_plan", "statement_seq": 2 }
  ],
  "visualization": {
    "nodes": [
      { "id": "source_table", "label": "source_table", "type": "source" },
      { "id": "tmp", "label": "tmp", "type": "intermediate" },
      { "id": "target_table", "label": "target_table", "type": "target" }
    ],
    "edges": [
      { "source": "source_table", "target": "tmp", "label": "CREATE", "statement_seq": 1 },
      { "source": "tmp", "target": "target_table", "label": "INSERT", "statement_seq": 2 }
    ]
  }
}
```

### 7.2 获取历史分析记录

```
GET /api/analyses?page=1&page_size=20
```

### 7.3 获取单次分析详情

```
GET /api/analyses/{analysis_id}
```

### 7.4 修正语句解析结果

用户在前端语句分段面板中修正解析结果后，提交修正并重新生成血缘关系。

```
PUT /api/analyses/{analysis_id}/statements/{seq}
```

**请求体：**

```json
{
  "corrected_text": "INSERT INTO target_table SELECT * FROM source_table_v2",
  "tables_referenced": ["source_table_v2"],
  "tables_modified": ["target_table"]
}
```

**响应体：** 返回更新后的完整分析结果（同 7.1 响应格式）。

### 7.5 获取预处理结果

获取脚本预处理和分段后的结果，供前端展示。

```
GET /api/analyses/{analysis_id}/statements
```

**响应体：**

```json
{
  "group_id": "uuid",
  "original_script": "原始脚本全文",
  "preprocessed_script": "预处理后全文",
  "statements": [
    { "seq": 1, "type": "CREATE", "text": "...", "tables_referenced": [...], "tables_created": [...] },
    { "seq": 2, "type": "INSERT", "text": "...", "tables_referenced": [...], "tables_modified": [...] }
  ]
}
```

---

## 8. 验证方案

### 8.1 单元测试

| 测试对象 | 测试内容 |
|----------|----------|
| 预处理模块 | 注释移除、空格压缩、语句过滤 |
| 语句拆分器 | 多语句脚本正确拆分、边界情况处理 |
| 血缘提取器 | 各类 DML 语句的血缘关系正确提取 |

### 8.2 集成测试

- 连接真实数据库，执行 `EXPLAIN` 验证执行计划解析
- 端到端测试：提交脚本 → 获取分析结果 → 渲染可视化图

### 8.3 测试用例示例

```sql
-- 测试用例1: 简单 INSERT-SELECT
INSERT INTO summary_table (id, name, total)
SELECT u.id, u.name, SUM(o.amount)
FROM users u JOIN orders o ON u.id = o.user_id
GROUP BY u.id, u.name;

-- 期望血缘:
--   users → summary_table (INSERT)
--   orders → summary_table (INSERT)

-- 测试用例2: 多语句脚本
INSERT INTO table_a SELECT * FROM table_b;
UPDATE table_c SET col1 = (SELECT col1 FROM table_d);

-- 期望血缘:
--   table_b → table_a (INSERT)
--   table_d → table_c (UPDATE)

-- 测试用例3: 包含注释和空白
-- 这是一个注释
INSERT /* 内联注释 */ INTO target
SELECT * FROM source;

-- 期望: 预处理后正确解析

-- 测试用例4: 包含临时表/中间表
CREATE TEMP TABLE tmp_order_detail AS
SELECT o.order_id, o.amount, c.name
FROM orders o JOIN customers c ON o.customer_id = c.id;

INSERT INTO order_report (order_id, amount, customer_name)
SELECT order_id, amount, name FROM tmp_order_detail;

-- 期望血缘:
--   orders → tmp_order_detail (CREATE)
--   customers → tmp_order_detail (CREATE)
--   tmp_order_detail → order_report (INSERT)
-- 期望分段存储:
--   #1 CREATE | "CREATE TEMP TABLE tmp_order_detail AS ..."
--   #2 INSERT | "INSERT INTO order_report ..."

-- 测试用例5: 执行计划 vs 静态解析
-- 当脚本包含视图或复杂子查询时，执行计划应能正确展开
INSERT INTO target SELECT * FROM my_view;
-- 假设 my_view = SELECT * FROM table_a JOIN table_b ON ...
-- 静态解析只能识别: my_view → target
-- 执行计划应识别: table_a → target, table_b → target（视图展开）
```

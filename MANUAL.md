# DataLineage Visualizer 使用手册

## 目录

1. [简介](#1-简介)
2. [环境要求](#2-环境要求)
3. [安装与启动](#3-安装与启动)
4. [快速开始](#4-快速开始)
5. [功能详解](#5-功能详解)
6. [参数映射配置](#6-参数映射配置)
7. [数据库准备](#7-数据库准备)
8. [测试脚本示例](#8-测试脚本示例)
9. [常见问题](#9-常见问题)

---

## 1. 简介

DataLineage Visualizer 是一个 **DML 脚本血缘关系分析与可视化工具**，采用 **增量拼图** 模式：

- 每次分析一个 DML 脚本，自动提取其血缘关系
- 多次分析结果累积到全局血缘图谱中，像拼图一样逐步构建完整的数据库血缘关系
- 支持脚本管理（查看、重命名、删除），删除脚本后全局图谱自动更新

### 核心概念

| 概念 | 说明 |
|------|------|
| **源表 (Source)** | 数据来源的物理表，图中显示为绿色节点 |
| **中间表 (Intermediate)** | 脚本中 CREATE 定义的临时表，图中显示为黄色节点 |
| **目标表 (Target)** | 数据最终写入的表，图中显示为蓝色节点 |
| **表级血缘** | 源表到目标表的数据流向，以有向箭头表示 |
| **列级血缘** | 目标列 ← 源列的映射，点击边查看（含变换表达式） |
| **全局图谱** | 所有分析脚本的血缘关系累积后的完整图谱 |

### 分析模式

| 模式 | 说明 |
|------|------|
| **离线模式（默认，推荐）** | 不填数据库配置，纯 SQL 语法（AST）解析提取血缘，无需数据库 |
| **在线模式（可选）** | 填写数据库配置，额外校验表是否存在、补充列信息 |

> **重要**：血缘提取统一基于 `sqlglot` AST 静态解析，确定性强、可离线。数据库仅用于校验与补充，不影响血缘结果。

### 页面布局

```
┌────────────────────────────────────────────────────────────────────┐
│  DataLineage Visualizer   [搜索框] [参数映射] [新建分析]            │
├──────────┬───────────────────────────────────────┬─────────────────┤
│          │                                       │                 │
│  脚本列表 │     全局血缘图谱（React Flow）         │  语句分段面板    │
│  (左栏)   │     + 点边看列级 + 搜索聚焦           │  (右栏)         │
│          │                                       │                 │
│  ▸ ETL_  │  [orders]──▶[tmp]──▶[report]         │  #1 CREATE ...  │
│  ▸ 每日   │  [customers]──▶[report]              │  #2 INSERT ...  │
│          │                                       │                 │
├──────────┴───────────────────────────────────────┴─────────────────┤
│  状态栏: 12 张表 | 18 条血缘 | 5 个脚本                            │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. 环境要求

### 开发模式

| 组件 | 版本要求 |
|------|----------|
| Python | 3.10+（推荐 3.13） |
| Node.js | 18+ |
| PostgreSQL | 12+（可选，仅在线校验用） |

### 绿色包（便携版）

**无任何环境要求**——双击 `run.bat` 即用（自带 Python 运行时和全部依赖）。详见 [便携版部署](#35-绿色包便携版零安装)。

---

## 3. 安装与启动

### 3.1 开发模式（后端 + 前端分离）

**安装后端依赖：**

```bash
cd backend
pip install -r requirements.txt
```

**安装前端依赖：**

```bash
cd frontend
npm install
```

### 3.2 使用启停脚本（推荐）

```bash
./ctl.sh start    # 启动（后端 :8000 + 前端 dev :5173）
./ctl.sh stop     # 停止
./ctl.sh restart  # 重启
./ctl.sh status   # 查看状态
```

### 3.3 一体化部署（生产，推荐）

构建前端后，后端单进程同时服务 API + 页面：

```bash
cd frontend && npm run build       # 产出 frontend/dist/
cd ../backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

浏览器访问 **http://localhost:8000**（单端口，无需前端 dev server）。

### 3.4 手动启动（开发调试）

**后端：**

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**前端**（新终端）：

```bash
cd frontend
npm run dev    # :5173
```

### 3.5 绿色包（便携版，零安装）

使用 `pack_portable.bat`（开发机执行）生成 `dist-portable/`：

```bash
pack_portable.bat    # 产出 dist-portable/（约 294MB）
```

将 `dist-portable/` 整个文件夹拷贝到目标机器，双击 `run.bat`，浏览器开 http://localhost:8000。

**目标机不需要安装任何东西**（无需 Python、Node、Docker）。

详见 `README_PORTABLE.txt`。

### 3.6 访问应用

- 一体化/绿色包：**http://localhost:8000**
- 开发模式：**http://localhost:5173**（前端 dev server）

---

## 4. 快速开始

### 第一步：打开新建分析弹窗

点击 Header 右上角的 **「新建分析」** 按钮。

### 第二步：（可选）填写数据库连接

弹窗里「高级选项：数据库连接（可选）」**默认折叠**。

- **离线模式**：不展开，直接分析（推荐先试）
- **在线模式**：展开填写 host/port/库名/用户名/密码

> 不填数据库也能完整提取血缘。数据库仅用于校验表是否存在、补充列信息。

### 第三步：输入 DML 脚本

在代码编辑器中粘贴 DML 脚本。

### 第四步：点击「分析血缘」

分析完成后，提示「分析完成（离线模式）」或「分析完成（已连接数据库校验）」。

### 第五步：查看结果

| 区域 | 内容 |
|------|------|
| 左栏 脚本列表 | 新增一条脚本记录 |
| 中栏 全局图谱 | 新增的节点和边出现 |
| 右栏 语句分段 | 选中脚本后显示其语句 |
| 状态栏 | 表数/边数/脚本数实时更新 |

### 第六步：交互操作

| 操作 | 效果 |
|------|------|
| 点击左侧脚本 | 中栏切换为该脚本血缘图 |
| 点击「全部」 | 中栏恢复全局累积图谱 |
| 点击节点 | 展开/收起完整表名（长名截断后点开看全） |
| 点击边 | 弹出列级血缘 Drawer（目标列←源列+变换） |
| 点击语句 | 该语句的所有边高亮蓝色 |
| 搜索框输入 | 模糊匹配表名/字段名，选中后聚焦+高亮 |
| 全局图选中脚本 | 该脚本的所有边高亮 |

---

## 5. 功能详解

### 5.1 搜索框（Header）

Header 左侧的搜索框支持**模糊匹配表名和字段名**：

1. 输入关键词（如 "order"）
2. 下拉显示所有匹配的表（● 绿点）和字段（◆/◇ 钻石）
3. 选中表节点 → 图自动聚焦该节点 + 白边框发光
4. 选中字段 → 图聚焦该字段所在边 + 单边高亮 + 弹列级 Drawer

搜索范围根据当前视图自动切换：全局视图搜全局图，脚本视图搜当前脚本。

### 5.2 参数映射配置（Header）

点击 Header「参数映射」按钮，配置 `${param}` 占位符的实际值。详见 [第 6 节](#6-参数映射配置)。

### 5.3 脚本列表（左栏）

| 操作 | 说明 |
|------|------|
| 选中脚本 | 中栏显示该脚本的血缘图 |
| 查看全部 | 恢复全局累积图谱 |
| 重命名 | 点击编辑图标内联修改 |
| 删除 | 确认后删除，全局图谱自动更新 |

### 5.4 血缘图谱（中栏）

**节点颜色规则：**

| 颜色 | 含义 | 判定 |
|------|------|------|
| 绿色 `#52c41a` | 源表 | 只在边的 source 端出现 |
| 黄色 `#faad14` | 中间表/临时表 | 既作为 source 又作为 target |
| 蓝色 `#1890ff` | 目标表 | 只在边的 target 端出现 |

**节点宽度**：自适应（短名收缩，长名截断 + 点击展开看全）。

**边的流动动画**：默认所有边流动；选中单边时只该边流动；全局图选中脚本时该脚本的边高亮。

**布局切换**：右上角按钮切换垂直（TB）/水平（LR）。

**交互**：滚轮缩放、拖拽节点、拖拽空白平移、右下角迷你地图。

### 5.5 列级血缘（点边查看）

点击任意边，右侧弹出 Drawer 展示该边的列级映射：

```
public.orders → public.order_report  操作：INSERT  语句 #1

[order_id]      ← [public.orders.id]
[amount]        ← [public.orders.amount]   变换：amount * 1.1
[customer_name] ← [public.customers.name]
```

支持：显式列映射、JOIN+别名、聚合（SUM/COUNT）、表达式（price*qty）。`SELECT *` 无法解析列级，显示"无列级映射"（表级血缘仍正常）。

### 5.6 语句分段面板（右栏）

选中脚本后展示语句分段：序号（#1, #2）、类型标签（CREATE/INSERT/UPDATE/DELETE）、SQL 文本、涉及表。点击语句 → 该 seq 的所有边高亮。

### 5.7 支持的 SQL 类型

| 类型 | 示例 | 处理 |
|------|------|------|
| `CREATE TABLE ... AS SELECT` | `CREATE TEMP TABLE tmp AS SELECT * FROM src;` | 保留（中间表） |
| `INSERT INTO ... SELECT` | `INSERT INTO tgt SELECT * FROM src;` | 保留 |
| `UPDATE ... SET` | `UPDATE tgt SET col = val WHERE ...;` | 保留 |
| `DELETE FROM` | `DELETE FROM tgt WHERE ...;` | 保留 |
| `MERGE INTO` | `MERGE INTO tgt USING src ON ...;` | 保留 |
| `ALTER TABLE` | `ALTER TABLE t ADD COLUMN c INT;` | 过滤 |
| `DROP TABLE` | `DROP TABLE t;` | 过滤 |

**预处理**：自动移除注释、压缩空格、按 `;` 拆分（考虑 dollar-quote）。

### 5.8 血缘提取策略

**统一基于 `sqlglot` AST 静态解析**，不再使用 EXPLAIN 执行计划：

- 确定性强、无外部依赖、可离线运行
- 正确处理 CTE/子查询/各类 DML/跨 schema 同名表
- 列级血缘独立模块（column_lineage.py），与表级解耦

### 5.9 数据持久化

```
backend/data/
├── tables.json          # 全局表注册表（schema.table 为 key）
├── edges.jsonl          # 全局血缘边（JSON Lines，带列级映射）
├── param_mapping.json   # 参数映射表
├── store.lock           # 文件锁
└── scripts/
    └── {id}.json        # 各脚本分析结果
```

所有写操作在文件锁保护下原子完成。删除脚本后全表扫清理孤立表。

---

## 6. 参数映射配置

ETL 脚本常用 `${icl_schema}`、`${batch_date}` 等模板占位符。配置映射后，分析时自动替换。

### 6.1 配置方法

1. 点击 Header「参数映射」按钮
2. 在弹窗中添加映射行：

   | 参数名 | 实际值 |
   |--------|--------|
   | `icl_schema` | `ods` |
   | `env` | `prod` |
   | `src_schema` | `staging` |

3. 点击「保存」

### 6.2 替换规则

| 占位符 | 有映射 | 无映射 |
|--------|--------|--------|
| `${icl_schema}.orders` | `ods.orders` | `icl_schema.orders`（保留参数名） |
| `${schema}_${env}.report` | `dw_prod.report` | `schema_env.report` |
| `WHERE dt = ${batch_date}` | `WHERE dt = <映射值>` | `WHERE dt = batch_date`（当列名，对血缘无影响） |

> **注意**：参数映射在**分析新脚本时**生效。已有脚本的节点不会自动更新，需重新分析才能应用新映射。

### 6.3 API

```
GET  /api/param-mapping    # 获取映射表
PUT  /api/param-mapping    # 更新映射表（全量替换）
```

---

## 7. 数据库准备

数据库**可选**。仅在需要在线校验（表是否存在、列信息补充）时准备。

### 7.1 Docker 部署 PostgreSQL

```bash
docker run -d \
  --name lineage-pg \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=<your-password> \
  -e POSTGRES_DB=postgres \
  -p 5432:5432 \
  postgres:16
```

### 7.2 创建测试表

```bash
docker exec -i lineage-pg psql -U postgres < backend/tests/init_test_tables.sql
```

> **离线模式下不需要这步**——直接粘贴 SQL 分析即可。

---

## 8. 测试脚本示例

以下示例可直接粘贴到「新建分析」弹窗。**离线模式下无需准备数据库**。

### 示例 1：简单 INSERT-SELECT（双源表 JOIN）

```sql
INSERT INTO order_report (order_id, amount, customer_name)
SELECT o.id, o.amount, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id;
```

**期望**：3 节点（orders/customers/order_report）+ 2 边。点边看列级：order_id←orders.id, customer_name←customers.name。

### 示例 2：临时表 + 列级表达式

```sql
CREATE TEMP TABLE tmp_order_detail AS
SELECT o.id AS order_id, o.amount, c.name AS customer_name
FROM orders o JOIN customers c ON o.customer_id = c.id;

INSERT INTO order_report (order_id, amount, customer_name)
SELECT order_id, amount * 1.1, customer_name FROM tmp_order_detail;
```

**期望**：`tmp_order_detail` 为黄色中间表。第二条边列级显示 `amount` 带变换 `amount * 1.1`。

### 示例 3：带参数占位符

先配置参数映射 `icl_schema = ods`，再分析：

```sql
INSERT INTO ${icl_schema}.summary (cust_id, total)
SELECT customer_id, SUM(amount) FROM ${icl_schema}.orders
WHERE dt = ${batch_date} GROUP BY customer_id;
```

**期望**：节点显示 `ods.summary` 和 `ods.orders`（参数已替换）。

### 示例 4：多层临时表嵌套

```sql
CREATE TEMP TABLE tmp_a AS SELECT * FROM src;
CREATE TEMP TABLE tmp_b AS SELECT * FROM tmp_a WHERE x > 0;
INSERT INTO report SELECT * FROM tmp_b;
```

**期望**：形成 src→tmp_a→tmp_b→report 链路，tmp_a/tmp_b 为黄色中间表。

### 示例 5：跨 schema 同名表

```sql
INSERT INTO reporting.fact
SELECT a.x FROM public.orders a JOIN reporting.orders b ON a.id = b.id;
```

**期望**：`public.orders` 和 `reporting.orders` 是两个独立节点（不冲突）。

### 端到端验证流程

1. 依次提交示例，验证全局图谱逐步累积
2. 点击边查看列级血缘 Drawer
3. 用搜索框搜索表名/字段名，选中后聚焦
4. 删除某个脚本，验证全表扫清理孤立表
5. 刷新页面，验证数据从 JSON 恢复

---

## 9. 常见问题

### Q: 不连数据库能用吗？

**能。** 离线模式（默认）完全不需要数据库。血缘提取基于 SQL 语法解析。只有需要校验表是否存在时才连数据库。

### Q: 分析时报数据库连接失败？

数据库连接失败会**自动降级为离线模式**，仍返回血缘结果。检查：PostgreSQL 是否运行、端口/账号是否正确、防火墙。

### Q: 列级血缘看不到？

1. 确认不是 `SELECT *`（无法解析列级，降级为表级）
2. 点击边，右侧 Drawer 展示列级映射
3. `SELECT *` 显示"无列级映射"是正常的（表级血缘仍正常）

### Q: 参数占位符 `${param}` 报错？

sqlglot 无法直接解析 `${param}`。在 Header「参数映射」配置实际值，分析时自动替换。

### Q: 删除脚本后图谱还有残留节点？

已修复。删除脚本会全表扫清理孤立表。如仍有残留，刷新页面。

### Q: 搜索框怎么用？

Header 左侧输入关键词，下拉显示匹配的表和字段。选中后图自动聚焦+高亮。

### Q: 节点名太长看不全？

点击节点，展开显示完整表名（不受截断限制）。再点收起。

### Q: 前端页面空白？

1. 确认后端服务已启动（http://localhost:8000/api/health 返回 ok）
2. F12 查看控制台错误
3. 确认前端已 build（一体化模式下需要 `npm run build`）

### Q: 如何查看 API 文档？

http://localhost:8000/docs（Swagger UI）。

### Q: 绿色包怎么用？

见 `README_PORTABLE.txt`。双击 `run.bat`，浏览器开 :8000，零安装。

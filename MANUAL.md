# DataLineage Visualizer 使用手册

## 目录

1. [简介](#1-简介)
2. [环境要求](#2-环境要求)
3. [安装与启动](#3-安装与启动)
4. [快速开始](#4-快速开始)
5. [功能详解](#5-功能详解)
6. [数据库准备](#6-数据库准备)
7. [测试脚本示例](#7-测试脚本示例)
8. [常见问题](#8-常见问题)

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
| **血缘关系** | 源表到目标表的数据流向，以有向箭头表示 |
| **全局图谱** | 所有分析脚本的血缘关系累积后的完整图谱 |
| **脚本管理** | 对已分析脚本的查看、重命名、删除操作 |

### 页面布局

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
│    汇总   │                                   │  #1 CREATE ...    │
│          │                                   │  #2 INSERT ...    │
├──────────┴───────────────────────────────────┴───────────────────┤
│  状态栏: 12 张表 | 18 条血缘 | 5 个脚本                           │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 环境要求

| 组件 | 版本要求 |
|------|----------|
| Python | 3.11+ |
| Node.js | 18+ |
| PostgreSQL | 12+（需要能执行 EXPLAIN） |

---

## 3. 安装与启动

### 3.1 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
```

### 3.2 安装前端依赖

```bash
cd frontend
npm install
```

### 3.3 使用启停脚本（推荐）

项目提供了 `ctl.sh` 脚本，支持一键启停：

```bash
# 启动（后端 + 前端）
./ctl.sh start

# 停止
./ctl.sh stop

# 重启
./ctl.sh restart

# 查看状态
./ctl.sh status
```

### 3.4 手动启动

**启动后端服务：**

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**启动前端服务**（新终端窗口）：

```bash
cd frontend
npm run dev
```

### 3.5 访问应用

在浏览器中打开 **http://localhost:5173** 即可使用。

---

## 4. 快速开始

### 第一步：打开新建分析弹窗

点击页面右上角的 **「新建分析」** 按钮，弹出分析窗口。

### 第二步：填写数据库连接信息

在弹窗顶部的「数据库配置」区域，填入 PostgreSQL 连接信息：

```
主机: localhost      （Docker 映射到本机时填 localhost）
端口: 5432           （或你映射的端口）
数据库: postgres      （你的数据库名）
用户名: postgres
密码: your_password
```

### 第三步：输入 DML 脚本

在弹窗的代码编辑器中粘贴或输入 DML 脚本。

### 第四步：点击「分析血缘」

点击编辑器下方的 **「分析血缘」** 按钮，等待分析完成。分析结果会自动保存。

### 第五步：查看结果

- **左栏 — 脚本列表**：新增一条脚本记录，显示名称、语句数、表数
- **中栏 — 全局血缘图谱**：新增的节点和边出现在全局图中
- **右栏 — 语句分段面板**：选中脚本后展示其语句分段
- **底部状态栏**：实时显示表数量、血缘数量、脚本数量

### 第六步：交互操作

| 操作 | 效果 |
|------|------|
| 点击左侧脚本 | 中栏切换为该脚本的血缘图，右栏显示语句分段 |
| 点击「全部」按钮 | 中栏恢复为全局累积图谱 |
| 点击语句分段中的语句 | 对应的血缘边高亮为蓝色粗线 |
| 点击图谱右上角按钮 | 切换垂直/水平布局 |

---

## 5. 功能详解

### 5.1 脚本列表（左栏）

脚本列表展示所有已分析的脚本，支持以下操作：

| 操作 | 说明 |
|------|------|
| 选中脚本 | 点击脚本项，中栏显示该脚本的血缘图，右栏显示语句分段 |
| 查看全部 | 点击列表顶部的「全部」按钮，恢复全局累积图谱 |
| 重命名 | 点击脚本名称旁的编辑图标，内联修改名称 |
| 删除 | 点击删除图标，确认后删除脚本，全局图谱自动更新 |

每个脚本项显示：
- 脚本名称
- 语句数量（蓝色标签）
- 涉及的表数量（绿色标签）
- 分析时间

### 5.2 全局血缘图谱（中栏）

全局图谱是所有分析脚本血缘关系的累积展示：

**节点颜色规则：**

| 元素 | 含义 | 颜色 |
|------|------|------|
| 绿色节点 | 源表（数据来源） | `#52c41a` |
| 黄色节点 | 中间表/临时表（CREATE 创建的表） | `#faad14` |
| 蓝色节点 | 目标表（数据写入的表） | `#1890ff` |
| 有向箭头 | 数据流向，标注操作类型 | 灰色 |

**视图切换：**

- **全局视图**：展示所有脚本的累积血缘图（默认）
- **脚本视图**：选中某个脚本后，只显示该脚本的血缘图

**布局切换：**

点击图谱右上角的布局按钮，在垂直布局（从上到下）和水平布局（从左到右）之间切换。

**交互操作：**

- 鼠标滚轮：缩放
- 拖拽节点：调整位置
- 拖拽空白处：平移画布
- 右下角迷你地图：全局概览

### 5.3 语句分段面板（右栏）

选中脚本后，右栏展示该脚本的语句分段信息：

- **序号标签**：`#1`、`#2`... 表示语句执行顺序
- **类型标签**：`CREATE`（金色）、`INSERT`（绿色）、`UPDATE`（蓝色）、`DELETE`（红色）
- **语句文本**：完整的 SQL 语句
- **引用表/创建表**：该语句涉及的表

**联动功能：** 点击某条语句时，血缘图中对应的边会高亮为蓝色粗线。

### 5.4 新建分析弹窗

点击右上角「新建分析」按钮打开弹窗，包含：

1. **数据库配置表单**：主机、端口、数据库、用户名、密码
2. **脚本编辑器**：支持 SQL 语法高亮的代码编辑区域
3. **分析按钮**：点击后执行分析，完成后弹窗自动关闭

> **安全说明**：系统只对 DML 语句执行 `EXPLAIN`，不会实际执行 INSERT/UPDATE/DELETE，不会修改你的数据。

### 5.5 支持的 SQL 类型

| 类型 | 示例 | 是否保留 |
|------|------|----------|
| `CREATE TABLE ... AS SELECT` | `CREATE TEMP TABLE tmp AS SELECT * FROM src;` | 保留（中间表） |
| `INSERT INTO ... SELECT` | `INSERT INTO tgt SELECT * FROM src;` | 保留 |
| `UPDATE ... SET` | `UPDATE tgt SET col = (SELECT ...);` | 保留 |
| `DELETE FROM` | `DELETE FROM tgt WHERE ...;` | 保留 |
| `MERGE INTO` | `MERGE INTO tgt USING src ON ...;` | 保留 |
| `ALTER TABLE` | `ALTER TABLE t ADD COLUMN c INT;` | 过滤（不影响血缘） |
| `DROP TABLE` | `DROP TABLE t;` | 过滤（不影响血缘） |

**预处理功能：**
- 自动移除 `--` 单行注释和 `/* */` 多行注释
- 自动压缩多余空格和空白行
- 按分号 `;` 拆分为独立语句

### 5.6 血缘提取策略

| 策略 | 优先级 | 说明 |
|------|--------|------|
| 执行计划 | 高 | 通过 `EXPLAIN` 获取数据库引擎的解析结果，能正确处理视图展开、别名等 |
| 静态解析 | 低 | 通过 SQL 语法树解析，作为数据库不可用时的补充 |

### 5.7 数据持久化

分析结果自动保存在后端的 JSON 文件中：

```
backend/data/
├── tables.json              # 全局表注册表
├── edges.json               # 全局血缘边
└── scripts/
    ├── {script_id}.json     # 各脚本分析结果
    └── ...
```

- 刷新页面后数据从 JSON 文件恢复
- 重启后端服务后数据不丢失
- 删除脚本后全局图谱自动更新（移除边，清理孤立表）

---

## 6. 数据库准备

### 6.1 Docker 部署 PostgreSQL（如尚未部署）

```bash
docker run -d \
  --name lineage-pg \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=<your-password> \
  -e POSTGRES_DB=postgres \
  -p 5432:5432 \
  postgres:16
```

### 6.2 创建测试表和数据

项目提供了建表脚本 `backend/tests/init_test_tables.sql`，包含：

**源表（3 张）：**

| 表名 | 说明 |
|------|------|
| `customers` | 客户表（id, name, region） |
| `orders` | 订单表（id, customer_id, product_id, amount, order_date, status） |
| `products` | 产品表（id, name, category, price） |

**目标表（3 张）：**

| 表名 | 说明 |
|------|------|
| `order_report` | 订单报表 |
| `customer_summary` | 客户汇总 |
| `daily_metrics` | 每日指标 |

使用 psql 执行：

```bash
docker exec -i lineage-pg psql -U postgres < backend/tests/init_test_tables.sql
```

---

## 7. 测试脚本示例

以下 6 个测试用例可以依次提交，体验增量拼图效果。每个用例可以直接粘贴到「新建分析」弹窗中。

> 使用前请确保：1) Docker PostgreSQL 已启动；2) 已执行 `init_test_tables.sql` 创建测试表。

### 示例 1：简单 INSERT-SELECT（双源表 JOIN）

```sql
INSERT INTO order_report (order_id, amount, customer_name)
SELECT o.id, o.amount, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id;
```

**期望结果：** 全局图谱出现 3 个节点（orders, customers, order_report）+ 2 条边。

### 示例 2：包含临时表的完整流程

```sql
CREATE TEMP TABLE tmp_order_detail AS
SELECT o.id AS order_id, o.amount, c.name AS customer_name, c.region
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.amount > 0;

INSERT INTO order_report (order_id, amount, customer_name, region)
SELECT order_id, amount, customer_name, region
FROM tmp_order_detail;
```

**期望结果：** 全局图谱出现 4 个节点，`tmp_order_detail` 为黄色中间表。

### 示例 3：多语句混合操作（INSERT + UPDATE）

```sql
INSERT INTO customer_summary (customer_id, total_amount, order_count)
SELECT customer_id, SUM(amount) AS total_amount, COUNT(*) AS order_count
FROM orders
GROUP BY customer_id;

UPDATE order_report SET amount = amount * 1.1
WHERE region = '华东';
```

**期望结果：** 全局图谱新增 `customer_summary` 节点（蓝色目标表）。

### 示例 4：带注释的复杂 ETL 脚本

```sql
-- ==========================================
-- 每日订单汇总 ETL
-- ==========================================

/* 步骤1: 创建每日临时表 */
CREATE TEMP TABLE tmp_daily AS
SELECT
    customer_id,
    SUM(amount) AS daily_total,
    COUNT(*)    AS daily_count
FROM orders
WHERE order_date = CURRENT_DATE
GROUP BY customer_id;

/* 步骤2: 合并到客户汇总 */
INSERT INTO customer_summary (customer_id, total_amount, order_count)
SELECT customer_id, daily_total, daily_count
FROM tmp_daily;

-- 步骤3: 生成区域指标
INSERT INTO daily_metrics (metric_date, region, total_amount, order_count)
SELECT CURRENT_DATE, c.region, SUM(o.amount), COUNT(*)
FROM orders o
JOIN customers c ON o.customer_id = c.id
GROUP BY c.region;
```

**期望结果：** 注释被自动移除，正确拆分为 3 条语句。全局图谱新增 `daily_metrics` 和 `tmp_daily` 节点。

### 示例 5：多层临时表嵌套

```sql
CREATE TEMP TABLE tmp_product_orders AS
SELECT p.name AS product_name, p.category, o.amount, o.order_date
FROM products p
JOIN orders o ON p.id = o.product_id;

CREATE TEMP TABLE tmp_high_value AS
SELECT product_name, category, amount
FROM tmp_product_orders
WHERE amount > 1000;

INSERT INTO order_report (order_id, amount, customer_name, region)
SELECT 0, amount, product_name, category
FROM tmp_high_value;
```

**期望结果：** 全局图谱出现 `tmp_product_orders` 和 `tmp_high_value` 两个黄色中间表，形成多层链路。

### 示例 6：包含被过滤的 DDL

```sql
ALTER TABLE order_report ADD COLUMN IF NOT EXISTS notes TEXT;

INSERT INTO order_report (order_id, amount, customer_name, region)
SELECT o.id, o.amount, c.name, c.region
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.status = 'completed';

DROP TABLE IF EXISTS tmp_not_exist;
```

**期望结果：** 只保留 INSERT 语句，ALTER 和 DROP 被过滤。语句分段面板只显示 1 条 INSERT 语句。

### 端到端验证流程

1. 依次提交用例 1-6（每次点「新建分析」→ 粘贴 → 「分析血缘」）
2. 左侧脚本列表应有 6 个脚本
3. 点击「全部」查看全局累积图谱：
   - 应包含约 8 个表节点（含多个临时表）
   - 边数量应超过 10 条
4. 逐个点击脚本，验证每个脚本的血缘图和语句分段
5. 删除某个脚本，验证全局图谱自动更新（边减少，孤立表被清理）
6. 刷新页面，验证数据从 JSON 文件恢复

---

## 8. 常见问题

### Q: 分析时报数据库连接失败？

1. 确认 PostgreSQL 正在运行：`docker ps`
2. 确认端口映射正确：`docker ps` 查看 `PORTS` 列
3. 确认用户名和密码正确
4. 如果 PostgreSQL 在远程服务器，确认防火墙允许 5432 端口

### Q: 连接成功但血缘为空？

1. 确认数据库中存在脚本引用的表
2. 确认脚本中的表名与数据库中的表名一致（大小写敏感）
3. 检查语句分段面板中语句是否被正确识别

### Q: 临时表没有出现在血缘图中？

1. 确认使用的是 `CREATE TABLE` 或 `CREATE TEMP TABLE` 语法
2. `CREATE TABLE ... AS SELECT` 会被识别
3. 检查语句分段面板中 CREATE 语句是否被正确保留

### Q: 只看到静态解析，没有执行计划？

执行计划获取失败时会自动回退到静态解析。常见原因：
1. 脚本中引用的临时表在数据库中不存在（EXPLAIN 会失败）
2. SQL 语法与 PostgreSQL 不兼容
3. 数据库连接中断

### Q: 删除脚本后全局图谱没有更新？

刷新页面即可。全局图谱的数据在后端已更新，前端需要重新获取。

### Q: 数据库配置在哪里填写？

点击页面右上角的 **「新建分析」** 按钮，弹窗顶部有数据库配置表单。每次分析时填写连接信息。

### Q: 前端页面空白或报错？

1. 确认后端服务已启动（访问 http://localhost:8000/api/health 应返回 `{"status":"ok"}`）
2. 确认前端服务已启动
3. 打开浏览器开发者工具（F12）查看控制台错误信息

### Q: 如何查看 API 文档？

启动后端后访问 http://localhost:8000/docs 可查看完整的 API 文档（Swagger UI），支持在线调试。

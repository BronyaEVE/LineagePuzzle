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

DataLineage Visualizer 是一个 **DML 脚本血缘关系分析与可视化工具**。它能够：

- 解析你提交的 DML 脚本（INSERT、UPDATE、DELETE、MERGE、CREATE TABLE AS）
- 连接 PostgreSQL 数据库获取表结构和执行计划
- 自动提取表与表之间的数据血缘关系
- 以可视化有向图的形式展示血缘链路
- 展示分段后的语句列表，支持人工检查

### 核心概念

| 概念 | 说明 |
|------|------|
| **源表 (Source)** | 数据来源的物理表，图中显示为绿色节点 |
| **中间表 (Intermediate)** | 脚本中 CREATE 定义的临时表，图中显示为黄色节点 |
| **目标表 (Target)** | 数据最终写入的表，图中显示为蓝色节点 |
| **血缘关系** | 源表到目标表的数据流向，以有向箭头表示 |

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

### 3.3 启动后端服务

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动成功后会看到：

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

### 3.4 启动前端服务

打开一个新的终端窗口：

```bash
cd frontend
npm run dev
```

启动成功后会看到：

```
  VITE v6.x.x  ready in xxx ms

  ➜  Local:   http://localhost:5173/
```

### 3.5 访问应用

在浏览器中打开 **http://localhost:5173** 即可使用。

---

## 4. 快速开始

### 第一步：填写数据库连接信息

在页面顶部的「数据库配置」区域，填入你的 PostgreSQL 连接信息：

```
主机: localhost      （Docker 映射到本机时填 localhost）
端口: 5432           （或你映射的端口，如 5433）
数据库: mydb          （你的数据库名）
用户名: postgres
密码: your_password
```

> 如果你用 Docker 部署了 PostgreSQL，运行 `docker ps` 查看 `PORTS` 列确认端口映射。

### 第二步：输入 DML 脚本

在「DML 脚本」编辑器中粘贴或输入你要分析的脚本。

### 第三步：点击「分析血缘」

点击右上角的「分析血缘」按钮，等待分析完成。

### 第四步：查看结果

- **左侧 - 血缘关系图**：展示表之间的数据流向，绿色为源表，黄色为中间表/临时表，蓝色为目标表
- **右侧 - 语句分段面板**：展示预处理后的每条语句，标注了序号和类型

### 第五步：交互操作

- 在**语句分段面板**中点击某条语句，血缘图中对应的边会高亮显示
- 在**血缘关系图**中可以缩放、拖拽、点击节点查看详情

---

## 5. 功能详解

### 5.1 数据库配置

页面顶部的配置表单用于连接 PostgreSQL 数据库。每次点击「分析血缘」时，系统会使用当前填写的连接信息。

**需要连接数据库的原因：**
1. 读取表结构信息（通过 `INFORMATION_SCHEMA`）
2. 获取执行计划（通过 `EXPLAIN`，不会实际修改数据）

> **安全说明**：系统只对 DML 语句执行 `EXPLAIN`，不会实际执行 INSERT/UPDATE/DELETE，不会修改你的数据。

### 5.2 脚本编辑器

支持输入的 SQL 类型：

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

### 5.3 血缘关系图

图中的节点和边：

| 元素 | 含义 | 颜色 |
|------|------|------|
| 绿色节点 | 源表（数据来源） | 绿色 |
| 黄色节点 | 中间表/临时表（脚本中 CREATE 的表） | 黄色 |
| 蓝色节点 | 目标表（数据写入的表） | 蓝色 |
| 有向箭头 | 数据流向，标注操作类型（INSERT/UPDATE/CREATE 等） | 灰色 |

**交互操作：**
- 鼠标滚轮：缩放
- 拖拽节点：调整位置
- 拖拽空白处：平移画布

### 5.4 语句分段面板

面板展示每条预处理后的语句，包含以下信息：

- **序号标签**：`#1`、`#2`、`#3`... 表示语句执行顺序
- **类型标签**：`CREATE`（金色）、`INSERT`（绿色）、`UPDATE`（蓝色）、`DELETE`（红色）
- **语句文本**：完整的 SQL 语句
- **引用表**：该语句读取了哪些表
- **创建/写入表**：该语句创建或修改了哪些表

**联动功能：** 点击某条语句时，血缘图中对应的边会高亮为蓝色粗线，方便定位。

### 5.5 血缘提取策略

系统采用两种策略提取血缘关系：

| 策略 | 优先级 | 说明 |
|------|--------|------|
| 执行计划 | 高 | 通过 `EXPLAIN` 获取数据库引擎的解析结果，能正确处理视图展开、别名等 |
| 静态解析 | 低 | 通过 SQL 语法树解析，作为数据库不可用时的补充 |

---

## 6. 数据库准备

### 6.1 Docker 部署 PostgreSQL（如尚未部署）

```bash
docker run -d \
  --name lineage-pg \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=testdb \
  -p 5432:5432 \
  postgres:16
```

### 6.2 创建测试表

连接到数据库后，创建一些测试表：

```sql
-- 源表
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    region VARCHAR(50)
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(id),
    amount DECIMAL(10,2),
    order_date DATE
);

-- 目标表
CREATE TABLE order_report (
    order_id INT,
    amount DECIMAL(10,2),
    customer_name VARCHAR(100),
    region VARCHAR(50)
);

CREATE TABLE customer_summary (
    customer_id INT,
    total_amount DECIMAL(10,2),
    order_count INT
);
```

### 6.3 插入测试数据

```sql
INSERT INTO customers (name, region) VALUES ('张三', '华东'), ('李四', '华北');
INSERT INTO orders (customer_id, amount, order_date) VALUES (1, 100.00, '2026-01-01'), (1, 200.00, '2026-02-01'), (2, 150.00, '2026-01-15');
```

---

## 7. 测试脚本示例

### 示例 1：简单的 INSERT-SELECT

```sql
INSERT INTO order_report (order_id, amount, customer_name)
SELECT o.id, o.amount, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id;
```

**期望结果：** 两个源表 `orders`、`customers` 通过 INSERT 指向目标表 `order_report`。

### 示例 2：包含临时表的完整流程

```sql
-- 先创建临时表存储中间结果
CREATE TEMP TABLE tmp_order_detail AS
SELECT o.id AS order_id, o.amount, c.name AS customer_name, c.region
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.amount > 0;

-- 再从临时表写入目标表
INSERT INTO order_report (order_id, amount, customer_name, region)
SELECT order_id, amount, customer_name, region
FROM tmp_order_detail;
```

**期望结果：**
- `orders` → `tmp_order_detail`（CREATE，黄色节点）
- `customers` → `tmp_order_detail`（CREATE，黄色节点）
- `tmp_order_detail` → `order_report`（INSERT，蓝色节点）

### 示例 3：多语句混合操作

```sql
-- 聚合到汇总表
INSERT INTO customer_summary (customer_id, total_amount, order_count)
SELECT customer_id, SUM(amount), COUNT(*)
FROM orders
GROUP BY customer_id;

-- 更新报表
UPDATE order_report SET amount = amount * 1.1
WHERE region = '华东';
```

**期望结果：**
- `orders` → `customer_summary`（INSERT）
- `order_report`（UPDATE，无源表）

### 示例 4：带注释和空行的脚本

```sql
-- ==========================================
-- ETL 脚本：每日订单汇总
-- ==========================================

/* 步骤1: 创建临时表 */
CREATE TEMP TABLE tmp_daily AS
SELECT
    customer_id,
    SUM(amount) AS daily_total,
    COUNT(*)    AS daily_count
FROM orders
WHERE order_date = CURRENT_DATE
GROUP BY customer_id;

/* 步骤2: 写入汇总 */
INSERT INTO customer_summary (customer_id, total_amount, order_count)
SELECT customer_id, daily_total, daily_count
FROM tmp_daily;
```

**期望结果：** 注释被自动移除，脚本正确拆分为 2 条语句，临时表血缘完整。

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
3. 检查语句分段面板中语句是否被正确识别（类型标签是否正确）

### Q: 临时表没有出现在血缘图中？

1. 确认使用的是 `CREATE TABLE` 或 `CREATE TEMP TABLE` 语法
2. `CREATE TABLE ... AS SELECT` 会被识别，但 `CREATE TABLE ... (col INT)` 后跟单独的 `INSERT` 也能识别
3. 检查语句分段面板中 CREATE 语句是否被正确保留

### Q: 只看到静态解析，没有执行计划？

执行计划获取失败时会自动回退到静态解析。常见原因：
1. 脚本中引用的临时表在数据库中不存在（EXPLAIN 会失败）
2. SQL 语法与 PostgreSQL 不兼容
3. 数据库连接中断

静态解析仍然能提取基本的血缘关系，只是无法展开视图等复杂结构。

### Q: 前端页面空白或报错？

1. 确认后端服务已启动（访问 http://localhost:8000/api/health 应返回 `{"status":"ok"}`）
2. 确认前端服务已启动
3. 打开浏览器开发者工具（F12）查看控制台错误信息

### Q: 如何查看 API 响应？

启动后端后访问 http://localhost:8000/docs 可查看完整的 API 文档（Swagger UI），支持在线调试。

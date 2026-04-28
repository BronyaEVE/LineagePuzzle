-- ============================================================
-- DataLineage Visualizer 测试用例脚本
-- 每个用例可以直接粘贴到前端「新建分析」弹窗中进行分析
--
-- 使用前请确保：
--   1. Docker PostgreSQL 已启动
--   2. 已执行 init_test_tables.sql 创建测试表和数据
--   3. 数据库配置填写正确（默认 localhost:5432/postgres/<your-password>）
--
-- 测试流程：
--   1. 逐个粘贴下面的脚本到「新建分析」弹窗，点击「分析血缘」
--   2. 每次分析后，左侧脚本列表会增加一条记录
--   3. 中间全局图谱会逐步累积所有脚本血缘关系（拼图效果）
--   4. 点击左侧脚本可查看该脚本的血缘图和语句分段
--   5. 点击「全部」可查看完整累积图谱
-- ============================================================


-- ==================== 测试用例 1 ====================
-- 场景: 简单 INSERT-SELECT（双源表 JOIN）
-- 操作: 新建分析 → 粘贴 → 分析 → 观察全局图谱
-- 期望血缘: customers → order_report, orders → order_report
-- 验证: 全局图谱出现 3 个节点(orders, customers, order_report) + 2 条边

INSERT INTO order_report (order_id, amount, customer_name)
SELECT o.id, o.amount, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id;


-- ==================== 测试用例 2 ====================
-- 场景: 包含临时表的完整流程
-- 操作: 新建分析 → 粘贴 → 分析 → 点击左侧脚本查看
-- 期望血缘:
--   orders → tmp_order_detail (CREATE)
--   customers → tmp_order_detail (CREATE)
--   tmp_order_detail → order_report (INSERT)
-- 验证:
--   全局图谱出现 4 个节点(orders, customers, tmp_order_detail, order_report)
--   orders 和 customers 为绿色源表
--   tmp_order_detail 为黄色中间表
--   order_report 在用例1后变为紫色(既被直接INSERT也被间接INSERT)

CREATE TEMP TABLE tmp_order_detail AS
SELECT o.id AS order_id, o.amount, c.name AS customer_name, c.region
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.amount > 0;

INSERT INTO order_report (order_id, amount, customer_name, region)
SELECT order_id, amount, customer_name, region
FROM tmp_order_detail;


-- ==================== 测试用例 3 ====================
-- 场景: 多语句混合操作（INSERT + UPDATE）
-- 操作: 新建分析 → 粘贴 → 分析 → 观察全局图谱
-- 期望血缘:
--   orders → customer_summary (INSERT)
--   order_report 无源表 (UPDATE)
-- 验证: 全局图谱新增 customer_summary 节点(蓝色目标表)

INSERT INTO customer_summary (customer_id, total_amount, order_count)
SELECT customer_id, SUM(amount) AS total_amount, COUNT(*) AS order_count
FROM orders
GROUP BY customer_id;

UPDATE order_report SET amount = amount * 1.1
WHERE region = '华东';


-- ==================== 测试用例 4 ====================
-- 场景: 带注释的复杂 ETL 脚本
-- 操作: 新建分析 → 粘贴 → 分析 → 检查语句分段面板
-- 期望: 注释被自动移除，正确拆分为 3 条语句
-- 验证: 语句分段面板显示 #1 CREATE / #2 INSERT / #3 INSERT

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


-- ==================== 测试用例 5 ====================
-- 场景: 多层临时表嵌套
-- 操作: 新建分析 → 粘贴 → 分析 → 查看全局图谱
-- 期望血缘:
--   products → tmp_product_orders (CREATE)
--   orders → tmp_product_orders (CREATE)
--   tmp_product_orders → tmp_high_value (CREATE)
--   tmp_high_value → order_report (INSERT)
-- 验证: 全局图谱出现 tmp_product_orders 和 tmp_high_value 两个黄色中间表

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


-- ==================== 测试用例 6 ====================
-- 场景: 包含被过滤的 DDL（ALTER/DROP 应被忽略）
-- 操作: 新建分析 → 粘贴 → 分析 → 检查语句分段
-- 期望: 只保留 INSERT，ALTER 和 DROP 被过滤
-- 验证: 语句分段面板只显示 1 条 INSERT 语句

ALTER TABLE order_report ADD COLUMN IF NOT EXISTS notes TEXT;

INSERT INTO order_report (order_id, amount, customer_name, region)
SELECT o.id, o.amount, c.name, c.region
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.status = 'completed';

DROP TABLE IF EXISTS tmp_not_exist;


-- ============================================================
-- 端到端验证流程
-- ============================================================
--
-- 1. 依次提交用例 1-6（每次点「新建分析」→ 粘贴 → 「分析血缘」）
-- 2. 左侧脚本列表应有 6 个脚本
-- 3. 点击「全部」查看全局累积图谱：
--    - 应包含约 8 个表节点（orders, customers, products, order_report, customer_summary, daily_metrics, 以及多个临时表）
--    - 边数量应超过 10 条
--    - order_report 应为紫色混合角色（多个脚本向其写入）
-- 4. 逐个点击脚本，验证每个脚本的血缘图和语句分段
-- 5. 删除某个脚本，验证全局图谱自动更新（边减少，孤立表被清理）
-- 6. 刷新页面，验证数据从 JSON 文件恢复

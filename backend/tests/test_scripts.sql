-- ============================================================
-- DataLineage Visualizer 测试用例脚本
-- 每个用例可以直接粘贴到前端脚本编辑器中进行分析
-- ============================================================


-- ==================== 测试用例 1 ====================
-- 简单 INSERT-SELECT（双源表 JOIN）
-- 期望血缘: customers → order_report, orders → order_report

INSERT INTO order_report (order_id, amount, customer_name)
SELECT o.id, o.amount, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id;


-- ==================== 测试用例 2 ====================
-- 包含临时表的完整流程
-- 期望血缘:
--   orders → tmp_order_detail (CREATE)
--   customers → tmp_order_detail (CREATE)
--   tmp_order_detail → order_report (INSERT)

CREATE TEMP TABLE tmp_order_detail AS
SELECT o.id AS order_id, o.amount, c.name AS customer_name, c.region
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.amount > 0;

INSERT INTO order_report (order_id, amount, customer_name, region)
SELECT order_id, amount, customer_name, region
FROM tmp_order_detail;


-- ==================== 测试用例 3 ====================
-- 多语句混合操作（INSERT + UPDATE）
-- 期望血缘:
--   orders → customer_summary (INSERT)
--   order_report 无源表 (UPDATE)

INSERT INTO customer_summary (customer_id, total_amount, order_count)
SELECT customer_id, SUM(amount) AS total_amount, COUNT(*) AS order_count
FROM orders
GROUP BY customer_id;

UPDATE order_report SET amount = amount * 1.1
WHERE region = '华东';


-- ==================== 测试用例 4 ====================
-- 带注释和空行的复杂 ETL 脚本
-- 期望: 注释被自动移除，正确拆分为 3 条语句

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

/* 步骤2: 合并客户信息 */
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
-- 多层临时表嵌套
-- 期望血缘:
--   products → tmp_product_orders (CREATE)
--   orders → tmp_product_orders (CREATE)
--   tmp_product_orders → tmp_high_value (CREATE)
--   tmp_high_value → order_report (INSERT)

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
-- 包含被过滤的 DDL（ALTER/DROP 应被忽略）
-- 期望: 只保留 INSERT，ALTER 和 DROP 被过滤

ALTER TABLE order_report ADD COLUMN IF NOT EXISTS notes TEXT;

INSERT INTO order_report (order_id, amount, customer_name, region)
SELECT o.id, o.amount, c.name, c.region
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.status = 'completed';

DROP TABLE IF EXISTS tmp_not_exist;

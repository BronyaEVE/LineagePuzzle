-- ============================================================
-- DataLineage Visualizer 测试表初始化脚本
-- 使用方法: psql -h localhost -U postgres -d testdb -f init_test_tables.sql
-- ============================================================

-- 清理已有的测试表（忽略不存在的表）
DROP TABLE IF EXISTS order_report;
DROP TABLE IF EXISTS customer_summary;
DROP TABLE IF EXISTS daily_metrics;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS products;

-- ==================== 源表 ====================

-- 客户表
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    region VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 订单表
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(id),
    product_id INT,
    amount DECIMAL(10,2) NOT NULL,
    order_date DATE NOT NULL,
    status VARCHAR(20) DEFAULT 'pending'
);

-- 产品表
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    price DECIMAL(10,2)
);

-- ==================== 目标表 ====================

-- 订单报表（示例1、2、4 的目标表）
CREATE TABLE order_report (
    order_id INT,
    amount DECIMAL(10,2),
    customer_name VARCHAR(100),
    region VARCHAR(50)
);

-- 客户汇总表（示例3 的目标表）
CREATE TABLE customer_summary (
    customer_id INT,
    total_amount DECIMAL(10,2),
    order_count INT
);

-- 每日指标表（综合场景的目标表）
CREATE TABLE daily_metrics (
    metric_date DATE,
    region VARCHAR(50),
    total_amount DECIMAL(10,2),
    order_count INT,
    avg_amount DECIMAL(10,2)
);

-- ==================== 测试数据 ====================

INSERT INTO customers (name, region) VALUES
    ('张三', '华东'),
    ('李四', '华北'),
    ('王五', '华南'),
    ('赵六', '华东'),
    ('钱七', '华北');

INSERT INTO products (name, category, price) VALUES
    ('笔记本电脑', '电子产品', 5999.00),
    ('手机', '电子产品', 3999.00),
    ('耳机', '配件', 299.00),
    ('键盘', '配件', 499.00),
    ('显示器', '电子产品', 1999.00);

INSERT INTO orders (customer_id, product_id, amount, order_date, status) VALUES
    (1, 1, 5999.00, '2026-04-20', 'completed'),
    (1, 3, 299.00,  '2026-04-21', 'completed'),
    (2, 2, 3999.00, '2026-04-21', 'completed'),
    (2, 4, 499.00,  '2026-04-22', 'pending'),
    (3, 5, 1999.00, '2026-04-22', 'completed'),
    (3, 3, 299.00,  '2026-04-23', 'completed'),
    (4, 1, 5999.00, '2026-04-23', 'pending'),
    (4, 2, 3999.00, '2026-04-24', 'completed'),
    (5, 4, 499.00,  '2026-04-24', 'completed'),
    (5, 5, 1999.00, '2026-04-25', 'pending');

# LineagePuzzle — 项目文档

[English](./PROJECT.md) | **简体中文**

> 本文是详细文档。快速上手见 [README.md](../README.md)。

## 项目背景与目标

### 解决什么问题

现代化数据平台和数据库普遍自带血缘分析，但都预设了"完整、联网、新建的大数据平台"这一前提。现实中大量团队受困于：

- **老旧调度工具**（Control-M、Kettle、自研调度器）只执行脚本，从不记录数据来源与流向
- **数仓 ETL 脚本堆积**，改一张表无法预知爆炸半径，接手者要靠读 SQL 逆向链路
- **数据库自带血缘能力薄弱**（如 PostgreSQL 依赖视图仅表级、不覆盖 ETL 全链路、无可视化）
- **内网隔离环境**装不了 Airflow / DataHub / OpenLineage 这类需要 Kafka、K8s、元数据库的重型方案

### LineagePuzzle 的定位

一个**零依赖、可离线、装进 U 盘双击即跑**的血缘分析小工具，用最轻量的方式把"先进平台的血缘标配能力"带到任何内网环境：

- 纯 SQL 语法（sqlglot AST）静态解析，**不连数据库也能提取完整血缘**
- **增量拼图**模式：每次分析一个脚本，逐步拼出全局血缘图谱
- 表级 + 列级血缘、影响分析、参数化 SQL 支持
- 便携版自带 Python 运行时，目标机零安装

### 适用环境

| 维度 | 要求 |
|------|------|
| 网络 | 无要求（离线模式无需任何网络） |
| 数据库 | 可选（仅在线校验时需要 PostgreSQL） |
| 运行时 | 便携版零安装；开发模式需 Python 3.10+ / Node 18+ |
| 部署形态 | 单进程单端口（一体化部署）或便携包（双击 run.bat） |

---

## 目录

1. [核心概念](#1-核心概念)
2. [系统架构](#2-系统架构)
3. [核心流程](#3-核心流程)
4. [功能详解](#4-功能详解)
5. [血缘提取能力](#5-血缘提取能力)
6. [预处理规则](#6-预处理规则)
7. [API 参考](#7-api-参考)
8. [存储设计](#8-存储设计)
9. [部署](#9-部署)
10. [测试脚本示例](#10-测试脚本示例)
11. [常见问题](#11-常见问题)

---

## 1. 核心概念

### 增量拼图模式

传统血缘工具要求一次性导入所有脚本。本项目采用**增量拼图**：

- 每次分析一个 DML 脚本，自动提取血缘关系
- 多次分析结果**累积**到全局血缘图谱，像拼图一样逐步还原完整血缘
- 删除脚本后，全局图谱**自动更新**（全表扫清理孤立表）

### 节点角色

| 概念 | 图中颜色 | 判定 |
|------|---------|------|
| **源表 (Source)** | 🟢 绿色 `#52c41a` | 只在边的 source 端出现 |
| **中间表 (Intermediate)** | 🟡 黄色 `#faad14` | 既作为 source 又作为 target（脚本中 CREATE 的临时表） |
| **目标表 (Target)** | 🔵 蓝色 `#1890ff` | 只在边的 target 端出现 |

### 血缘层级

| 层级 | 说明 |
|------|------|
| **表级血缘** | 源表 → 目标表的数据流向，以有向箭头表示（保底层，始终生成） |
| **列级血缘** | 目标列 ← 源列的映射 + 变换表达式（增强层，点边查看） |

> 列级是增强层：解析失败/降级（如 `SELECT *`）不影响表级边。

### 分析模式

| 模式 | 说明 |
|------|------|
| **离线模式（默认）** | 不填数据库配置，纯 AST 解析提取血缘，无需数据库 |
| **在线模式** | 填写数据库配置，额外校验表是否存在、补充列信息 |

> 血缘提取**统一基于 sqlglot AST 静态解析**，确定性强、可离线。数据库仅用于校验与补充，**不影响血缘结果**。在线模式连接失败时自动降级为离线模式。

---

## 2. 系统架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                          前端页面（React + antd v6）                    │
│                                                                      │
│  Header: [搜索框] [预处理规则] [标签维度] [导入导出] [新建分析]          │
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
│                                   │          │ ├── preprocess_r.│    │
│                          ┌────────▼────────┐ │ └── scripts/*.json│   │
│                          │ DB 校验器(可选)  │ └─────────────────┘    │
│                          │ INFO_SCHEMA     │                        │
│                          └─────────────────┘                        │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                    PostgreSQL（可选，仅校验用）
```

**四层架构：**

| 层级 | 职责 |
|------|------|
| **前端页面层** | 三栏布局 + Header 工具栏。血缘图用 React Flow 渲染 |
| **分析器层** | 预处理（含参数替换）→ 语句拆分 → AST 血缘提取（表级 + 列级）→ 可选 DB 校验 |
| **持久化存储层** | JSON/JSONL 文件存储，带文件锁、script_ids 反向索引、孤立表清理 |
| **数据库层（可选）** | 表结构校验与列信息补充；不参与血缘提取 |

---

## 3. 核心流程

### 分析流程

```
用户提交脚本
     │
     ▼
步骤1: 预处理规则 → 应用正则替换规则(参数映射为内置特例);${param} 替换为实际值
     │
     ▼
步骤2: 预处理     → 去注释、压缩空格、去空行
     │
     ▼
步骤3: 语句拆分   → 按 ; 拆分，保留 CREATE/INSERT/UPDATE/DELETE/MERGE
     │
     ▼
步骤4: AST 血缘提取 → 表级（源→目标）+ 列级（目标列←源列+变换）
     │
     ▼
步骤5: 数据库校验(可选) → 表是否存在、列信息补充
     │
     ▼
步骤6: 持久化存储 → 保存到 JSON + 更新全局图谱（文件锁保护）
```

### 增量累积机制

**分析一个脚本后：**
1. 脚本保存为 `data/scripts/{script_id}.json`
2. 表合并到 `data/tables.json`（以 `schema.table` 为 key，带 `script_ids` 反向索引）
3. 边追加到 `data/edges.jsonl`（每行一条，O(1) 追加）

**删除一个脚本后：**
1. 删除脚本文件
2. 重写 `edges.jsonl`，移除该脚本的边
3. **全表扫** `tables.json`，移除该 script_id，`script_ids` 变空的表删除（孤立表清理）

> 孤立表清理用全表扫而非"只看 edges 涉及的表"，因为表可能从 database_info 或无源表 lineage 登记进 tables.json 但不在 edges 里（UPDATE 无源表场景，边不写 edges.jsonl）。

---

## 4. 功能详解

### 4.1 血缘图谱交互

| 操作 | 效果 |
|------|------|
| 点击脚本列表顶部置顶的「全局图谱」 | 显示全局累积血缘图谱 |
| 点击左侧脚本 | 中栏切换为该脚本血缘图，右栏显示语句分段 |
| 点击节点 | 展开/收起完整表名，并触发影响分析（高亮上下游链路） |
| 点击节点入边侧 − 按钮 | 折叠上游全部链路（隐藏节点和边），节点显示橙色 +N 计数 |
| 点击节点出边侧 − 按钮 | 折叠下游全部链路（隐藏节点和边），橙色 +N 计数 |
| 点击 +N 计数 | 展开已折叠的上游/下游链路 |
| 点击边 | 弹出列级血缘 Drawer（目标列←源列+变换），单边高亮 |
| 点击语句 | 该 seq 的所有边高亮蓝色 |
| 搜索框输入 | 模糊匹配表名/字段名。搜表名 = 点击该节点（聚焦+影响分析）；搜字段 = 高亮该字段流转经过的所有边。重复搜同一目标也会重新聚焦 |

> **折叠：** 每个节点在入边侧/出边侧各有一个 14px 的 +/- 按钮（TB 布局在节点上下边缘，LR 布局在左右边缘）。折叠会递归隐藏整条上游/下游链路。切换脚本或切到全局图谱时折叠状态自动重置。

**高亮优先级：** 单边（点边） > 影响分析（上下游双色） > 语句级（点语句） > 脚本级 > 默认（无高亮，静态边）

> **边动画：** 默认所有边都是静态的（无流动动画），保证大图浏览流畅——只有被高亮的边才会流动。

**节点样式：** 宽度自适应（短名收缩到最小 150px，长名截断 + 点击展开）；展开时白边框发光。

**布局：** 右上角按钮切换垂直（TB）/ 水平（LR）。滚轮缩放、拖拽节点、拖拽空白平移、右下角迷你地图。

### 4.2 搜索框（Header）

支持**模糊匹配表名和字段名**：

1. 输入关键词（如 "order"）
2. 下拉显示所有匹配的表（● 绿点）和字段（◇ 钻石）。字段按「表.列」聚合，不同表的同名字段是独立条目（`orders.id` 与 `users.id` 分开）
3. 选中表节点 → 图自动聚焦该节点 + 触发影响分析（与点节点完全一致：上下游双色高亮）
4. 选中字段 → 图高亮**该字段流转经过的所有边**（紫色 `#722ed1`）+ fitView 覆盖这些边的端点。跨多边的字段在下拉里显示「(N 条流转)」

搜索范围根据当前视图自动切换：全局视图搜全局图，脚本视图搜当前脚本。

> **重复搜索修复：** 每次选中都带一个递增的 `focusToken`，所以连续两次搜同一目标（值相同）也会重新聚焦——React effect 保证重跑。

> **折叠感知：** 如果聚焦的节点/边端点被折叠隐藏，会先自动展开挡路的折叠链，再聚焦（pendingFocus 异步补做）。

### 4.3 影响分析（点节点）

点击节点触发影响分析，基于 networkx 内存图计算：

- **下游**（改这张表会影响谁）：橙色 `#fa8c16` 高亮全部下游链路
- **上游**（这张表的数据来自谁）：青色 `#13c2c2` 高亮全部上游链路

> **作用范围**：影响分析在两种视图下均可用——全局图谱视图分析全图（可跨脚本）；单脚本视图仅限当前脚本的边。

> **菱形依赖完整覆盖**：当 `A→B→C` 且 `A→C` 同时存在时，点击 C 用 `all_simple_paths` 返回全部路径，A→B 这条中间边也会被高亮（不会因最短路径而漏掉）。路径爆炸有 `cutoff` 限深 + 单源路径数上限 + 有环降级三重防护。

### 4.4 批量导入

「新建分析」弹窗切换到「批量导入文件」：

- 拖入多个 `.sql` 文件（浏览器多选），或一个含多 `.sql` 的 `.zip` 压缩包
- zip 在前端用 fflate 解压，提取所有 `.sql`
- 每个文件产出**独立脚本**（各自 analysis_id，可单独删除/重命名）
- 部分文件失败不影响其他文件，失败的在提示中显示
- **可选批量打标**：若已定义标签维度（见 4.5），导入区会出现「打标签（可选）」按钮。选好后**整批脚本统一打上同一组标签**——一批同层/同业务线的 ETL 脚本一次打完

### 4.5 标签筛选与脚本分组

给脚本打**扁平多维度标签**（如 `[C层, 个人借据]`），然后在全局画布按标签筛选只显示命中脚本贡献的血缘。这是分层数仓（O/C/D 层）和按业务线组织 ETL 的天然做法。

**数据模型——扁平标签，维度外置：**

- 每个脚本存一个扁平 `tags: string[]` 数组（如 `["C层", "个人借据"]`），**不带任何维度结构**
- 维度定义在 `tag_schema.json`（`{dimensions: [{name, values}]}`），管理员通过 Header 的「标签维度」按钮维护
- 维度名**不写死**——开箱默认 `dimensions: []`（空），部署后由管理员填实际维度名和标签值。增删维度完全不碰脚本数据，被删维度的孤儿标签只是不再出现在筛选器里

**三种打标方式：**

1. **单条打标** —— 每个列表项显示已打标签（紫色）+ 一个标签图标按钮，点击弹出按维度分组的勾选浮层
2. **批量打标** —— 列表头部点「批量」，勾选多个脚本，然后「打标签」一次性给选中脚本打同一组标签
3. **上传时打标** —— 批量导入面板的可选打标（见 4.4）

**筛选语义（类 Excel：维度内 OR × 跨维度 AND）：**

筛选器是脚本列表顶部的多选下拉，可选项按维度分组。选中标签后的命中逻辑：

- **同一维度内：** OR —— 脚本含该维度下任意一个选中标签即命中（如 `个人借据 或 信用卡`）
- **跨维度：** AND —— 脚本必须满足所有「有选中项的维度」（如必须 `C层` 且 `个人借据或信用卡`）

这和 Excel 的列筛选一致，符合「我要 C 层的、个人借据业务线的脚本」这种直觉。

**画布效果（边驱动）：**

- 只有**全局图谱视图**应用标签筛选；切到单脚本视图时筛选器灰显但不清空（返回全局时恢复）
- 画布只保留 `script_id` 在命中集合中的边，再由这些边推导节点（与全局图构建逻辑一致）——没有命中边经过的孤立表不显示
- 列表里未命中的脚本**灰显（不隐藏）**，让你知道它们存在

> **典型流程：** 管理员在「标签维度」里定义维度（数仓层、业务线）→ 用户打标（上传时批量打标最快）→ 全局视图下在筛选器里勾选标签 → 画布收窄到这一片的血缘。改标签或删维度都是非破坏性的。

### 4.6 预处理规则

见 [第 6 节](#6-预处理规则)。

### 4.7 导入/导出

| 操作 | 说明 |
|------|------|
| 导出 | 一键导出全部数据（tables + edges + scripts + preprocess_rules + tag_schema）为 JSON 文件 |
| 导入 | 用导出的 JSON 覆盖当前所有数据（会清空现有数据，需确认）。旧版导出文件无 `tag_schema` 字段时默认空 schema |

### 4.8 图导出

右上角按钮导出当前图谱：
- **PNG**：截图当前画布（排除控件/迷你地图）
- **HTML**：生成独立可打开的 HTML 文件，内嵌图谱数据

### 4.9 支持的 SQL 类型

| 类型 | 示例 | 处理 |
|------|------|------|
| `CREATE TABLE ... AS SELECT` | `CREATE TEMP TABLE tmp AS SELECT * FROM src;` | 保留（中间表） |
| `INSERT INTO ... SELECT` | `INSERT INTO tgt SELECT * FROM src;` | 保留 |
| `UPDATE ... SET` | `UPDATE tgt SET col = val WHERE ...;` | 保留 |
| `DELETE FROM` | `DELETE FROM tgt WHERE ...;` | 保留 |
| `MERGE INTO` | `MERGE INTO tgt USING src ON ...;` | 保留 |
| `ALTER TABLE` / `DROP TABLE` / `GRANT` | - | 过滤（非血缘语句） |

**预处理**：自动移除注释（`--` 单行、`/* */` 多行）、压缩空格、按 `;` 拆分。

---

## 5. 血缘提取能力

### 5.1 表级血缘

| 语句类型 | 目标表 | 源表 | 提取规则 |
|----------|--------|------|----------|
| `CREATE [TEMP] TABLE t AS SELECT` | `t` | SELECT 的 FROM/JOIN | CTAS |
| `INSERT INTO t SELECT ...` | `t` | SELECT 的 FROM/JOIN | INSERT-SELECT |
| `UPDATE t SET ... FROM s` | `t` | FROM 子句 | PG 扩展 |
| `DELETE FROM t USING s` | `t` | USING | PG 扩展 |
| `MERGE INTO t USING src` | `t` | `src` | MERGE |

**全限定命名：** 所有表以 `schema.table` 作为唯一标识。裸表名补 `public`。`public.orders` 与 `reporting.orders` 视为两个不同节点（杜绝跨 schema 同名表冲突）。

### 5.2 列级血缘

独立模块 `column_lineage.py`，与表级解耦。能力边界：

| 场景 | 能力 |
|------|------|
| 显式列 `INSERT INTO t(a,b) SELECT x,y` | ✅ 完整映射 |
| JOIN + 别名 `o.id, c.name` | ✅ 解析到各自物理表 |
| 表达式 `price*qty` | ✅ 多源列 + transform |
| 聚合 `SUM(x)` | ✅ 源列 + transform |
| CTAS | ✅ 支持 |
| UPDATE SET | ✅ 左=目标列，右表达式找源列 |
| 单表无别名 `SELECT x FROM src` | ✅ 回退到唯一源表 |
| 派生表穿透 `FROM (SELECT...) sub` | ✅ 列穿透到物理表 |
| 嵌套子查询 | ✅ 递归穿透到最底层 |
| JOIN + 子查询混合 | ✅ 各列穿透到正确物理表 |
| `SELECT *` | ⚠️ 降级为空（表级边保底） |

> **派生表穿透**：外层 SELECT 引用派生表输出列时，递归解析派生表内部的 projection，追溯到物理源表。派生表内由聚合/常量产生的列（如 `COUNT(*) AS cnt`）无物理源，不杜撰源列。此行为经与 sqllineage 1.5.8 一致性验证。

---

## 6. 预处理规则

生产环境里的 SQL 脚本格式千奇百怪：`${icl_schema}` 模板占位符、特殊注释、ETL 工具注入的标记等，内置规则几乎不可能全覆盖。本模块把「参数映射」和「自定义清洗」统一为**正则替换规则**，用户可自行增减，应对各种奇怪格式。

每条规则在 SQL 解析前对脚本文本执行一次 `re.sub(pattern, replacement)`。规则字段：

| 字段 | 说明 |
|------|------|
| `name` | 规则名称（如「去单行注释」「参数映射: icl_schema」） |
| `pattern` | Python 正则表达式（`re.sub` 第一个参数，支持捕获组） |
| `replacement` | 替换文本，支持 `$1` `$2` 反向引用 |
| `enabled` | 开关，关闭的规则在预处理时跳过 |
| `builtin` | 内置标记（参数映射类规则为 `true`，前端蓝色标记区分） |

**参数映射**已降级为规则的一种内置特例：每条参数映射对应一条 `id` 以 `param-` 前缀、`builtin=true` 的规则，`pattern` 形如 `\$\{param_name\}`。用户可像编辑普通规则一样编辑、关闭或删除它们。

### 6.1 配置方法

点击 Header「预处理规则」按钮，管理规则列表：

- 点击「添加规则」新增一条自定义清洗规则
- 每条规则可填名称、正则、替换文本，并用开关启用/禁用
- 内置规则（参数映射）以蓝色「内置」标记区分
- 非法正则会在前端红色高亮，保存时被后端过滤

示例规则：

| 名称 | pattern | replacement | 说明 |
|------|---------|-------------|------|
| 参数映射: icl_schema | `\$\{icl_schema\}` | `ods` | 内置，替换占位符 |
| 参数映射: env | `\$\{env\}` | `prod` | 内置，替换占位符 |
| 去 MySQL 注释 | `#[^\n]*` | (空) | 自定义，清洗 `#` 风格注释 |

### 6.2 参数替换效果

参数映射类规则的替换效果（`enabled=true` 时）：

| 占位符 | 有规则 | 无规则（兜底） |
|--------|--------|----------------|
| `${icl_schema}.orders` | `ods.orders` | `icl_schema.orders`（兜底用参数名当标识符） |
| `${schema}_${env}.report` | `dw_prod.report` | `schema_env.report` |
| `WHERE dt = ${batch_date}` | `WHERE dt = <规则值>` | `WHERE dt = batch_date`（当列名，对血缘无影响） |

> **兜底机制**：即使未配置任何参数规则，`${param}` 也会被替换成参数名本身（当合法标识符），保证血缘仍可提取。

### 6.3 执行流水线

预处理分两阶段，规则只在阶段 A 执行：

```
阶段 A（可配置）→ 阶段 B（固定核心）→ 兜底
  按规则顺序执行     去注释/DO block/事务      ${param}→参数名
  正则替换           补分号/压缩空格
```

阶段 B 的去注释、DO block 提取、事务补分号是 splitter / sqlglot 正常工作的前提，不暴露给用户开关。

> **注意**：预处理规则在**分析新脚本时**生效。已有脚本的节点不会自动更新，需重新分析才能应用新规则。

---

## 7. API 参考

所有端点前缀 `/api`。Swagger UI：`http://localhost:8000/docs`。

### 分析

| 端点 | 方法 | 说明 |
|------|------|------|
| `/analyze` | POST | 提交脚本分析（database_config 可选，None 为离线模式） |
| `/analyze-batch` | POST | 批量分析多个文件（每个产出独立脚本）。可选 `tags` 给整批统一打标 |
| `/impact-analysis/{table}` | GET | 影响分析（上下游/路径/环） |

### 脚本管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/scripts` | GET | 脚本列表（含 `tags`） |
| `/scripts/{id}` | GET / DELETE | 脚本详情 / 删除 |
| `/scripts/{id}/name` | PUT | 重命名 |
| `/scripts/{id}/tags` | PUT | 给脚本打标（全量替换，`tags: string[]`） |
| `/scripts/batch-tags` | POST | 批量给多个脚本打同一组标签（`{script_ids, tags}`） |
| `/scripts/{id}/statements` | GET | 语句分段 |
| `/scripts/{id}/statements/{seq}` | PUT | 修正语句解析 |

### 全局数据

| 端点 | 方法 | 说明 |
|------|------|------|
| `/global-graph` | GET | 全局图谱（含 column_mappings） |
| `/tables` | GET | 全局表注册表 |
| `/tag-schema` | GET / PUT | 标签维度定义（`{dimensions: [{name, values}]}`）；默认空，管理员维护 |
| `/preprocess-rules` | GET / PUT | 预处理规则（正则替换规则；参数映射为内置类型） |
| `/param-mapping` | GET / PUT | *(旧版，向后兼容，等价于 /preprocess-rules)* |
| `/export` | GET | 导出全部数据（含 `tag_schema`） |
| `/import` | POST | 导入数据（覆盖） |
| `/health` | GET | 健康检查 |

---

## 8. 存储设计

### 目录结构

```
backend/data/
├── tables.json          # 全局表注册表（schema.table 为 key，带 script_ids 反向索引）
├── edges.jsonl          # 全局血缘边（JSON Lines，追加写，带 column_mappings）
├── preprocess_rules.json # 预处理规则（正则替换；参数映射为内置类型）
├── tag_schema.json      # 标签维度定义（{dimensions: [{name, values}]}）；默认空
├── store.lock           # 文件锁
└── scripts/
    └── {id}.json        # 各脚本分析结果（含扁平 `tags: string[]`）
```

### 并发与一致性

| 机制 | 说明 |
|------|------|
| **文件锁**（filelock） | 所有写操作在 `store.lock` 保护下原子完成 |
| **追加写** | 新边 append 到 `edges.jsonl` 尾部，O(1) |
| **删除重写** | 删除脚本时过滤重写 edges.jsonl（低频操作） |
| **script_ids 全表扫** | 孤立表清理遍历 tables.json，移除 script_id，空的删表 |

### 向后兼容

`VisEdge` / `GlobalEdge` 的 `column_mappings` 字段用 `Field(default_factory=list)`，旧数据（无此字段）反序列化为空数组，不报错。`AnalysisResult` / `ScriptSummary` 的 `tags` 字段同理——旧脚本（无 `tags`）加载为空数组。

**参数映射自动迁移**：首次启动检测到旧 `param_mapping.json` 存在时，自动转为 `preprocess_rules.json` 中的 builtin 规则（每条 `{param: value}` → 一条 `id=param-{name}`、`pattern=\$\{name\}`、`builtin=true` 的规则）。迁移后旧文件不再使用。导入旧版导出的 JSON（含 `param_mapping` 字段而无 `preprocess_rules`）也会自动转换。

**标签维度**：`tag_schema.json` 首次访问时创建为空。导入旧版导出 JSON（无 `tag_schema` 字段）时写入空 schema。删除维度是非破坏性的——脚本上的孤儿标签值会被筛选器忽略（没有维度认领就不展示），重新保存受影响脚本的标签即可清理。

---

## 9. 部署

### 9.1 开发模式

```bash
./ctl.sh start    # 后端 :8000 + 前端 dev :5173
./ctl.sh stop
./ctl.sh restart
./ctl.sh status
```

### 9.2 一体化部署（生产）

构建前端后，后端单进程同时服务 API + 页面：

```bash
cd frontend && npm run build
cd ../backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

访问 `http://localhost:8000`（单端口，无需前端 dev server）。dev 模式（未 build）不挂载静态文件，不影响 vite 开发。

### 9.3 数据库准备（可选）

数据库**可选**。仅在需要在线校验时准备：

```bash
docker run -d \
  --name lineage-pg \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=<your-password> \
  -e POSTGRES_DB=postgres \
  -p 5432:5432 \
  postgres:16

# 创建测试表（可选）
docker exec -i lineage-pg psql -U postgres < backend/tests/init_test_tables.sql
```

> 离线模式下不需要数据库——直接粘贴 SQL 分析即可。

### 9.4 便携版（绿色包，零安装）

**普通用户**：直接从 [GitHub Releases](../..//releases/latest) 下载 `LineagePuzzle-vX.Y.Z-portable.zip`，解压后双击 `run.bat` 即可，**无需自己打包**。

**开发者**（需要在本地构建最新版）：用 `pack_portable.bat`（必须在**有网**的开发机执行，会从镜像下载嵌入式 Python + 装依赖）：

```bash
pack_portable.bat    # 产出 dist-portable/（约 94MB）
```

将 `dist-portable/` 整个文件夹拷贝到目标机器，双击 `run.bat`，浏览器开 `http://localhost:8000`。

**目标机不需要安装任何东西**（无需 Python、Node、Docker）。便携版内嵌 Python 3.13.12 embeddable 运行时 + 全部依赖。

便携版目录结构：

```
dist-portable/
├── python/              内嵌 Python + 全部依赖（勿改）
├── app/                 后端代码（勿改）
├── frontend/dist/       前端页面（勿改）
└── run.bat              启动脚本（双击运行）
```

---

## 10. 测试脚本示例

以下示例可直接粘贴到「新建分析」弹窗。**离线模式下无需准备数据库。**

### 示例 1：简单 INSERT-SELECT（双源表 JOIN）

```sql
INSERT INTO order_report (order_id, amount, customer_name)
SELECT o.id, o.amount, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id;
```

**期望**：3 节点（orders/customers/order_report）+ 2 边。点边看列级：`order_id←orders.id`, `customer_name←customers.name`。

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

先在「预处理规则」配置一条参数映射类规则 `${icl_schema}` → `ods`，再分析：

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

**期望**：形成 `src→tmp_a→tmp_b→report` 链路，tmp_a/tmp_b 为黄色中间表。

### 示例 5：跨 schema 同名表

```sql
INSERT INTO reporting.fact
SELECT a.x FROM public.orders a JOIN reporting.orders b ON a.id = b.id;
```

**期望**：`public.orders` 和 `reporting.orders` 是两个独立节点（不冲突）。

### 端到端验证流程

1. 依次提交示例，验证全局图谱逐步累积
2. 点击边查看列级血缘 Drawer
3. 点击节点查看影响分析（上下游双色高亮）
4. 用搜索框搜索表名/字段名，选中后聚焦
5. 删除某个脚本，验证全表扫清理孤立表
6. 刷新页面，验证数据从 JSON 恢复

---

## 11. 常见问题

### Q: 不连数据库能用吗？

**能。** 离线模式（默认）完全不需要数据库。血缘提取基于 SQL 语法解析。只有需要校验表是否存在时才连数据库。

### Q: 分析时报数据库连接失败？

数据库连接失败会**自动降级为离线模式**，仍返回血缘结果。检查：PostgreSQL 是否运行、端口/账号是否正确、防火墙。

### Q: 列级血缘看不到？

1. 确认不是 `SELECT *`（无法解析列级，降级为表级）
2. 点击边，右侧 Drawer 展示列级映射
3. `SELECT *` 显示"无列级映射"是正常的（表级血缘仍正常）

### Q: 参数占位符 `${param}` 报错？

sqlglot 无法直接解析 `${param}`。在 Header「预处理规则」配置一条参数映射类规则（pattern 自动生成为 `\$\{param_name\}`），分析时自动替换。即使不配置，兜底机制也会把 `${param}` 替换成参数名本身当标识符。

### Q: 删除脚本后图谱还有残留节点？

已修复。删除脚本会全表扫清理孤立表。如仍有残留，刷新页面。

### Q: 节点名太长看不全？

点击节点，展开显示完整表名（不受截断限制）。再点收起。

### Q: 影响分析点击节点后部分边没高亮？

已修复。改用 `all_simple_paths` 后，菱形依赖（A→B→C 且 A→C）的所有中间边都会高亮。若提示"路径较多，仅高亮部分"，说明触发了路径数上限保护（病态稠密图才会）。

### Q: 前端页面空白？

1. 确认后端服务已启动（`http://localhost:8000/api/health` 返回 ok）
2. F12 查看控制台错误
3. 确认前端已 build（一体化模式下需要 `npm run build`）

### Q: 如何查看 API 文档？

`http://localhost:8000/docs`（Swagger UI）。

### Q: 便携版怎么用？

双击 `run.bat`，浏览器开 :8000，零安装。详见 [9.4 便携版](#94-便携版绿色包零安装)。

### Q: 数据保存在哪？

`backend/data/` 目录（tables.json / edges.jsonl / preprocess_rules.json / scripts/*.json）。备份此目录即备份所有分析结果。便携版在 `app/data/`。

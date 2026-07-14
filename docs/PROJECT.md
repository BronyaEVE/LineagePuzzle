# LineagePuzzle — Project Documentation

**English** | [简体中文](./PROJECT.zh-CN.md)

> This is the detailed documentation. For a quick start, see [README.md](../README.md).

## Table of Contents

1. [Core Concepts](#1-core-concepts)
2. [System Architecture](#2-system-architecture)
3. [Core Workflow](#3-core-workflow)
4. [Feature Reference](#4-feature-reference)
5. [Lineage Extraction Capabilities](#5-lineage-extraction-capabilities)
6. [Preprocess Rules](#6-preprocess-rules)
7. [API Reference](#7-api-reference)
8. [Storage Design](#8-storage-design)
9. [Deployment](#9-deployment)
10. [Example SQL Scripts](#10-example-sql-scripts)
11. [FAQ](#11-faq)

---

## 1. Core Concepts

### Incremental Puzzle Mode

Traditional lineage tools require importing all scripts at once. This project takes an **incremental puzzle** approach:

- Analyze one DML script at a time, auto-extract its lineage
- Results from multiple analyses **accumulate** into a global lineage graph — like assembling a puzzle, gradually reconstructing the full lineage
- After deleting a script, the global graph **auto-updates** (full-table scan cleans up orphan tables)

### Node Roles

| Concept | Color | Determination |
|---------|-------|---------------|
| **Source table** | 🟢 Green `#52c41a` | Only appears as the source end of an edge |
| **Intermediate table** | 🟡 Yellow `#faad14` | Acts as both source and target (a temp table created by `CREATE` in a script) |
| **Target table** | 🔵 Blue `#1890ff` | Only appears as the target end of an edge |

### Lineage Levels

| Level | Description |
|-------|-------------|
| **Table-level lineage** | Source table → target table data flow, shown as directed arrows (always generated as the base layer) |
| **Column-level lineage** | Target column ← source column mapping + transform expression (enhancement layer; click an edge to view) |

> Column-level is an enhancement layer: parse failures/degradation (e.g. `SELECT *`) do not affect table-level edges.

### Analysis Modes

| Mode | Description |
|------|-------------|
| **Offline mode (default)** | No database config; pure AST parsing extracts lineage, no database needed |
| **Online mode** | Fill in database config; additionally validates table existence and enriches column info |

> Lineage extraction is **unified on sqlglot AST static parsing** — deterministic and offline-capable. The database is only for validation and enrichment and **does not affect lineage results**. Online mode auto-degrades to offline mode on connection failure.

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                       Frontend (React + antd v6)                      │
│                                                                      │
│  Header: [Search] [Preprocess Rules] [Import/Export] [New Analysis]  │
│                                                                      │
│  ┌──────────┐  ┌──────────────────────────┐  ┌──────────────────┐   │
│  │ Script    │  │   Global / Script          │  │ Statement Panel  │   │
│  │ List      │  │   Lineage Graph            │  │ (right pane)     │   │
│  │ (left)    │  │   React Flow visualization │  │                  │   │
│  │          │  │   + Column Drawer + Search  │  │                  │   │
│  └──────────┘  └──────────────────────────┘  └──────────────────┘   │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ REST API (FastAPI, same-origin)
┌──────────────────────────────▼───────────────────────────────────────┐
│                     Backend Analyzer (FastAPI)                        │
│                                                                      │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌──────────────────────┐   │
│  │ Preprocess│ │ Statement │ │ Lineage    │ │  Store (persistence) │   │
│  │ + params  │ │ Splitter  │ │ Extractor  │ │  (file lock + JSONL  │   │
│  │           │ │           │ │ AST + col  │ │   + reverse index)   │   │
│  └──────────┘ └──────────┘ └───────────┘ └──────────────────────┘   │
│                                   │                  │               │
│                          ┌────────▼────────┐ ┌───────▼─────────┐    │
│                          │ sqlglot AST     │ │ data/            │    │
│                          │ (static, offline)│ │ ├── tables.json  │    │
│                          └────────┬────────┘ │ ├── edges.jsonl  │    │
│                                   │          │ ├── preprocess_r.│    │
│                          ┌────────▼────────┐ │ └── scripts/*.json│   │
│                          │ DB Validator    │ └─────────────────┘    │
│                          │ (optional)      │                        │
│                          └─────────────────┘                        │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                    PostgreSQL (optional, validation only)
```

**Four-layer architecture:**

| Layer | Responsibility |
|-------|----------------|
| **Frontend** | Three-pane layout + Header toolbar. Lineage graph rendered with React Flow |
| **Analyzer** | Preprocessing (incl. param substitution) → statement splitting → AST lineage extraction (table + column level) → optional DB validation |
| **Persistence (Store)** | JSON/JSONL file storage with file lock, `script_ids` reverse index, orphan-table cleanup |
| **Database (optional)** | Table structure validation and column enrichment; not involved in lineage extraction |

---

## 3. Core Workflow

### Analysis Flow

```
User submits a script
     │
     ▼
Step 1: Preprocess rules  → apply regex replacement rules (param mapping is a built-in type); ${param} replaced with actual values
     │
     ▼
Step 2: Preprocessing           → strip comments, collapse spaces, drop blank lines
     │
     ▼
Step 3: Statement splitting     → split on `;`, keep CREATE/INSERT/UPDATE/DELETE/MERGE
     │
     ▼
Step 4: AST lineage extraction  → table-level (source→target) + column-level (target col←source col + transform)
     │
     ▼
Step 5: DB validation (optional)→ table existence, column info enrichment
     │
     ▼
Step 6: Persistence             → save to JSON + update global graph (under file lock)
```

### Incremental Accumulation

**After analyzing a script:**
1. Script saved to `data/scripts/{script_id}.json`
2. Tables merged into `data/tables.json` (keyed by `schema.table`, with `script_ids` reverse index)
3. Edges appended to `data/edges.jsonl` (one per line, O(1) append)

**After deleting a script:**
1. Delete the script file
2. Rewrite `edges.jsonl`, removing that script's edges
3. **Full-table scan** of `tables.json`, remove the `script_id`; tables whose `script_ids` becomes empty are deleted (orphan cleanup)

> Orphan cleanup uses a full-table scan rather than "only edges' involved tables", because tables can be registered in `tables.json` from `database_info` or no-source lineages without appearing in edges (UPDATE with no source — the edge isn't written to `edges.jsonl`).

---

## 4. Feature Reference

### 4.1 Lineage Graph Interactions

| Action | Effect |
|--------|--------|
| Click a script (left pane) | Middle pane switches to that script's lineage graph; right pane shows its statements |
| Click "All" | Restore the global accumulated graph |
| Click a node | Expand/collapse full table name (long names are truncated; click to see full) |
| Click an edge | Open the column-level lineage drawer (target col ← source col + transform); single-edge highlight |
| Click a statement | All edges of that `seq` highlight in blue |
| Search box | Fuzzy-match table/column names; on select, focus + highlight |

**Highlight priority:** single edge (click edge) > impact analysis (upstream/downstream bi-color) > statement-level (click statement) > script-level > default (no highlight, static edges)

> **Edge animation:** by default all edges are static (no flowing animation) to keep large graphs smooth — only highlighted edges animate.

**Node style:** width auto-fits content (short names shrink, long names truncate + click to expand); expanded nodes glow with a white border.

**Layout:** toggle vertical (TB) / horizontal (LR) via the top-right button. Scroll to zoom, drag nodes, drag blank to pan, minimap at bottom-right.

### 4.2 Search Box (Header)

Supports **fuzzy matching of table and column names**:

1. Type a keyword (e.g. "order")
2. Dropdown shows all matching tables (● green dot) and columns (◆ diamond)
3. Select a table node → graph auto-focuses that node + white-border glow
4. Select a column → graph focuses the relevant edge + single-edge highlight + opens column drawer

Search scope auto-switches with the current view: global view searches the global graph; script view searches the current script.

### 4.3 Impact Analysis (Click a Node)

Click a node to trigger impact analysis, computed on an in-memory networkx graph:

- **Downstream** (who's affected if this table changes): orange `#fa8c16` highlights all downstream paths
- **Upstream** (where this table's data comes from): cyan `#13c2c2` highlights all upstream paths

> **Diamond dependencies fully covered:** when both `A→B→C` and `A→C` exist, clicking C uses `all_simple_paths` to return all paths, so the `A→B` middle edge is also highlighted (not skipped by shortest-path). Path explosion is guarded by three layers: `cutoff` depth limit + per-source path-count cap + cycle-degradation fallback.

### 4.4 Batch Import

Switch to "Batch Import Files" in the "New Analysis" dialog:

- Drag in multiple `.sql` files (browser multi-select) or a `.zip` containing multiple `.sql` files
- The zip is decompressed in the browser via fflate; all `.sql` files are extracted
- Each file produces an **independent script** (its own `analysis_id`, individually deletable/renamable)
- A partial failure of one file doesn't block others; failures are shown in the toast

### 4.5 Preprocess Rules

See [Section 6](#6-preprocess-rules).

### 4.6 Import / Export

| Action | Description |
|--------|-------------|
| Export | One-click export of all data (tables + edges + scripts + preprocess_rules) as a JSON file |
| Import | Overwrite all current data with an exported JSON (clears existing data; confirmation required) |

### 4.7 Graph Export

Export the current graph via the top-right buttons:
- **PNG**: screenshot of the current canvas (excludes controls/minimap)
- **HTML**: generate a standalone openable HTML file with the graph data embedded

### 4.8 Supported SQL Types

| Type | Example | Handling |
|------|---------|----------|
| `CREATE TABLE ... AS SELECT` | `CREATE TEMP TABLE tmp AS SELECT * FROM src;` | Kept (intermediate table) |
| `INSERT INTO ... SELECT` | `INSERT INTO tgt SELECT * FROM src;` | Kept |
| `UPDATE ... SET` | `UPDATE tgt SET col = val WHERE ...;` | Kept |
| `DELETE FROM` | `DELETE FROM tgt WHERE ...;` | Kept |
| `MERGE INTO` | `MERGE INTO tgt USING src ON ...;` | Kept |
| `ALTER TABLE` / `DROP TABLE` / `GRANT` | - | Filtered out (not lineage statements) |

**Preprocessing:** auto-removes comments (`--` single-line, `/* */` multi-line), collapses spaces, splits on `;`.

---

## 5. Lineage Extraction Capabilities

### 5.1 Table-level Lineage

| Statement type | Target table | Source tables | Rule |
|----------------|--------------|---------------|------|
| `CREATE [TEMP] TABLE t AS SELECT` | `t` | SELECT's FROM/JOIN | CTAS |
| `INSERT INTO t SELECT ...` | `t` | SELECT's FROM/JOIN | INSERT-SELECT |
| `UPDATE t SET ... FROM s` | `t` | FROM clause | PG extension |
| `DELETE FROM t USING s` | `t` | USING | PG extension |
| `MERGE INTO t USING src` | `t` | `src` | MERGE |

**Fully-qualified naming:** all tables use `schema.table` as the unique identity. Bare table names are prefixed with `public`. `public.orders` and `reporting.orders` are treated as two distinct nodes (eliminating cross-schema same-name conflicts).

### 5.2 Column-level Lineage

Standalone module `column_lineage.py`, decoupled from table-level. Capability matrix:

| Scenario | Capability |
|----------|------------|
| Explicit columns `INSERT INTO t(a,b) SELECT x,y` | ✅ Full mapping |
| JOIN + aliases `o.id, c.name` | ✅ Resolved to respective physical tables |
| Expression `price*qty` | ✅ Multi-source columns + transform |
| Aggregate `SUM(x)` | ✅ Source column + transform |
| CTAS | ✅ Supported |
| UPDATE SET | ✅ Left = target column; find source columns in right expression |
| Single table no alias `SELECT x FROM src` | ✅ Falls back to the only source table |
| Derived-table passthrough `FROM (SELECT...) sub` | ✅ Columns traced to physical tables |
| Nested subqueries | ✅ Recursively traced to the bottom level |
| JOIN + subquery mix | ✅ Each column traced to the correct physical table |
| `SELECT *` | ⚠️ Degrades to empty (table-level edge preserved) |

> **Derived-table passthrough:** when an outer SELECT references a derived table's output column, the parser recursively resolves the derived table's inner projection to trace back to physical source tables. Columns produced by aggregates/constants inside the derived table (e.g. `COUNT(*) AS cnt`) have no physical source and are not fabricated. This behavior is consistency-verified against sqllineage 1.5.8.

---

## 6. Preprocess Rules

SQL scripts in production come in all shapes: `${icl_schema}` template placeholders, special comments, ETL-tool-injected markers — built-in rules can hardly cover them all. This module unifies **parameter mapping** and **custom cleanup** into *regex replacement rules* that users can add/remove to handle any weird format.

Each rule runs `re.sub(pattern, replacement)` on the script text before parsing. Rule fields:

| Field | Description |
|-------|-------------|
| `name` | Rule name (e.g. "Strip line comments", "Param: icl_schema") |
| `pattern` | Python regex (first arg of `re.sub`; capture groups supported) |
| `replacement` | Replacement text, supports `$1` `$2` backreferences |
| `enabled` | Toggle; disabled rules are skipped during preprocessing |
| `builtin` | Built-in flag (param-mapping rules are `true`; shown blue in UI) |

**Parameter mapping** is now a built-in subtype of rule: each mapping entry corresponds to a rule with `id` prefixed `param-`, `builtin=true`, and `pattern` like `\$\{param_name\}`. Users can edit, disable, or delete them like any other rule.

### 6.1 Configuration

Click the "Preprocess Rules" button in the Header to manage the rule list:

- Click "Add Rule" to create a custom cleanup rule
- Each rule has name, regex, replacement text, and an enable toggle
- Built-in rules (param mappings) are marked blue
- Invalid regexes are highlighted red in the UI and filtered by the backend on save

Example rules:

| Name | pattern | replacement | Note |
|------|---------|-------------|------|
| Param: icl_schema | `\$\{icl_schema\}` | `ods` | built-in, replaces placeholder |
| Param: env | `\$\{env\}` | `prod` | built-in, replaces placeholder |
| Strip MySQL comments | `#[^\n]*` | (empty) | custom, cleans `#`-style comments |

### 6.2 Parameter substitution effect

Substitution behavior of param-mapping rules (when `enabled=true`):

| Placeholder | With rule | Without rule (fallback) |
|-------------|-----------|-------------------------|
| `${icl_schema}.orders` | `ods.orders` | `icl_schema.orders` (falls back to param name as identifier) |
| `${schema}_${env}.report` | `dw_prod.report` | `schema_env.report` |
| `WHERE dt = ${batch_date}` | `WHERE dt = <rule value>` | `WHERE dt = batch_date` (treated as column name; no lineage impact) |

> **Fallback**: even with no param rules configured, `${param}` is replaced with the param name itself (as a valid identifier) so lineage can still be extracted.

### 6.3 Execution pipeline

Preprocessing has two phases; rules only run in phase A:

```
Phase A (configurable) → Phase B (fixed core) → Fallback
  apply rules in order     strip comments/DO block/      ${param}→param name
  regex substitution       transaction semicolons/whitespace
```

Phase B (comment stripping, DO block extraction, transaction semicolons) is a prerequisite for splitter / sqlglot and is not exposed for toggling.

> **Note:** Preprocess rules take effect when **analyzing new scripts**. Existing scripts' nodes are not auto-updated; you must re-analyze to apply new rules.

---

## 7. API Reference

All endpoints are prefixed with `/api`. Swagger UI: `http://localhost:8000/docs`.

### Analysis

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/analyze` | POST | Submit a script for analysis (`database_config` optional; None = offline mode) |
| `/analyze-batch` | POST | Batch-analyze multiple files (each produces an independent script) |
| `/impact-analysis/{table}` | GET | Impact analysis (upstream/downstream/paths/cycles) |

### Script Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/scripts` | GET | Script list |
| `/scripts/{id}` | GET / DELETE | Script detail / delete |
| `/scripts/{id}/name` | PUT | Rename |
| `/scripts/{id}/statements` | GET | Statement segments |
| `/scripts/{id}/statements/{seq}` | PUT | Correct a statement's parse result |

### Global Data

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/global-graph` | GET | Global graph (with column_mappings) |
| `/tables` | GET | Global table registry |
| `/preprocess-rules` | GET / PUT | Preprocess rules (regex replacement rules; param mapping is a built-in type) |
| `/param-mapping` | GET / PUT | *(legacy, backward-compat alias of /preprocess-rules)* |
| `/export` | GET | Export all data |
| `/import` | POST | Import data (overwrites) |
| `/health` | GET | Health check |

---

## 8. Storage Design

### Directory Structure

```
backend/data/
├── tables.json          # Global table registry (schema.table as key, with script_ids reverse index)
├── edges.jsonl          # Global lineage edges (JSON Lines, append-only, with column_mappings)
├── preprocess_rules.json # Preprocess rules (regex replacement; param mapping is a built-in type)
├── store.lock           # File lock
└── scripts/
    └── {id}.json        # Each script's analysis result
```

### Concurrency & Consistency

| Mechanism | Description |
|-----------|-------------|
| **File lock** (filelock) | All writes are atomic under `store.lock` |
| **Append-only** | New edges append to the tail of `edges.jsonl`, O(1) |
| **Delete rewrite** | Deleting a script filters and rewrites `edges.jsonl` (low-frequency) |
| **script_ids full-table scan** | Orphan cleanup scans `tables.json`, removes the `script_id`, deletes tables whose set becomes empty |

### Backward Compatibility

The `column_mappings` field of `VisEdge` / `GlobalEdge` uses `Field(default_factory=list)`, so old data (without this field) deserializes to an empty array without errors.

**Param mapping auto-migration**: on first startup, if a legacy `param_mapping.json` is detected, it is automatically converted into builtin rules in `preprocess_rules.json` (each `{param: value}` becomes a rule with `id=param-{name}`, `pattern=\$\{name\}`, `builtin=true`). The old file is no longer used after migration. Importing a legacy export JSON (with `param_mapping` field but no `preprocess_rules`) also auto-converts.

---

## 9. Deployment

### 9.1 Development Mode

```bash
./ctl.sh start    # backend :8000 + frontend dev :5173
./ctl.sh stop
./ctl.sh restart
./ctl.sh status
```

### 9.2 All-in-One Deployment (Production)

After building the frontend, the backend serves both API and pages in a single process:

```bash
cd frontend && npm run build
cd ../backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Visit `http://localhost:8000` (single port; no frontend dev server needed). In dev mode (no build), static files are not mounted, so vite dev is unaffected.

### 9.3 Database Setup (Optional)

The database is **optional** — only needed for online validation:

```bash
docker run -d \
  --name lineage-pg \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=<your-password> \
  -e POSTGRES_DB=postgres \
  -p 5432:5432 \
  postgres:16

# Create test tables (optional)
docker exec -i lineage-pg psql -U postgres < backend/tests/init_test_tables.sql
```

> Offline mode doesn't need a database — just paste SQL and analyze.

### 9.4 Portable Edition (Zero Install)

**General users:** download `LineagePuzzle-vX.Y.Z-portable.zip` directly from [GitHub Releases](../../releases/latest), extract, and double-click `run.bat` — **no need to build it yourself**.

**Developers** (build the latest locally): use `pack_portable.bat` (must run on a dev machine **with internet** — it downloads embedded Python and installs deps):

```bash
pack_portable.bat    # produces dist-portable/ (~94 MB)
```

Copy the entire `dist-portable/` folder to the target machine, double-click `run.bat`, and open `http://localhost:8000`.

**The target machine needs nothing installed** (no Python, Node, or Docker). The portable edition bundles the Python 3.13.12 embeddable runtime + all dependencies.

Portable edition structure:

```
dist-portable/
├── python/              Embedded Python + all deps (do not modify)
├── app/                 Backend code (do not modify)
├── frontend/dist/       Frontend pages (do not modify)
└── run.bat              Launcher (double-click to run)
```

---

## 10. Example SQL Scripts

The examples below can be pasted directly into the "New Analysis" dialog. **Offline mode requires no database.**

### Example 1: Simple INSERT-SELECT (two-source JOIN)

```sql
INSERT INTO order_report (order_id, amount, customer_name)
SELECT o.id, o.amount, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id;
```

**Expected:** 3 nodes (orders/customers/order_report) + 2 edges. Click an edge for column-level: `order_id←orders.id`, `customer_name←customers.name`.

### Example 2: Temp table + column expression

```sql
CREATE TEMP TABLE tmp_order_detail AS
SELECT o.id AS order_id, o.amount, c.name AS customer_name
FROM orders o JOIN customers c ON o.customer_id = c.id;

INSERT INTO order_report (order_id, amount, customer_name)
SELECT order_id, amount * 1.1, customer_name FROM tmp_order_detail;
```

**Expected:** `tmp_order_detail` is a yellow intermediate table. The second edge's column-level shows `amount` with transform `amount * 1.1`.

### Example 3: With parameter placeholders

First add a param-mapping preprocess rule `${icl_schema}` → `ods` in "Preprocess Rules", then analyze:

```sql
INSERT INTO ${icl_schema}.summary (cust_id, total)
SELECT customer_id, SUM(amount) FROM ${icl_schema}.orders
WHERE dt = ${batch_date} GROUP BY customer_id;
```

**Expected:** nodes show `ods.summary` and `ods.orders` (params replaced).

### Example 4: Multi-layer temp table nesting

```sql
CREATE TEMP TABLE tmp_a AS SELECT * FROM src;
CREATE TEMP TABLE tmp_b AS SELECT * FROM tmp_a WHERE x > 0;
INSERT INTO report SELECT * FROM tmp_b;
```

**Expected:** forms a `src→tmp_a→tmp_b→report` chain; tmp_a/tmp_b are yellow intermediate tables.

### Example 5: Cross-schema same-name tables

```sql
INSERT INTO reporting.fact
SELECT a.x FROM public.orders a JOIN reporting.orders b ON a.id = b.id;
```

**Expected:** `public.orders` and `reporting.orders` are two independent nodes (no conflict).

### End-to-End Verification Flow

1. Submit the examples one by one; verify the global graph accumulates incrementally
2. Click an edge to view the column-level drawer
3. Click a node to view impact analysis (upstream/downstream bi-color highlight)
4. Use the search box to find table/column names; on select, focus
5. Delete a script; verify orphan-table cleanup via full-table scan
6. Refresh the page; verify data restores from JSON

---

## 11. FAQ

### Q: Can I use it without a database?

**Yes.** Offline mode (default) needs no database at all. Lineage extraction is based on SQL syntax parsing. The database is only needed if you want to validate table existence.

### Q: Database connection failed during analysis?

Database connection failure **auto-degrades to offline mode** and still returns lineage results. Check: is PostgreSQL running, are the port/credentials correct, any firewall issues.

### Q: No column-level lineage visible?

1. Confirm it's not `SELECT *` (cannot parse column-level; degrades to table-level)
2. Click an edge; the right drawer shows column mappings
3. "No column mappings" for `SELECT *` is normal (table-level lineage still works)

### Q: Parameter placeholder `${param}` errors?

sqlglot cannot parse `${param}` directly. Add a param-mapping rule in Header → "Preprocess Rules" (pattern auto-generated as `\$\{param_name\}`); it's auto-replaced during analysis. Even without a rule, the fallback replaces `${param}` with the param name as a valid identifier.

### Q: Residual nodes in the graph after deleting a script?

Fixed. Deleting a script does a full-table scan to clean up orphan tables. If residuals remain, refresh the page.

### Q: Table name too long to see fully?

Click the node to expand and show the full table name (no truncation limit). Click again to collapse.

### Q: Some edges not highlighted after clicking a node in impact analysis?

Fixed. After switching to `all_simple_paths`, all middle edges of diamond dependencies (A→B→C and A→C) are highlighted. If you see "too many paths, only partial highlighted", it means the path-count cap was triggered (only happens with pathological dense graphs).

### Q: Blank frontend page?

1. Confirm the backend is running (`http://localhost:8000/api/health` returns ok)
2. Check console errors via F12
3. Confirm the frontend is built (all-in-one mode requires `npm run build`)

### Q: How to view API docs?

`http://localhost:8000/docs` (Swagger UI).

### Q: How to use the portable edition?

Double-click `run.bat`, open :8000 in the browser, zero install. See [9.4 Portable Edition](#94-portable-edition-zero-install).

### Q: Where is data stored?

The `backend/data/` directory (tables.json / edges.jsonl / preprocess_rules.json / scripts/*.json). Backing up this directory backs up all analysis results. The portable edition uses `app/data/`.

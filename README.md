# LineagePuzzle

[![zread](https://img.shields.io/badge/Ask_Zread-_.svg?style=flat&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff)](https://zread.ai/BronyaEVE/LineagePuzzle)
[![Built with GLM-5.2](https://img.shields.io/badge/Built_with-GLM--5.2-3858F6?style=flat)](https://z.ai)

**English** | [简体中文](./README.zh-CN.md)

> A zero-dependency SQL data lineage visualization tool for air-gapped / on-premise environments — paste DML scripts, auto-generate table-level + column-level lineage graphs, and reconstruct the full data flow of your warehouse piece by piece.

![Global Lineage Graph](docs/images/hero.png)

---

## 🎯 Why This Project

Modern data platforms (Dataphin, WhaleOps, cloud DataWorks, etc.) and databases ship with built-in lineage analysis — but they all assume you have a **complete, connected, freshly-built big-data platform**. In reality, many teams are stuck with:

- **Legacy schedulers** — still running Control-M, Kettle, or in-house schedulers that only execute scripts and never record "where does this table's data actually come from?"
- **Piles of SQL scripts** — hundreds of warehouse ETL scripts where changing one table has unknown blast radius; whoever inherits the project reads SQL for three days to trace a single lineage path
- **Weak built-in lineage** — PostgreSQL's dependency views are table-level only, don't cover the full ETL chain, and have no visualization
- **Air-gapped networks** — heavy lineage platforms like Airflow / DataHub / OpenLineage need Kafka, K8s, a metadata DB — none of which can land in an isolated environment

**LineagePuzzle exists for this scenario**: a pocket-sized tool that fits on a USB stick and runs on double-click. It extracts lineage purely from SQL syntax analysis, needs no big-data platform, and works without a database connection. It brings the "standard-issue" lineage capability of advanced platforms to any intranet, in the lightest possible way.

## 👥 Who Is It For

- **Developers inheriting legacy projects** — facing undocumented ETL scripts, want to quickly figure out where data comes from, where it goes, and who is affected by changing a table
- **Air-gapped / isolated-network teams** — can't install heavy lineage platforms, need a zero-dependency, offline-capable lightweight solution
- **Warehouse developers / data governance** — want to incrementally map lineage at script granularity rather than bulk-importing an entire data dictionary

---

## ✨ Key Features

- **Incremental build** — analyze one script at a time, lineage auto-accumulates into a global graph; no need to submit all scripts at once
- **Offline-first** — static AST parsing via `sqlglot`, **no database connection required** to extract full lineage
- **Table-level + Column-level** — not just table flow, click an edge to see `target column ← source columns` and transform expressions (`SUM(amount)`, `price*qty`)
- **Impact analysis** — click a node to highlight all upstream (cyan) and downstream (orange) paths; diamond dependencies fully covered
- **Parameterized SQL** — supports ETL template placeholders like `${icl_schema}`, replaced via a global mapping table
- **Batch import** — drag in multiple `.sql` files or a `.zip` archive; each file becomes an independent script
- **Zero-install deployment** — portable edition bundles the Python runtime; just double-click on the target machine

---

## 🚀 Quick Start

Two paths depending on your environment:

### Option A: Download the Portable Package (air-gapped / general users, zero install)

> Best for: air-gapped environments, users who don't want to fiddle with Python/Node.

1. Download `LineagePuzzle-v1.0.0-portable.zip` (~33 MB) from the [Releases](../../releases/latest) page
2. Extract to any folder (avoid Chinese characters and spaces in the path)
3. Double-click `run.bat`
4. Open **http://localhost:8000** in your browser

**That's it.** The target machine needs no Python, Node, or Docker, and no internet. The portable package bundles Python 3.13 runtime and all dependencies. Copy the whole folder to a USB stick and run it on any intranet machine.

> Want colleagues to access it? `run.bat` listens on `0.0.0.0:8000` by default, so coworkers can reach it at `http://your-ip:8000`. Copy the `app/data/` folder to them and they'll see the same global graph.

### Option B: Build from Source (developers)

> Best for: developers who want to read/modify code or contribute PRs. Requires internet.

```bash
git clone https://github.com/BronyaEVE/LineagePuzzle.git
cd LineagePuzzle

# Install dependencies
cd backend && pip install -r requirements.txt
cd ../frontend && npm install

# Start (backend :8000 + frontend dev :5173)
cd .. && ./ctl.sh start
```

Open **http://localhost:5173**, click "New Analysis" in the top-right, and paste some SQL:

```sql
CREATE TEMP TABLE tmp_detail AS
SELECT o.id, o.amount, c.name FROM orders o JOIN customers c ON o.cid = c.id;

INSERT INTO order_report (order_id, amount, customer_name)
SELECT id, amount * 1.1, name FROM tmp_detail;
```

Click "Analyze Lineage" — you'll see the chain `orders`, `customers` (green) → `tmp_detail` (yellow) → `order_report` (blue). Click any edge to see the column-level mapping on the right.

**All-in-one deployment** (production, single port):

```bash
cd frontend && npm run build        # build frontend into dist/
cd ../backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** (single process serving both the page and the API).

> **No database required.** Lineage extraction relies purely on SQL syntax parsing; the database is only for optional table-existence validation.

---

## 🧩 Two Analysis Modes

| Mode | Use case | Description |
|------|----------|-------------|
| **Offline mode** (default) | No database | Pure AST parsing, just paste SQL; shows "Analysis complete (offline mode)" |
| **Online mode** | Has PostgreSQL | Expand "Advanced options" to fill in connection info; additionally validates table existence and enriches column info |

---

## 📖 Feature Overview

### Column-level lineage (click an edge)

Click any edge in the graph to open a drawer showing that edge's column mappings:

```
public.orders → public.order_report   Operation: INSERT   Statement #1

[order_id]      ← [public.orders.id]
[amount]        ← [public.orders.amount]      Transform: amount * 1.1
[customer_name] ← [public.customers.name]
```

Supports: explicit column mapping, JOIN + aliases, aggregates (`SUM`/`COUNT`), expressions (`price*qty`), CTAS, UPDATE SET, and **derived-table passthrough** (subquery columns traced back to physical tables). `SELECT *` degrades to table-level (edges still generated).

### Impact analysis (click a node)

Click a node to highlight **all** upstream/downstream paths (via `all_simple_paths`; diamond dependencies like `A→B→C` and `A→C` light up all three edges):

- 🔵 Downstream (who's affected if this table changes) — orange highlight
- 🔼 Upstream (where this table's data comes from) — cyan highlight

### Batch import

Switch to the "Batch Import" tab in the "New Analysis" dialog, drag in multiple `.sql` files or a `.zip` containing multiple `.sql` files; each file becomes an independent script.

### Others

- **Search box**: fuzzy-match table/column names; selecting one auto-focuses and highlights
- **Parameter mapping**: configure `${param}` → actual value, auto-replaced during analysis
- **Import/Export**: one-click backup/migration of all lineage data (JSON)
- **Graph export**: export the current graph as PNG / standalone HTML

> Full feature docs, architecture, and API reference in **[docs/PROJECT.md](docs/PROJECT.md)**.

---

## 🏗️ Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19 + TypeScript + antd v6 + React Flow (@xyflow/react v12) |
| Backend | Python FastAPI + Pydantic |
| SQL parsing | sqlglot (static AST analysis, sole lineage source) |
| Graph algorithms | networkx (shortest/all paths, cycle detection for impact analysis) |
| Storage | JSON / JSONL + filelock (no database dependency) |
| Deployment | Python embeddable (portable edition, zero install) |

---

## 📂 Project Structure

```
LineagePuzzle/
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI routes (16 REST endpoints)
│   │   ├── services/      # lineage extraction, storage, param substitution (core logic)
│   │   ├── models/        # Pydantic data models
│   │   └── main.py        # FastAPI app + static file hosting
│   ├── tests/             # 222 tests (94% coverage)
│   └── requirements.txt   # 9 core dependencies
├── frontend/
│   └── src/
│       ├── components/    # lineage graph, search box, batch import, etc.
│       ├── api/           # REST client
│       └── types/         # TypeScript type definitions
├── docs/
│   ├── PROJECT.md         # detailed project docs (architecture/API/advanced usage)
│   └── images/            # screenshots
├── ctl.sh                 # one-click start/stop script
└── pack_portable.bat      # portable edition build script
```

---

## 📊 Testing

```bash
cd backend && python -m pytest    # 222 passed, 94% coverage
```

---

## 📄 License

MIT

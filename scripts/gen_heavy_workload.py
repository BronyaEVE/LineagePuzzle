#!/usr/bin/env python3
"""
Generate synthetic SQL DML fixtures that simulate a heavy data-lineage workload.

Mimics the real banking-ETL topology (see CONTEXT.md / ADR-0001):
  - A shared pool of source tables in a source-layer schema, reused across many
    files (like ECIF / CBSD reference tables) — this is what makes dedup matter.
  - Each file creates several staging (_tmp) tables from multi-table JOINs of
    sources, then loads a final "fact" table — exactly the pattern that inflates
    node count and produces cross-product edges.
  - Cross-file references: the final step sometimes reads a fact table produced by
    an earlier file, so clean-layer tables become Intermediate (written by one
    file, read by another) — matching the dynamic role behavior in CONTEXT.md.

Output is clean PostgreSQL-dialect DML (parseable by sqlglot, unlike OCR'd input),
one .sql file per script — matching the app's batch-import format (.sql / .zip).

Usage:
  python scripts/gen_heavy_workload.py --preset heavy --out samples/heavy_workload --zip
  python scripts/gen_heavy_workload.py --files 150 --stmts-min 3 --stmts-max 6

The printed summary estimates distinct nodes, raw edges (pre-aggregation), and
unique (source,target) edge pairs (what the G6 renderer sees after aggregation).
"""
from __future__ import annotations

import argparse
import random
import zipfile
from pathlib import Path

# ---- Test-fixture names ---------------------------------------------------
# NOTE: these are fixture names for generated test data, NOT hardcoded into the
# tool itself. ADR-0001 (environment-neutrality) governs the tool's code, not
# its test fixtures.
DEFAULT_SOURCE_SCHEMAS = "edwiol_data"   # ODS / source layer
DEFAULT_CLEAN_SCHEMAS = "edwicl_data"    # clean / interface layer

DOMAINS = ["acct", "loan", "dep", "card", "txn", "cust", "org", "gl", "risk", "kpi"]
SOURCE_BASES = [
    "acct_base", "cust_info", "cust_org", "branch_dim", "prod_dim", "rate_ref",
    "grade_ref", "txn_log", "loan_mast", "dep_mast", "card_mast", "ccy_rate",
    "cal_dim", "acct_bal", "cust_label", "loan_dtl", "txn_acct", "dep_dtl",
    "card_txn", "org_dim", "emp_dim", "chanel_dim", "event_log", "acct_stat",
]
COLS = ["id", "custno", "acctno", "amt", "bal", "dt", "ccy", "status", "brch", "grade"]

PRESETS = {
    "small":   dict(files=30,  source_tables=20, stmts=(2, 4), srcs=(2, 5)),
    "medium":  dict(files=120, source_tables=40, stmts=(3, 6), srcs=(3, 7)),
    "heavy":   dict(files=300, source_tables=50, stmts=(4, 8), srcs=(3, 8)),
    "extreme": dict(files=600, source_tables=60, stmts=(5, 9), srcs=(4, 9)),
}


def dedupe(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def build_source_pool(rng, n, schemas):
    """n distinct source tables spread across the source-layer schema(s)."""
    pool = []
    for i in range(n):
        base = SOURCE_BASES[i % len(SOURCE_BASES)]
        sch = rng.choice(schemas)
        # disambiguate when the base name repeats
        name = base if i < len(SOURCE_BASES) else f"{base}_{i:02d}"
        pool.append(f"{sch}.{name}")
    return dedupe(pool)


def gen_select(refs):
    """Valid `SELECT ... FROM ... LEFT JOIN ...` over the referenced tables."""
    aliases = [chr(ord("a") + i) for i in range(len(refs))]
    cols = [f"{al}.{COLS[i % len(COLS)]}" for i, al in enumerate(aliases)]
    lines = [f"  SELECT {', '.join(cols)}", f"  FROM {refs[0]} AS {aliases[0]}"]
    for i in range(1, len(refs)):
        a0, ai = aliases[0], aliases[i]
        lines.append(f"  LEFT JOIN {refs[i]} AS {ai} ON {a0}.id = {ai}.id")
    return "\n".join(lines)


def gen_file(idx, rng, sources, clean_schema, prior_facts, stmts, srcs, cross_prob):
    """Generate one script's SQL + the (target, refs) list per statement."""
    domain = rng.choice(DOMAINS)
    nsteps = rng.randint(*stmts)
    sql_parts = []
    stmt_refs = []  # (target, [refs])
    prev = None

    # staging chain: stg1 <- sources; stg_j <- stg_{j-1} + more sources
    for step in range(1, nsteps):
        tgt = f"{clean_schema}.{domain}_stg{step}_tmp_{idx:04d}"
        refs = []
        if prev:
            refs.append(prev)
        refs += rng.sample(sources, min(rng.randint(*srcs), len(sources)))
        refs = dedupe(refs) or rng.sample(sources, 1)
        sql_parts.append(f"CREATE TABLE {tgt} AS\n{gen_select(refs)};")
        stmt_refs.append((tgt, refs))
        prev = tgt

    # final "fact" table: declare, then INSERT from last staging (+ optional cross-file)
    final = f"{clean_schema}.{domain}_fact_{idx:04d}"
    refs = [prev] if prev else rng.sample(sources, 1)
    if rng.random() < cross_prob and prior_facts:
        refs.append(rng.choice(prior_facts))
    refs = dedupe(refs)
    coldecl = ", ".join(f"{c} varchar(64)" for c in COLS[:8])
    sql_parts.append(f"CREATE TABLE {final} ({coldecl});")
    sql_parts.append(
        f"INSERT INTO {final} ({', '.join(COLS[:8])})\n{gen_select(refs)};"
    )
    stmt_refs.append((final, refs))
    return "\n\n".join(sql_parts) + "\n", final, stmt_refs


def main():
    ap = argparse.ArgumentParser(description="Generate heavy-workload SQL lineage fixtures.")
    ap.add_argument("--preset", choices=list(PRESETS), help="parameter preset")
    ap.add_argument("--files", type=int, help="number of .sql files (overrides preset)")
    ap.add_argument("--source-tables", type=int, help="shared source pool size")
    ap.add_argument("--stmts-min", type=int, help="min statements per file")
    ap.add_argument("--stmts-max", type=int, help="max statements per file")
    ap.add_argument("--srcs-min", type=int, help="min sources per statement")
    ap.add_argument("--srcs-max", type=int, help="max sources per statement")
    ap.add_argument("--cross-prob", type=float, default=0.15, help="prob a final reads an earlier fact")
    ap.add_argument("--source-schemas", default=DEFAULT_SOURCE_SCHEMAS)
    ap.add_argument("--clean-schemas", default=DEFAULT_CLEAN_SCHEMAS)
    ap.add_argument("--seed", type=int, default=20260813)
    ap.add_argument("--out", default="samples/heavy_workload")
    ap.add_argument("--zip", action="store_true", help="also write a single .zip for one-click import")
    args = ap.parse_args()

    cfg = dict(PRESETS[args.preset]) if args.preset else {}
    files = args.files if args.files is not None else cfg.get("files", 200)
    n_sources = args.source_tables if args.source_tables is not None else cfg.get("source_tables", 40)
    stmts = (
        args.stmts_min or cfg.get("stmts", (3, 6))[0],
        args.stmts_max or cfg.get("stmts", (3, 6))[1],
    )
    srcs = (
        args.srcs_min or cfg.get("srcs", (3, 7))[0],
        args.srcs_max or cfg.get("srcs", (3, 7))[1],
    )

    rng = random.Random(args.seed)
    source_schemas = [s.strip() for s in args.source_schemas.split(",") if s.strip()]
    clean_schemas = [s.strip() for s in args.clean_schemas.split(",") if s.strip()]
    sources = build_source_pool(rng, n_sources, source_schemas)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_nodes = set(sources)
    raw_edges = 0
    unique_edges = set()
    prior_facts = []

    for i in range(files):
        clean_schema = rng.choice(clean_schemas)
        sql, final, stmt_refs = gen_file(
            i, rng, sources, clean_schema, prior_facts, stmts, srcs, args.cross_prob
        )
        for target, refs in stmt_refs:
            all_nodes.add(target)
            for r in refs:
                raw_edges += 1
                unique_edges.add((r, target))
        prior_facts.append(final)
        (out_dir / f"file_{i:04d}.sql").write_text(sql, encoding="utf-8")

    # optional zip
    zip_path = None
    if args.zip:
        zip_path = out_dir.with_suffix(".zip") if out_dir.name else Path("heavy_workload.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for i in range(files):
                zf.write(out_dir / f"file_{i:04d}.sql", f"file_{i:04d}.sql")

    print("=" * 60)
    print(f"preset      : {args.preset or '(custom)'}")
    print(f"files       : {files}")
    print(f"source pool : {len(sources)} tables (shared, across {source_schemas})")
    print(f"stmts/file  : {stmts[0]}-{stmts[1]}")
    print(f"srcs/stmt   : {srcs[0]}-{srcs[1]}")
    print("-" * 60)
    print(f"distinct nodes       : {len(all_nodes)}")
    print(f"raw edges (pre-agg)  : {raw_edges}")
    print(f"unique edges (post-agg, what G6 sees): {len(unique_edges)}")
    print("-" * 60)
    print(f"output dir : {out_dir.resolve()}")
    if zip_path:
        print(f"output zip : {zip_path.resolve()}")
    print("=" * 60)
    print("Import via the app: 新建分析 → 批量导入文件 → pick the .zip or the .sql dir")


if __name__ == "__main__":
    main()

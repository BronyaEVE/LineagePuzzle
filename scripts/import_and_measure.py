#!/usr/bin/env python3
"""
Import a generated workload (a dir of .sql files) into the running backend via
/api/analyze-batch, then report parse timing and the resulting global-graph size.

Prerequisite: backend running (e.g. `uvicorn app.main:app --port 8000`).

Usage:
  python scripts/import_and_measure.py --dir samples/medium_workload
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
import urllib.error
from pathlib import Path


def post_json(url, payload, timeout=300):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_for_backend(base, tries=30):
    for _ in range(tries):
        try:
            get_json(f"{base}/api/global-graph", timeout=5)
            return True
        except Exception:
            time.sleep(1)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="dir of .sql files to import")
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--chunk-size", type=int, default=20)
    args = ap.parse_args()

    base = args.host.rstrip("/")
    if not wait_for_backend(base):
        raise SystemExit("backend not reachable at " + base)

    files = sorted(Path(args.dir).glob("*.sql"))
    if not files:
        raise SystemExit(f"no .sql files in {args.dir}")
    print(f"importing {len(files)} files from {args.dir} (chunk={args.chunk_size})")

    before = get_json(f"{base}/api/global-graph")
    print(f"  graph before: {len(before['nodes'])} nodes, {len(before['edges'])} edges")

    total_parse = 0.0
    imported = 0
    for start in range(0, len(files), args.chunk_size):
        chunk = files[start : start + args.chunk_size]
        payload_files = [
            {"name": f.name, "content": p.read_text(encoding="utf-8")}
            for f, p in [(f, f) for f in chunk]
        ]
        t0 = time.perf_counter()
        post_json(
            f"{base}/api/analyze-batch",
            {"files": payload_files, "database_config": None, "tags": []},
            timeout=600,
        )
        dt = time.perf_counter() - t0
        total_parse += dt
        imported += len(chunk)
        print(f"  [{imported:>4}/{len(files)}] parsed {len(chunk)} files in {dt:6.2f}s "
              f"({dt/len(chunk):.3f}s/file)")

    print(f"total parse time: {total_parse:.2f}s ({total_parse/len(files):.3f}s/file)")

    after = get_json(f"{base}/api/global-graph")
    print(f"graph after : {len(after['nodes'])} nodes, {len(after['edges'])} edges")
    print(
        f"added       : {len(after['nodes']) - len(before['nodes'])} nodes, "
        f"{len(after['edges']) - len(before['edges'])} edges"
    )


if __name__ == "__main__":
    main()

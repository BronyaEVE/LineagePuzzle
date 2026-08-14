# Security notes

LineagePuzzle is an offline-first LAN/local tool. This document records the threat
model and the security hardening applied in the 2026-08 maintenance pass.

## Threat model

| Mode | Binding | Exposure |
|---|---|---|
| Desktop (`desktop.py`) | 127.0.0.1 | local only |
| Portable (`run.bat` → `launcher.pyw`) | **0.0.0.0** | any LAN peer can reach all APIs |

The realistic threat surface is the portable/LAN mode: an unauthenticated peer on
the same network. Treat the deployment network accordingly (isolated lab/VPN).

## Hardening applied (2026-08)

| # | Fix | Where |
|---|---|---|
| 1 | **Path traversal in import**: `scripts` payload keys are validated (`^[A-Za-z0-9_-]+$`) before being used as filenames; invalid keys are skipped | `store.import_all` |
| 2 | **`</script>` injection in exported HTML**: embedded JSON escapes `</` so a crafted table name cannot break out of the script block | `LineageGraph.handleExportHtml` |
| 3 | **Payload caps**: script/file content ≤ 10 MB, batch ≤ 200 files, filenames ≤ 255 chars (pydantic-level rejection) | `schemas/requests.py` |
| 4 | **Error detail hygiene**: raw exception text (may contain DB host/user) is logged server-side only; responses carry generic messages | `api/analyze.py` |
| 5 | **debug=False by default** (tracebacks in responses disabled); enable with `LINEAGE_DEBUG=1` | `config.py` |
| 6 | **Optional API token** (`LINEAGE_TOKEN`): when set, all `/api/*` requests require `?token=` or `Authorization: Bearer`. The launcher auto-generates a per-run token and opens a tokenized URL; LAN peers find the share URL in `logs/launcher.log`. Opt out with `LINEAGE_TOKEN=off` (isolated single-machine use only) | `main.py` middleware, `launcher.pyw`, `client.ts` |
| 7 | **ReDoS partial guard**: preprocessing regex patterns capped at 200 chars (catastrophic patterns need long nesting) | `store.set_preprocess_rules` |

## Known accepted risks

- **ReDoS (partial)**: a short-but-pathological regex can still hang analysis;
  there is no re.sub timeout in the stdlib. Mitigation is the length cap; a
  process-pool timeout would be the full fix if this ever bites.
- **Plaintext HTTP on LAN**: the DB password in the analyze request and the API
  token itself travel unencrypted (sniffable on hostile LANs). Use an isolated
  network segment or a reverse proxy with TLS if this matters.
- **Exported HTML loads React Flow from jsdelivr CDN** at open time (needs
  internet; supply-chain trust in the CDN). The app itself has no such dependency.
- **Zip handling** (client-side `unzipSync`) has no size caps — a malicious zip
  only freezes the importer's own tab (self-DoS).

## Verified clean

- SQL injection: online mode uses bound parameters only (`db_connector.py`).
- Path traversal: all `script_id` entry points validated.
- In-app XSS: no `dangerouslySetInnerHTML` anywhere; React escapes by default.
- PyWebView desktop mode: no `js_api`, no debug flags, loopback-only.

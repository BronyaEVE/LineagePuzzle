# LineagePuzzle

A static SQL data-lineage visualizer for offline/isolated environments. This glossary fixes the vocabulary used across issues, code, and docs for the entities that make up a lineage graph.

## Roles

A table's **role is derived from the current global edge set and recomputed every time scripts are added** — it is never inferred from schema or name.

**Source**:
A table with out-edges only — no analyzed script writes to it (yet). Adding a script that writes into it turns it into a Target.
_Avoid_: origin, base table

**Target**:
A table with in-edges — at least one script writes to it. The persistent, business-meaningful output of a script.
_Avoid_: form table (informal usage only), sink, result table

**Intermediate**:
A table with both in- and out-edges — written to by one script and read by another.
_Avoid_: passthrough, bridge

## Foldable flag

**Staging**:
A derived flag on an Intermediate: a table created and consumed within a single script, used to transform or aggregate sources before they reach a Target. Foldable — collapsible into its downstream consumer. Always graph-derived, never schema-based.
_Avoid_: temp, temporary table

## Structural groupings

**Layer**:
A user-defined grouping of tables, configured at runtime in the web UI (typically by schema match or name pattern). Instances are per-environment config — never built into code or this doc. A soft prior for clustering only; never a determinant of Role.
_Avoid_: tier, zone

**Subsystem**:
A user-defined grouping of tables by business domain (e.g. accounts, customers), configured at runtime in the web UI by name pattern. Same rules as Layer: config, not code; a clustering aid, not a Role determinant.
_Avoid_: module, domain

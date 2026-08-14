# Environment-neutrality: no hardcoded schema or role assumptions

Status: accepted

The tool must work for any SQL warehouse, not just one organization's. We decided that **nothing environment-specific — schema names (e.g. source vs. clean layers), subsystem prefixes, or role assumptions — is hardcoded into parsing, classification, or rendering code.** Every structural grouping (Layer, Subsystem) is a rule the user configures at runtime in the web UI, and Role (Source / Target / Intermediate) is always recomputed from the global edge set. We rejected special-casing known schemas (e.g. treating particular schemas as always-Source) because it would make the tool single-environment and silently misclassify tables whose role differs from the schema's tendency.

**Considered options:** hardcoding known schema roles (rejected — non-portable, drifts as warehouses evolve); deriving role from schema (rejected — Role is a property of the accumulated graph, not of a table's location).

**Consequences:** a rule-engine plus web UI for grouping rules is required, adding config-engine complexity in exchange for generality. See `CONTEXT.md` for the canonical Role / Staging / Layer / Subsystem vocabulary this decision depends on.

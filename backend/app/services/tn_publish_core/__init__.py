"""Framework-agnostic publish pipeline: extract -> resolve -> validate -> assemble.

See `openspec/changes/tn-publisher-module/design.md` Decision 1. This PR
(PR-3) only ships `extract` (strict report-78 projection, PC1/S1) and
`resolve` (GBP-layer unit/dimension conversion, PC2/PC3). The public surface
(`build_draft`, `resolve_batch`, `execute_batch`) and the remaining
precedence/validate/assemble/batch stages land in PR-5.
"""

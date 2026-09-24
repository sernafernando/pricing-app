```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:2706ae77c0b1f036d794bc0cf620e55ed8d964f1a2337f07a65c3067a210bc6d
verdict: pass
blockers: 0
critical_findings: 0
requirements: 5/5
scenarios: 24/24
test_command: pytest tests/unit/test_oc_match_refresh_doc_refs.py tests/integration/test_oc_match_enqueue.py -q --tb=short && pnpm exec vitest run src/components/compras/_shared/DataTable.test.jsx src/components/compras/TabOcMatch.test.jsx src/hooks/useOcMatch.test.js
test_exit_code: 0
test_output_hash: sha256:faef4bb2724cc7c7aeada2f635bda1606beb690a978c00bd202d3d983fe4580c
build_command: ruff format --check app/services/oc_match/refresh_doc_refs.py app/services/oc_match/__init__.py app/routers/administracion_compras.py tests/unit/test_oc_match_refresh_doc_refs.py tests/integration/test_oc_match_enqueue.py && pnpm exec eslint src/components/compras/_shared/DataTable.jsx src/components/compras/_shared/DataTable.test.jsx src/components/compras/TabOcMatch.jsx src/components/compras/TabOcMatch.test.jsx src/hooks/useOcMatch.js src/hooks/useOcMatch.test.js
build_exit_code: 0
build_output_hash: sha256:41fea4986a4777f025675cd07c0f9f3efd43f52262ca3ed2a4e44397b8187d44
```

## Verification Report

**Change**: feat-compras-oc-match-inline-expand-doc-refresh
**Version**: N/A (delta specs; HEAD `feat/compras-oc-match-inline-expand-doc-refresh` @ 9cea7805 = `upstream/main`; feature work uncommitted)
**Mode**: Standard

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 15 |
| Tasks complete | 15 |
| Tasks incomplete | 0 |

Native heading counts across `openspec/changes/feat-compras-oc-match-inline-expand-doc-refresh/specs/`: **5** `### Requirement:` / **24** `#### Scenario:`. The fifth heading is the rename `Expand-below full-width job detail → Accordion expand under selected job row` (zero scenarios; covered by the accordion requirement).

### Build & Tests Execution
**Build**: ✅ Passed
```text
ruff format --check (5 Python files) → 5 files already formatted; RUFF_EXIT:0
pnpm exec eslint (6 FE files) → 0 errors / 0 warnings; ESLINT_EXIT:0
```

**Tests**: ✅ 61 passed / ❌ 0 failed / ⚠️ 0 skipped (24 pytest + 37 vitest)
```text
pytest tests/unit/test_oc_match_refresh_doc_refs.py tests/integration/test_oc_match_enqueue.py -q --tb=short
24 passed, 63 warnings in 7.12s; EXIT:0
(worktree backend has no .env; Settings loaded from /home/user/proyectos/pricing-app/backend/.env via dotenv, no ENVIRONMENT=testing override)

pnpm exec vitest run src/components/compras/_shared/DataTable.test.jsx src/components/compras/TabOcMatch.test.jsx src/hooks/useOcMatch.test.js
Test Files  3 passed (3); Tests  37 passed (37); Duration 3.35s; EXIT:0
```

**Coverage**: ➖ Not available / threshold: N/A → ➖ Not available

### Spec Compliance Matrix
| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Dedicated Factura/s and Pedido/s refresh action | Button shown for done plus gestionar | `TabOcMatch.test.jsx > shows dedicated button for done plus gestionar` | ✅ COMPLIANT |
| Dedicated Factura/s and Pedido/s refresh action | Error keeps Retry plus checkbox | `TabOcMatch.test.jsx > error keeps Retry plus checkbox and shows dedicated button` | ✅ COMPLIANT |
| Dedicated Factura/s and Pedido/s refresh action | View-only hides refresh button | `TabOcMatch.test.jsx > hides dedicated button for view-only` | ✅ COMPLIANT |
| Dedicated Factura/s and Pedido/s refresh action | Hidden on queued running skipped | `TabOcMatch.test.jsx > hides dedicated button on %s` (`queued`/`running`/`skipped`) | ✅ COMPLIANT |
| Dedicated Factura/s and Pedido/s refresh action | Click enqueues without rematch spinner | `TabOcMatch.test.jsx > click enqueues and shows non-blocking banner` + `useOcMatch.test.js > does not poll done or error after refreshDocRefs` | ✅ COMPLIANT |
| Accordion expand under selected job row | Selected job expands under its row | `TabOcMatch.test.jsx > expands detail under the selected row, not as aside or modal` + `DataTable.test.jsx > renders colspan expand under the matching row only` | ✅ COMPLIANT |
| Accordion expand under selected job row | Same-row click toggles collapse | `TabOcMatch.test.jsx > same-row click toggles collapse` | ✅ COMPLIANT |
| Accordion expand under selected job row | Other row moves the expand | `TabOcMatch.test.jsx > other row moves the expand` | ✅ COMPLIANT |
| Accordion expand under selected job row | Detail is not below the whole list | `TabOcMatch.test.jsx > expands detail under the selected row` (heading inside list `table` expand `tr`; pagination sibling after table) | ✅ COMPLIANT |
| Accordion expand under selected job row | Side pane and modal are not used | `TabOcMatch.test.jsx > expands detail under the selected row` (`aside` and `[role=dialog]` null) | ✅ COMPLIANT |
| Accordion expand under selected job row | Other tables unchanged when expand omitted | `DataTable.test.jsx > omitted expand props leave markup unchanged` | ✅ COMPLIANT |
| Dedicated refresh-doc-refs endpoint | Done job accepted immediately | `test_oc_match_enqueue.py > TestRefreshDocRefsEndpoint.test_done_accepted_status_unchanged` | ✅ COMPLIANT |
| Dedicated refresh-doc-refs endpoint | Error job accepted and stays error | `test_oc_match_enqueue.py > test_error_accepted_stays_error` | ✅ COMPLIANT |
| Dedicated refresh-doc-refs endpoint | 409 when queued running or skipped | `test_oc_match_enqueue.py > test_409_when_queued_running_or_skipped` | ✅ COMPLIANT |
| Dedicated refresh-doc-refs endpoint | 409 unless done or error after reclaim | same 409 matrix after endpoint `reclaim_stale_running` | ✅ COMPLIANT |
| Dedicated refresh-doc-refs endpoint | Missing gestionar is 403 | `test_oc_match_enqueue.py > test_view_only_403` | ✅ COMPLIANT |
| Dedicated refresh-doc-refs endpoint | Does not rematch or mutate artifacts | 200/409 cases assert `add_task` is `refresh_doc_refs_job` (or empty); acta / renglones / `excel_rel_path` unchanged | ✅ COMPLIANT |
| Extract-only doc-refs refresh persist | Successful extract clears stamp then write-back | `test_oc_match_refresh_doc_refs.py > test_success_clears_then_writeback_and_restamp` | ✅ COMPLIANT |
| Extract-only doc-refs refresh persist | Failed extract leaves stamp and pedido | `test_oc_match_refresh_doc_refs.py > test_failed_extract_keeps_stamp` | ✅ COMPLIANT |
| Extract-only doc-refs refresh persist | Status left done or error skips persist | `test_oc_match_refresh_doc_refs.py > test_skip_if_status_left` | ✅ COMPLIANT |
| Extract-only doc-refs refresh persist | No rematch excel or status mutation | unit `_assert_no_rematch_side_effects` + success/error status/`progress_phase`/acta/excel/renglones unchanged | ✅ COMPLIANT |
| Extract-only doc-refs refresh persist | Error job stays error after refresh | `test_oc_match_refresh_doc_refs.py > test_error_job_stays_error` | ✅ COMPLIANT |
| Extract-only doc-refs refresh persist | Never writes numero_factura | success / skip / error unit asserts `pedido.numero_factura == "ERP-KEEP"` | ✅ COMPLIANT |
| Extract-only doc-refs refresh persist | No alerts from refresh | unit patches `crear_notificaciones_para_permisos` and asserts not called | ✅ COMPLIANT |

**Compliance summary**: 24/24 scenarios compliant

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| Dedicated Factura/s and Pedido/s refresh action | ✅ Implemented | Button iff `done`\|`error` + gestionar; POST via `refreshDocRefs`; banner; Retry+checkbox kept; stamp not rendered |
| Accordion expand under selected job row | ✅ Implemented | List `DataTable` `expandedRowId` + `renderExpandedRow`; renglones omit expand; pagination after table |
| Expand-below full-width → Accordion under row | ✅ Implemented | Rename-only heading; same accordion contract |
| Dedicated refresh-doc-refs endpoint | ✅ Implemented | Empty POST; `gestionar`; reclaim+404; 409 unless `done`\|`error`; `add_task(refresh_doc_refs_job)`; never `queue_retry` |
| Extract-only doc-refs refresh persist | ✅ Implemented | Two-session `refresh_doc_refs_job`; clear stamp after extract before `apply_writeback`; no match/Excel/status flip |

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| Optional DataTable expand props default off | ✅ Yes | Both props required; omitted markup unchanged |
| Same-row click toggles collapse | ✅ Yes | `setSelectedId(null)` on re-click |
| Dedicated empty POST (not retry `mode`) | ✅ Yes | New route; retry handler untouched |
| HTTP 200 + BackgroundTasks; status unchanged | ✅ Yes | Returns `_oc_match_job_response` immediately |
| Persist job `FOR UPDATE`; skip if status left | ✅ Yes | `_persist_writeback` |
| Clear stamp after successful extract | ✅ Yes | `doc_refs_aplicado_at = None` immediately before write-back |
| FE banner; no Gemini spinner / no poll-as-running | ✅ Yes | `OC_MATCH_ACTIVE` stays `{queued, running}` |
| Do not expose stamp on detalle | ✅ Yes | `OcMatchJobResponse`/`Detalle` omit `doc_refs_aplicado_at` |
| Hover selector `tr:hover > td` | ✅ Yes | Apply-progress refinement; expand cell does not paint nested renglones |

### Issues Found
**CRITICAL**: None
**WARNING**: None
**SUGGESTION**: (1) Add a TabOcMatch vitest with `totalPages > 1` that asserts pagination is a sibling after the list table, not between the selected row and expand. (2) Worktree backend has no `.env`; DoD pytest needs the main-repo env file or a worktree `.env`.

### Verdict
PASS
15/15 tasks complete; 5/5 requirements and 24/24 scenarios have passing covering tests; design locks held; no rematch/Excel/status mutation on refresh-doc-refs.

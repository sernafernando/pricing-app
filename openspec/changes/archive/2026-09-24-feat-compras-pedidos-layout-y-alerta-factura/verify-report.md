```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:00ac3bc608dd6c60e2e92e9439e9026885e12947dfc0b1284e670bc32402dd38
verdict: pass
blockers: 0
critical_findings: 0
requirements: 5/5
scenarios: 10/10
test_command: pnpm --dir frontend exec vitest run src/components/compras/TabPedidosCompra.test.jsx && pnpm --dir frontend exec vitest run --project=visual src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx
test_exit_code: 0
test_output_hash: sha256:9c46acab31add6f5e8fec28186c906efb6adeab838bff5b2fc3dd94bc39472c0
build_command: pnpm --dir frontend exec eslint src/components/compras/TabPedidosCompra.jsx src/components/compras/TabPedidosCompra.test.jsx src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx
build_exit_code: 0
build_output_hash: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

## Verification Report

**Change**: feat-compras-pedidos-layout-y-alerta-factura
**Version**: N/A (delta specs; tip `feat/compras-pedidos-layout-y-alerta-factura` @ `0ab3f25bcd18fd4dd4b01f9c80d0293d2eb3c661`)
**Mode**: Standard

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 9 |
| Tasks complete | 9 |
| Tasks incomplete | 0 |

Native heading recount after Empresa rewrite across `openspec/changes/feat-compras-pedidos-layout-y-alerta-factura/specs/`: **5** `### Requirement:` / **10** `#### Scenario:` (`pedidos-compra` 3/5 + `compras-pipeline-alerts` 2/5). Empresa remains one requirement with two scenarios (Grupo Gauss two-line vs Pastoriza single-line). Attempt `verify-final` on tip `0ab3f25b` (Pastoriza = empresa width one line; Grupo Gauss only = two centered lines via `<br/>` + `.empresaCellGrupoGauss`). Do not archive. Do not open PR.

### Build & Tests Execution
**Build**: ✅ Passed
```text
pnpm --dir frontend exec eslint src/components/compras/TabPedidosCompra.jsx src/components/compras/TabPedidosCompra.test.jsx src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx
(no output); EXIT:0
```

**Tests**: ✅ 17 passed / ❌ 0 failed / ⚠️ 0 skipped (16 unit + 1 visual)
```text
pnpm --dir frontend exec vitest run src/components/compras/TabPedidosCompra.test.jsx
Test Files  1 passed (1); Tests  16 passed (16); Duration 3.46s; EXIT:0

pnpm --dir frontend exec vitest run --project=visual src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx
Test Files  1 passed (1); Tests  1 passed (1); Duration 2.39s; EXIT:0
```

**Coverage**: ➖ Not available / threshold: N/A → ➖ Not available

**Docs grep** (verify lock, not in `test_command`): `dispatch_factura_cargada_alerts` and `ver_alertas_factura` present in `docs/RUNBOOKS.md`, `docs/modulos/compras-guia-usuario.md`, `docs/modulos/compras-post-deploy-checklist.md`, and `frontend/src/novedades/2026-09-23-compras-pipeline-ux.md`. Guía states ADMIN role is not enough.

**Backend fire-path**: Design says re-run existing sweep/empty-nº tests only if Python changes. Task 3.4 skipped; Python untouched. Focused pytest from main-repo venv failed to import (`ModuleNotFoundError: google.genai`); not a product failure. Covering tests remain `test_compras_alertas_service.py` + `test_pedido_factura_documentos.py`. Source still: check sets `alerta_pendiente_hasta`; `dispatch_factura_cargada_alerts.py` calls `disparar_alertas_factura_pendientes`; `notificar_factura_cargada` returns `[]` on empty/whitespace `numero`.

### Spec Compliance Matrix
| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Empresa name is two-line centered without ellipsis | Grupo Gauss is fully visible on two centered lines | `tabPedidosCompraFechaPago.visual.test.jsx > shows full Empresa names, 2-col Acciones, and zero Proveedor/Mon overlap` (`data-wrap=grupo-gauss`, both words, center, no ellipsis) | ✅ COMPLIANT |
| Empresa name is two-line centered without ellipsis | Pastoriza is fully visible | same visual (`data-wrap=single`, `white-space:nowrap`, full `Pastoriza`, no ellipsis) | ✅ COMPLIANT |
| Acciones icons use a two-by-two grid | Four icons occupy two columns | unit `sizes Fecha pago to 110px...` Acciones `<col>` `< 180px` + visual two unique X columns / `display:grid` | ✅ COMPLIANT |
| Pedidos column budget fits 1280–1400 | No Proveedor/Mon collision at 1280–1400 | visual host `1360px`; Proveedor/Mon painted width > 0; overlap area 0 | ✅ COMPLIANT |
| Pedidos column budget fits 1280–1400 | Locked columns stay | unit `Fecha pago` `110px`, Estado `152px`, Proceso `220px`; source Mon `60px` unchanged | ✅ COMPLIANT |
| Factura-cargada fire requires deploy cron | Check alone does not notify | `test_fanout_holders_only_after_timer` (count 0 after check) + `test_patch_check_starts_pending_window` (`alerta_pendiente_hasta` = T0+5m) | ✅ COMPLIANT |
| Factura-cargada fire requires deploy cron | Cron sweep fires after the delay | `test_fanout_holders_only_after_timer` (holders after T_5) + `test_copy_contains_p_proveedor_factura_not_pedidos_documento` (supplier invoice `numero`) | ✅ COMPLIANT |
| Factura-cargada fire requires deploy cron | Empty invoice number stays a no-op | `test_empty_numero_creates_no_alert` (whitespace persist 422, no notif) + `notificar_factura_cargada` empty-nº `[]` | ✅ COMPLIANT |
| Ops docs state cron and ADMIN-alone is not enough | Runbook names the dispatch command | grep `docs/RUNBOOKS.md` §7: `python -m app.scripts.dispatch_factura_cargada_alerts`; cron required | ✅ COMPLIANT |
| Ops docs state cron and ADMIN-alone is not enough | Guía says ADMIN role is insufficient | grep `docs/modulos/compras-guia-usuario.md`: ADMIN no alcanza; names `administracion.ver_alertas_factura` | ✅ COMPLIANT |

**Compliance summary**: 10/10 scenarios compliant

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| Empresa name is two-line centered without ellipsis | ✅ Implemented | `COLUMNS.empresa` `104px` (Pastoriza + td pad). Default `.empresaCell` nowrap centered, `text-overflow: clip`. Only `/^grupo\s+gauss$/i` adds `.empresaCellGrupoGauss` + `Grupo<br/>Gauss`. |
| Acciones icons use a two-by-two grid | ✅ Implemented | `.rowActions { display:grid; grid-template-columns: repeat(2, min-content) }`; `COLUMNS.acciones` `104px`. |
| Pedidos column budget fits 1280–1400 | ✅ Implemented | Locked `110` / `60` / `152` / `220`; Proveedor has no width. Visual at 1360 overlap 0. |
| Factura-cargada fire requires deploy cron | ✅ Implemented | No Python change. Script + service already wired; empty nº no-op preserved. |
| Ops docs state cron and ADMIN-alone is not enough | ✅ Implemented | RUNBOOKS §7, post-deploy checkbox, guía, novedad. Chicho assigns; no DB assign instruction. |

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| Grupo Gauss = 2 centered lines; Pastoriza = 1 line; no ellipsis | ✅ Yes | Tip `0ab3f25b` `<br/>` + `.empresaCellGrupoGauss` only |
| Cap width to Pastoriza + td pad | ✅ Yes | `104px` |
| Acciones 2-col grid; width ~88–110px | ✅ Yes | `104px` grid |
| Keep 110 / 60 / 152 / 220 | ✅ Yes | COLUMNS unchanged for those keys |
| Proveedor uncapped | ✅ Yes | no width |
| Playwright at 1280–1400 not 1600 | ✅ Yes | host 1360 |
| DataTable untouched | ✅ Yes | cell CSS + COLUMNS only |
| Cron docs-only unless Python gap | ✅ Yes | 3.4 skipped |
| Recipients = `ver_alertas_factura`; ADMIN alone out | ✅ Yes | docs |

### Issues Found
**CRITICAL**: None
**WARNING**: None
**SUGGESTION**: `apply-progress.md` task 1.2 still says all-empresa 2-line wrap; tip `0ab3f25b` is Gauss-only. Unit test does not assert Mon `60px` (source-locked). Backend fire-path tests were not re-executed this session (no worktree venv; main venv missing `google.genai`); design says re-run only if Python changes.

### Verdict
PASS
5/5 requirements and 10/10 scenarios COMPLIANT after Empresa rewrite recount; 9/9 tasks complete; unit 16/16 + visual 1/1 at 1360 + eslint 0. Locks held: Pastoriza single-line, Grupo Gauss two-line centered, no ellipsis, Acciones 104px 2-col, Fecha pago 110, Proveedor/Mon overlap 0, cron documented. Do not archive. Do not open PR.

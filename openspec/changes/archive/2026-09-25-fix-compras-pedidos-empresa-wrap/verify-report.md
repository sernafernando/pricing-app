```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:c4b88d5ec5ac6314bbe39a1667b572faf51f1a495a338040df7414da249ebbd1
verdict: pass
blockers: 0
critical_findings: 0
requirements: 1/1
scenarios: 4/4
test_command: cd frontend && pnpm exec vitest run src/components/compras/TabPedidosCompra.test.jsx src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx
test_exit_code: 0
test_output_hash: sha256:00f8e59897b2b8c96bc8cec877e572228d5a5ee001496581cce6028851b9678f
build_command: pnpm --dir frontend exec eslint src/components/compras/TabPedidosCompra.jsx src/components/compras/TabPedidosCompra.test.jsx src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx
build_exit_code: 0
build_output_hash: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

## Verification Report

**Change**: fix-compras-pedidos-empresa-wrap
**Version**: N/A (delta spec; working tree on `feat/compras-pedidos-layout-y-alerta-factura` @ `94655bac` plus uncommitted apply)
**Mode**: Standard

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 4 |
| Tasks complete | 4 |
| Tasks incomplete | 0 |

Native heading recount in `openspec/changes/fix-compras-pedidos-empresa-wrap/specs/pedidos-compra/spec.md`: **1** `### Requirement:` / **4** `#### Scenario:`. Attempt `verify-final` (`verify-empresa-wrap-1`) against the uncommitted apply on tip `94655bac`. Do not archive. Do not commit. Do not push. Do not open a PR.

### Build & Tests Execution
**Build**: ✅ Passed
```text
pnpm --dir frontend exec eslint src/components/compras/TabPedidosCompra.jsx src/components/compras/TabPedidosCompra.test.jsx src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx
(no output); EXIT:0
```

**Tests**: ✅ 18 passed / ❌ 0 failed / ⚠️ 0 skipped (2 files; unit + visual/Chromium)
```text
cd frontend && pnpm exec vitest run src/components/compras/TabPedidosCompra.test.jsx src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx
RUN v4.1.9; Test Files 2 passed (2); Tests 18 passed (18); Duration 4.68s; EXIT:0
```

**Coverage**: ➖ Not available / threshold: N/A → ➖ Not available

### Spec Compliance Matrix
| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Empresa name is two-line centered without ellipsis | Two-word name wraps on the space | `tabPedidosCompraFechaPago.visual.test.jsx > clips Empresa at two generic lines...` (`Holding Norte` both words present, centered, height > 1 line, `scrollHeight <= clientHeight`) | ✅ COMPLIANT |
| Empresa name is two-line centered without ellipsis | Short name stays one line when it fits | same visual (`Acme` full text, height ≤ 1.2 line, no ellipsis) | ✅ COMPLIANT |
| Empresa name is two-line centered without ellipsis | Long name clips after two lines without overflowing | same visual (long fixture `scrollHeight > clientHeight`, height ≤ 2.5em, no ellipsis, Empresa/Proveedor overlap area 0) | ✅ COMPLIANT |
| Empresa name is two-line centered without ellipsis | Wrap rule is name-agnostic | `TabPedidosCompra.test.jsx > shows raw names with no br and no data-wrap` (two distinct raw names) + visual `assertLockedEmpresaStyle` on every cell (shared computed style; no `data-wrap`; no `<br>`) | ✅ COMPLIANT |

**Compliance summary**: 4/4 scenarios compliant

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| Empresa name is two-line centered without ellipsis | ✅ Implemented | `case 'empresa'` renders `empresa_nombre` (fallback `#id`) as a text child of `data-testid="empresa-cell"`. Single locked `.empresaCell` (`display:block`, `text-align:center`, `white-space:normal`, `overflow-wrap:anywhere`, `line-height:1.25`, `max-height:2.5em`, `overflow:hidden`). No `isGrupoGauss`, no `<br>`, no `data-wrap`, no `.empresaCellGrupoGauss`, no company names in JSX/CSS comments. `COLUMNS.empresa` remains `104px`; locked `110/60/152/220/104` unchanged. |

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| CSS-only wrap; delete regex/`<br>`/`.empresaCellGrupoGauss` | ✅ Yes | JSX is `{nombre}` only |
| Clip after 2.5em; no ellipsis | ✅ Yes | Locked rule + visual clip fixture |
| Do not touch `COLUMNS` | ✅ Yes | empresa `104px`; fecha_pago `110px`; moneda `60px`; estado `152px`; proceso `220px`; acciones `104px` |
| Remove `data-wrap`; visual uses computed style + geometry | ✅ Yes | Shared `assertLockedEmpresaStyle`; two-word / short / long fixtures |
| No company names in JSX or CSS comments | ✅ Yes | Grep clean on the four Pedidos files |
| jsdom proves name-agnostic text; visual proves geometry | ✅ Yes | Both layers passed this run |
| Do not retune Acciones or Fecha pago asserts | ✅ Yes | Existing Acciones 2-col and Fecha pago width asserts left in place |

### Issues Found
**CRITICAL**: None
**WARNING**: None
**SUGGESTION**: Apply left the four Pedidos files uncommitted on `feat/compras-pedidos-layout-y-alerta-factura` (follow-up commit on #1348 is out of this verify phase).

### Verdict
PASS
1/1 requirements and 4/4 scenarios COMPLIANT; 4/4 tasks complete; vitest 18/18 (unit + visual) + eslint 0. Generic two-line Empresa wrap/clip holds for every name; no name branch; no ellipsis; no Proveedor spill. Do not archive. Do not commit. Do not push. Do not open a PR.

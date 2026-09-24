```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:13f6a7ffceacc189619f0583fe56242204c41c963e626b2924f36506dc3f0475
verdict: fail
blockers: 1
critical_findings: 1
requirements: 0/1
scenarios: 1/3
test_command: pnpm --dir frontend exec vitest run src/components/compras/TabPedidosCompra.test.jsx
test_exit_code: 0
test_output_hash: sha256:cffdffec77709c84031fc23635748029fdad5dc1b92a0485d24e59516516cbfc
build_command: pnpm --dir frontend exec eslint src/components/compras/TabPedidosCompra.jsx src/components/compras/TabPedidosCompra.test.jsx
build_exit_code: 0
build_output_hash: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

## Verification Report

**Change**: fix-compras-pedidos-fecha-pago-col-width
**Version**: N/A (delta specs; tip `feat/compras-pedidos-fecha-pago-col-width` @ `33fbb1eb`)
**Mode**: Standard

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 3 |
| Tasks complete | 3 |
| Tasks incomplete | 0 |

Native heading counts across `openspec/changes/fix-compras-pedidos-fecha-pago-col-width/specs/`: **1** `### Requirement:` / **3** `#### Scenario:`.

### Build & Tests Execution
**Build**: ✅ Passed
```text
pnpm --dir frontend exec eslint src/components/compras/TabPedidosCompra.jsx src/components/compras/TabPedidosCompra.test.jsx
(no output); EXIT:0
```

**Tests**: ✅ 13 passed / ❌ 0 failed / ⚠️ 0 skipped
```text
pnpm --dir frontend exec vitest run src/components/compras/TabPedidosCompra.test.jsx
Test Files  1 passed (1); Tests  13 passed (13); Duration 3.36s; EXIT:0
```

**Coverage**: ➖ Not available / threshold: N/A → ➖ Not available

### Spec Compliance Matrix
| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Fecha pago column is date-sized | Fecha pago col is 110px | `TabPedidosCompra.test.jsx > sizes Fecha pago to 110px and leaves Estado/Proceso unchanged` | ✅ COMPLIANT |
| Fecha pago column is date-sized | Urgency badge may wrap under the date | (none found) | ❌ UNTESTED |
| Fecha pago column is date-sized | Proveedor and Mon. do not collide | `TabPedidosCompra.test.jsx > sizes Fecha pago to 110px and leaves Estado/Proceso unchanged` (col widths only; jsdom `css: false`) | ⚠️ PARTIAL |

**Compliance summary**: 1/3 scenarios compliant (1 PARTIAL, 1 UNTESTED, 0 FAILING)

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| Fecha pago column is date-sized | ⚠️ Implemented, not fully proven | `COLUMNS.fecha_pago.width` is `110px`; `estado` `152px`; `proceso` `220px`; `moneda` `60px`; Proveedor has no width. `.fechaPagoCell` keeps `flex-wrap: wrap`. Badge `margin-left: 0`. Fixture `PEDIDO_CON_NUMERO` is `aprobado` but has no `fecha_pago_estimada`, so the width test never renders `dd/mm/yyyy` or an urgency badge. DataTable untouched. |

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| Width `110px` not `100px` | ✅ Yes | `COLUMNS.fecha_pago.width` is `'110px'` |
| Keep badge wrap | ✅ Yes | `.fechaPagoCell { flex-wrap: wrap }` unchanged |
| Optional badge `margin-left: 0` | ✅ Yes | `.badgeVenceUrgente` / `.badgeVencido` |
| DataTable untouched | ✅ Yes | Shared padding/API not edited |
| Cheap `<col>` assert | ✅ Yes | Header index → `colgroup` style width |
| Do not expand Estado/Proceso | ✅ Yes | Still `152px` / `220px` |

### Issues Found
**CRITICAL**:
- Scenario `Urgency badge may wrap under the date` is UNTESTED. No passing test renders an `aprobado` pedido with `fecha_pago_estimada` within 7 days, asserts `dd/mm/yyyy`, or exercises the urgency badge. Source/CSS inspection is not runtime coverage.

**WARNING**:
- Scenario `Proveedor and Mon. do not collide` is PARTIAL. The col-width test renders `Proveedor Uno` + `ARS` and locks Fecha pago / Estado / Proceso widths, but jsdom `css: false` cannot prove painted non-overlap. Design/tasks left that visual check manual; no covering geometry test exists.

**SUGGESTION**:
- Add a cheap vitest that sets `fecha_pago_estimada` within 7 days, asserts the `dd/mm/yyyy` date text and badge (`Nd` / `Hoy` / `Vencido Nd`), and keeps the `<col>` at `110px`. Painted Proveedor/Mon. overlap still needs Chromium geometry or an amended spec if manual-only remains the lock.

### Verdict
FAIL
3/3 tasks complete and the designed col-width test passed (13/13), but the requirement is not independently proven: 1/3 scenarios COMPLIANT, 1 PARTIAL, 1 UNTESTED. Do not archive.

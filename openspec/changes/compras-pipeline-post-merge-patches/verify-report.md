```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:7b18b628e8a2e3f4d1934e00312fc066a357e32b3788ac479ca12db66582ae2b
verdict: pass_with_warnings
blockers: 0
critical_findings: 0
requirements: 12/12
scenarios: 35/35
test_command: ENVIRONMENT=testing PYTHONPATH=/home/user/.herdr/worktrees/pricing-app/feature-compras-ux/backend /home/user/.herdr/worktrees/pricing-app/feature-admin-ocs/backend/venv/bin/python -m pytest tests/unit/test_oc_match_doc_refs.py tests/unit/test_oc_match_pipeline.py tests/integration/test_oc_match_worker.py tests/unit/test_compras_alertas_service.py::TestFaltantes tests/unit/test_compras_alertas_service.py::TestSnoozeClock tests/unit/test_compras_alertas_service.py::TestOkSnoozeRoutes tests/unit/test_compras_alertas_service.py::TestResolucionG31 tests/integration/test_compras_endpoints.py::TestPedidosCRUD::test_listar_pedidos_excluir_estado_cancelado tests/integration/test_compras_endpoints.py::TestPedidosCRUD::test_listar_pedidos_estado_explicito_gana_sobre_excluir tests/integration/test_compras_endpoints.py::TestPedidosCRUD::test_listar_pedidos_estados_logisticos tests/integration/test_compras_endpoints.py::TestPedidosCRUD::test_listar_pedidos_estado_multivalor -q --tb=short && pnpm --dir frontend exec vitest run src/components/compras/TabPedidosCompra.test.jsx src/components/compras/TabRecepcionDeposito.test.jsx src/components/compras/ModalPedidoDetalle.test.jsx src/components/AppLayout.comprasBanners.test.jsx
test_exit_code: 0
test_output_hash: sha256:202bac637dd95520acea308befd1502982bd01672aec20cba661e1b8201c1a30
build_command: /home/user/.herdr/worktrees/pricing-app/feature-admin-ocs/backend/venv/bin/ruff format --check app/services/oc_match/doc_refs.py app/services/oc_match/extract.py app/services/oc_match/gemini_pool.py app/services/oc_match/match.py app/services/oc_match/worker.py app/routers/administracion_compras.py tests/unit/test_oc_match_doc_refs.py tests/unit/test_oc_match_pipeline.py tests/integration/test_oc_match_worker.py tests/integration/test_compras_endpoints.py && pnpm --dir frontend exec eslint src/components/compras/TabPedidosCompra.jsx src/components/compras/TabPedidosCompra.test.jsx src/components/compras/TabRecepcionDeposito.jsx src/components/compras/TabRecepcionDeposito.test.jsx src/components/compras/ModalPedidoDetalle.test.jsx src/components/AppLayout.jsx src/components/AppLayout.comprasBanners.test.jsx src/pages/AdministracionCompras.jsx src/hooks/useRecepcionDeposito.js
build_exit_code: 0
build_output_hash: sha256:f9f1d0c902c8d7bf9e17701e68fc12abdce593c01d60d45a470da331a54f30ed
```

## Verification Report

**Change**: compras-pipeline-post-merge-patches
**Version**: N/A (delta specs; tip `feat/compras-pipeline-post-merge-patches` @ `ae7252e8`)
**Mode**: Standard

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 20 |
| Tasks complete | 20 |
| Tasks incomplete | 0 |

Native heading counts across `openspec/changes/compras-pipeline-post-merge-patches/specs/`: **12** `### Requirement:` / **35** `#### Scenario:`. Tasks 1.1–5.3 checked (3.6 REMOVED). Phase 5 chips + Con faltantes overlap landed at `ae7252e8`.

### Build & Tests Execution
**Build**: ✅ Passed
```text
ruff format --check (10 Python files) → 10 files already formatted; EXIT:0
pnpm exec eslint (9 FE files) → 0 errors, 2 pre-existing react-hooks/exhaustive-deps warnings in AppLayout.jsx; EXIT:0
```

**Tests**: ✅ 146 passed / ❌ 0 failed / ⚠️ 0 skipped (59 pytest + 87 vitest)
```text
pytest (feature-admin-ocs 3.11 venv; ENVIRONMENT=testing): 59 passed, 24 warnings in 24.34s; EXIT:0
vitest: 4 files / 87 tests passed in 5.47s; EXIT:0
```

**Coverage**: ➖ Not available / threshold: N/A → ➖ Not available

### Spec Compliance Matrix
| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Pedidos default excludes only cancelado | Default hides cancelado only | `test_listar_pedidos_excluir_estado_cancelado` + `TabPedidosCompra.test.jsx` `excluir_estado=cancelado` | ✅ COMPLIANT |
| Pedidos default excludes only cancelado | Cancelado is selectable | `test_listar_pedidos_estado_explicito_gana_sobre_excluir` + dropdown includes `cancelado` | ✅ COMPLIANT |
| Pedidos default excludes only cancelado | Logistic estados are selectable | `test_listar_pedidos_estados_logisticos` + dropdown `recibido`/`con_faltantes`/`controlado` | ✅ COMPLIANT |
| Pedido query is consumed then cleared | Close clears query so remount does not reopen | `TabPedidosCompra.test.jsx` close clears leftover query | ✅ COMPLIANT |
| Pedido query is consumed then cleared | Tab change does not sticky-reopen | `TabPedidosCompra.test.jsx` user tab click strips pedido | ✅ COMPLIANT |
| Pedido query is consumed then cleared | Ver force-opens the same URL | `TabPedidosCompra.test.jsx` Ver `open=` nonce then consume | ✅ COMPLIANT |
| Proceso chips use semantic colors | Factura and Match error are not gray twins | `TabPedidosCompra.test.jsx` `data-tone=success` vs `danger` | ⚠️ PARTIAL |
| Proceso chips use semantic colors | OC chip is distinctly colored | same test `chip-oc` `data-tone=info` vs Número muted | ⚠️ PARTIAL |
| Con faltantes estado is not clipped by Proceso | Con faltantes badge stays readable beside Proceso | `estado-cell`/`proceso-cell` `data-layout=no-clip` + CSS overflow/z-index | ⚠️ PARTIAL |
| Pedido chips keep stored leading zeros | Leading zeros stay on the chip | `TabRecepcionDeposito.test.jsx` chip `00184465` | ✅ COMPLIANT |
| Pedido chips keep stored leading zeros | Multiple tokens keep each string | `TabRecepcionDeposito.test.jsx` `0012` + `PED-08` | ✅ COMPLIANT |
| Incluir cuenta corriente defaults on | Default includes cuenta corriente | `TabRecepcionDeposito.test.jsx` toggle checked + `pagado,en_cuenta_corriente` | ✅ COMPLIANT |
| Incluir cuenta corriente defaults on | Operator can turn the toggle off | same file uncheck → subsequent `pagado` only | ✅ COMPLIANT |
| Banner and Ver force-open pedido detalle | Banner force-opens if URL already has pedido | `AppLayout.comprasBanners.test.jsx` Ver from `?pedido=42` adds `open=` | ✅ COMPLIANT |
| Banner and Ver force-open pedido detalle | Close or tab change does not stale-reopen | `TabPedidosCompra.test.jsx` close + tab-strip | ✅ COMPLIANT |
| Banner and Ver force-open pedido detalle | Inbound land still opens once | `TabPedidosCompra.test.jsx` inbound `?pedido=` opens then consumes | ✅ COMPLIANT |
| Factura banner Ver and X dismiss permanently | Ver on factura banner dismisses permanently | `AppLayout.comprasBanners.test.jsx` Ver → `PATCH .../ok` then navigate | ✅ COMPLIANT |
| Factura banner Ver and X dismiss permanently | X on factura banner dismisses permanently | same file Cerrar alerta → `PATCH .../ok` | ✅ COMPLIANT |
| Faltantes banner closable with X (snooze) | Faltantes shows X and X snoozes | `AppLayout.comprasBanners.test.jsx` Cerrar alerta → `/snooze`; `test_hide_until_mark_plus_one_hour` | ✅ COMPLIANT |
| Faltantes banner closable with X (snooze) | Faltantes Ver navigates without dismiss | `AppLayout.comprasBanners.test.jsx` Ver no `/ok`/snooze | ✅ COMPLIANT |
| Faltantes banner closable with X (snooze) | Faltantes permanent clear stays on resolution | `test_retractar_faltantes_clears_alert` + `ModalPedidoDetalle.test.jsx` resolver texto | ✅ COMPLIANT |
| Extract tipo_documento and pass it through | Factura extract includes tipo | `test_acta_includes_tipo_documento_line` + GOLDEN_EXTRACT worker path | ✅ COMPLIANT |
| Extract tipo_documento and pass it through | Alias and unknown normalize | `test_nv_alias_and_null_unknown` | ✅ COMPLIANT |
| Extract tipo_documento and pass it through | NC and ND normalize as non-factura | `test_nc_nd_aliases` | ✅ COMPLIANT |
| Extract tipo_documento and pass it through | Leading zeros survive extract | `test_quote_leading_zero_pedido_token` + `test_stringify_keeps_leading_zeros` + `test_match_passes_nro_pedido_as_string` | ✅ COMPLIANT |
| Route extracted numbers onto PedidoCompra | Factura routes both numbers | `test_factura_routes_both_columns` | ✅ COMPLIANT |
| Route extracted numbers onto PedidoCompra | Proforma writes only Pedido/s | `test_proforma_writes_only_pedidos` | ✅ COMPLIANT |
| Route extracted numbers onto PedidoCompra | Payment receipt skips write-back | `test_skip_comprobante_pago_and_otro` + `test_skip_tipo_does_not_stamp` | ✅ COMPLIANT |
| Route extracted numbers onto PedidoCompra | Excel error still writes; missing extract does not | `test_usd_sin_tc_is_error_without_xlsx_success` + `test_unmapped_empresa_errors_without_gemini` | ✅ COMPLIANT |
| Route extracted numbers onto PedidoCompra | Stamped persist skips write-back | `test_stamped_persist_skips_writeback` | ✅ COMPLIANT |
| Route extracted numbers onto PedidoCompra | Routeable write stamps the job | worker stamp after write-back + `test_stale_claim_persist_does_not_overwrite` | ✅ COMPLIANT |
| Route extracted numbers onto PedidoCompra | NC and ND skip write-back and factura persist | `test_nc_nd_skip_writeback` + `test_nc_nd_skip_writeback_stamp_and_factura_row` | ✅ COMPLIANT |
| OC-match MUST NOT create factura rows from NC/ND | NC does not create a factura row | `test_nc_nd_skip_writeback_stamp_and_factura_row` (`nota_credito`) | ✅ COMPLIANT |
| OC-match MUST NOT create factura rows from NC/ND | ND does not create a factura row | same parametrize (`nota_debito`) | ✅ COMPLIANT |
| OC-match MUST NOT create factura rows from NC/ND | Factura persist still creates constancia | `test_factura_fa10_persists_row_chip_off_no_notif` `cargada is False` | ✅ COMPLIANT |

**Compliance summary**: 32/35 COMPLIANT, 3/35 PARTIAL, 0 UNTESTED, 0 FAILING

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| Pedidos default excludes only cancelado | ✅ Implemented | FE empty select → `excluir_estado=cancelado`; BE `~estado.in_()` only when `estado` is None |
| Pedido query is consumed then cleared | ✅ Implemented | `stripPedidoQueryParams` / consume / `open` nonce on Ver |
| Proceso chips use semantic colors | ✅ Implemented | OC info, Factura success, Match error danger, other Match warning, ejes stronger, Número muted; CF tokens |
| Con faltantes estado is not clipped by Proceso | ✅ Implemented | `.estadoCell` z-index 1 + overflow visible; `.procesoCell` z-index 0 |
| Pedido chips keep stored leading zeros | ✅ Implemented | split `;`, render stored string, no `Number()` |
| Incluir cuenta corriente defaults on | ✅ Implemented | `useState(true)`; Por recibir requests `pagado,en_cuenta_corriente` |
| Banner and Ver force-open | ✅ Implemented | `deepLinkForCompras` appends `open=` nonce |
| Factura banner Ver and X permanent | ✅ Implemented | Ver and X → `PATCH /ok` |
| Faltantes X snooze, Ver navigate-only | ✅ Implemented | dismissible; X/onDismiss → snooze; Ver no `/ok` |
| Extract tipo + string tokens | ✅ Implemented | enum + aliases + `quote_numeric_doc_fields` + stringify; no `int()` |
| Route extracted numbers | ✅ Implemented | `TIPOS_ROUTEABLE` unchanged; NC/ND known not routeable; no stamp |
| OC-match no NC/ND factura rows | ✅ Implemented | worker skips `persist_factura_documento` for NC/ND |

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| Triple NC/ND gate (prompt + normalize + persist skip) | ✅ Yes | `TIPOS_CONOCIDOS` + aliases; `TIPOS_ROUTEABLE` unchanged |
| Quote lexeme then stringify; never `int()`/`Number()` | ✅ Yes | extract + match + Depósito chips |
| `excluir_estado` optional; explicit `estado=` wins | ✅ Yes | |
| Factura Ver+X `/ok`; faltantes X snooze; Ver navigate only | ✅ Yes | |
| Consume-or-clear + `open=` nonce | ✅ Yes | |
| Incluir CC `useState(true)` | ✅ Yes | |
| Chip CSS variants + tokens | ✅ Yes | no hardcoded hex in chip classes |
| Estado vs Proceso overflow/stack | ✅ Yes | |
| No `TabOcMatch.*` / expand-below / Alembic / 5m sweep / CAS | ✅ Yes | locks held |
| Task 3.6 checkbox rebind dropped | ✅ Yes | `ModalPedidoDetalle` cargada binding unchanged |

### Issues Found
**CRITICAL**: None
**WARNING**: (1) Phase 5 chip-color and Con faltantes overlap scenarios are proven via `data-tone` / `data-layout` (vitest `css:false`), not computed styles or pixel overlap. (2) AppLayout eslint `react-hooks/exhaustive-deps` warnings on `user` are pre-existing. (3) Residual design risk: Gemini may still emit `tipo_documento=factura` for an NC; persist cannot see the paper. (4) TabPedidosCompra / AppLayout remain god-components with `ponytail:` + ledger (out of scope).
**SUGGESTION**: Optional visual snapshot or computed-style assertion if css-enabled vitest is added later.

### Verdict
PASS WITH WARNINGS
All 20 tasks done at tip `ae7252e8`; 12/12 requirements implemented; 32/35 scenarios fully covered at runtime and 3 partial (jsdom chip/overlap); focused pytest 59 + vitest 87 passed; locks held. Do not archive unless asked.

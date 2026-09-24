```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:c177d29eac2d1898d6afa7a89dd5168ff8036ab01a71141279847b2c2b2e89eb
verdict: pass_with_warnings
blockers: 0
critical_findings: 0
requirements: 30/30
scenarios: 67/67
test_command: pytest tests/unit/test_pedido_factura_documentos.py tests/unit/test_eje_procesal.py tests/unit/test_compras_alertas_service.py tests/integration/test_recepcion_deposito_endpoints.py tests/integration/test_vincular_oc_multi.py tests/integration/test_oc_vincular_s1_endpoints.py -q --tb=line && pnpm exec vitest run --project=unit src/components/compras/TabRecepcionDeposito.test.jsx src/components/compras/ModalVincularOC.test.jsx src/components/AppLayout.comprasBanners.test.jsx
test_exit_code: 0
test_output_hash: sha256:0cd402578636f63d3f78d6804bf8f9f78c4b9317b669c5e6dbf5a9e9673bce61
build_command: ruff format --check app/services/compras_alertas_service.py app/services/pedidos_service.py app/services/recepcion_service.py app/models/pedido_factura_documento.py app/models/pedido_compra_oc.py app/models/pedido_compra.py app/schemas/pedido_compra.py app/schemas/orden_pago.py app/schemas/recepcion.py app/routers/administracion_compras.py app/api/endpoints/notificaciones.py && pnpm exec eslint src/components/AppLayout.jsx src/components/compras/TabRecepcionDeposito.jsx src/components/compras/ModalVincularOC.jsx src/components/compras/TabPedidosCompra.jsx src/components/compras/TabOrdenesPago.jsx src/components/compras/ModalPedidoDetalle.jsx src/hooks/useRecepcionDeposito.js
build_exit_code: 0
build_output_hash: sha256:e417753a2bed7b7340b73ebbae0f78f8b85a5dfd64ac3b0252b628068d97de28
```

## Verification Report

**Change**: compras-ops-pipeline-ux
**Version**: N/A (change specs; no published spec version)
**Mode**: Standard

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 22 |
| Tasks complete | 22 |
| Tasks incomplete | 0 |

Native heading counts across `openspec/changes/compras-ops-pipeline-ux/specs/`: **30** `### Requirement:` / **67** `#### Scenario:`.

### Build & Tests Execution
**Build**: ✅ Passed
```text
ruff format --check (11 Python files) → 11 files already formatted; EXIT:0
pnpm exec eslint (7 FE files) → 0 errors, 2 pre-existing react-hooks/exhaustive-deps warnings in AppLayout.jsx; EXIT:0
```

**Tests**: ✅ 212 passed / ❌ 0 failed / ⚠️ 0 skipped (167 pytest + 45 vitest)
```text
pytest (admin-ocs venv; dummy Settings DATABASE_URL/SECRET_KEY/ERP_BASE_URL; ENVIRONMENT=testing):
167 passed, 210 warnings in 46.96s; EXIT:0
Files: test_pedido_factura_documentos.py, test_eje_procesal.py, test_compras_alertas_service.py,
       test_recepcion_deposito_endpoints.py, test_vincular_oc_multi.py, test_oc_vincular_s1_endpoints.py

vitest --project=unit:
Test Files 3 passed; Tests 45 passed; Duration 3.41s; EXIT:0
Files: TabRecepcionDeposito.test.jsx, ModalVincularOC.test.jsx, AppLayout.comprasBanners.test.jsx
```

**Coverage**: ➖ Not available / threshold: N/A → ➖ Not available

### Hard locks
| Lock | Result | Evidence |
|------|--------|----------|
| Alerts channel in-app only | ✅ Held | `compras_alertas_service.py` has no email/Slack send path; `test_no_email_or_slack_on_factura` SMTP uncalled; AppLayout stacks `compras.*` banners; guide §3.1 |
| ERP multi-factura / ModalVincularFactura / ct_transaction untouched | ✅ Held | `test_erp_link_without_rows_is_not_cargada`; `git diff upstream/main...HEAD` does not include `ModalVincularFactura*`; new identity is `pedido_factura_documentos` rows |
| Financial badge `aprobado` not renamed by this change | ✅ Held | `test_aprobado_is_not_procesal_pendiente`; estado code stays `aprobado`; `EstadoBadge` `aprobado→Pendiente` label is pre-existing (`596714dc`, 0 diff vs `upstream/main`) |

### Spec Compliance Matrix
| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Normalized factura rows | Row makes factura cargada | `test_pedido_factura_documentos.py > test_row_makes_factura_cargada` | ✅ COMPLIANT |
| Normalized factura rows | ERP multi-link is not cargada | `test_pedido_factura_documentos.py > test_erp_link_without_rows_is_not_cargada` | ✅ COMPLIANT |
| Seed from facturas_documento | Semicolon tokens become rows | `test_pedido_factura_documentos.py > test_semicolon_tokens_become_three_rows` | ✅ COMPLIANT |
| Seed from facturas_documento | Empty token field seeds nothing | `test_pedido_factura_documentos.py > test_empty_or_separator_only_seeds_nothing` | ✅ COMPLIANT |
| Nonempty document number | Empty number rejected | `test_pedido_factura_documentos.py > test_empty_number_422_no_row_no_alert` | ✅ COMPLIANT |
| Five-minute undo | Undo inside five minutes | `test_pedido_factura_documentos.py > test_undo_inside_five_minutes_204` + `test_compras_alertas_service.py > test_undo_retracts_factura_notifs` | ✅ COMPLIANT |
| Five-minute undo | Undo after five minutes rejected | `test_pedido_factura_documentos.py > test_undo_after_five_minutes_409` | ✅ COMPLIANT |
| In-app channel only | Banner and campanita together | `AppLayout.comprasBanners.test.jsx` + `test_no_email_or_slack_on_factura` (TopBar/bell mocked) | ⚠️ PARTIAL |
| Alert copy uses P-number | Factura alert copy | `test_compras_alertas_service.py > test_copy_contains_p_proveedor_factura_not_pedidos_documento` | ✅ COMPLIANT |
| Factura recipients and per-user OK | Fan-out to union | `test_compras_alertas_service.py > test_fanout_union_and_outsider_excluded` | ✅ COMPLIANT |
| Factura recipients and per-user OK | Per-user OK does not clear others | `test_compras_alertas_service.py > test_ok_clears_only_that_user` | ✅ COMPLIANT |
| Faltantes alert to responsable | Responsable notified with free text | `test_compras_alertas_service.py > test_responsable_notified_with_free_text` | ✅ COMPLIANT |
| Faltantes alert to responsable | Faltantes without free text rejected | `test_compras_alertas_service.py > test_empty_texto_422_no_alert` | ✅ COMPLIANT |
| Faltantes snooze one hour | Snooze until mark plus one hour | `test_compras_alertas_service.py > test_hide_until_mark_plus_one_hour` (API list, not banner/bell UI) | ⚠️ PARTIAL |
| Faltantes resolution notifies depósito | All depósito receivers notified | `test_compras_alertas_service.py > test_deposito_receivers_only` | ✅ COMPLIANT |
| OPs column lists P-numbers | Multiple linked pedidos appear | `test_eje_procesal.py > test_two_p_numbers_and_a_cuenta_empty` (batch DTO; no TabOrdenesPago RTL) | ⚠️ PARTIAL |
| OPs column lists P-numbers | OP with no pedido imputations | `test_eje_procesal.py > test_two_p_numbers_and_a_cuenta_empty` (empty list; no RTL) | ⚠️ PARTIAL |
| Pedido tipo mercadería or servicio | Default tipo on create | `test_pedido_factura_documentos.py > test_crear_pedido_defaults_tipo_mercaderia_and_responsable` | ✅ COMPLIANT |
| Pedido tipo mercadería or servicio | Admin can edit tipo; PM cannot after create | `test_pm_cannot_patch_tipo_after_create` + `test_admin_can_patch_tipo_after_create` | ✅ COMPLIANT |
| Pedido responsable | Default and backfill to creator | create default tested; Alembic backfill SQL not executed at runtime | ⚠️ PARTIAL |
| Pedido responsable | Non-editor cannot change responsable | `test_pedido_factura_documentos.py > test_non_editor_cannot_change_responsable` | ✅ COMPLIANT |
| Visibility chips OC, factura, Match | Chips independent of procesal | `test_eje_procesal.py > test_factura_and_latest_match` + mapper (no TabPedidos RTL; OC chip from header) | ⚠️ PARTIAL |
| Procesal axis on Pedidos | Servicio is n_a_servicio | `test_eje_procesal.py > test_calcular_eje_procesal_mapping` (list render untested) | ⚠️ PARTIAL |
| Procesal axis on Pedidos | Mercadería waiting for goods | `test_eje_procesal.py > test_calcular_eje_procesal_mapping` | ✅ COMPLIANT |
| AND filters on Depósito | AND narrows the list | `test_recepcion_deposito_endpoints.py > test_and_proveedor_factura_intersection` | ✅ COMPLIANT |
| AND filters on Depósito | Empty filter ignored | same test `q_numero=P-01-2026-00012` only | ✅ COMPLIANT |
| Docs button opens pedido adjuntos | Docs opens adjuntos | `TabRecepcionDeposito.test.jsx > Docs opens pedido adjuntos` | ✅ COMPLIANT |
| Hide complete lines in faltantes | Complete line hidden | `TabRecepcionDeposito.test.jsx > hides faltantes lines with saldo_pendiente 0` | ✅ COMPLIANT |
| Control observation and photo optional | Control complete without obs or photo | `test_recepcion_deposito_endpoints.py > test_control_complete_without_obs_succeeds` | ✅ COMPLIANT |
| TabRecepcionDeposito Pedido list | List shows pagado and con_faltantes pedidos | Por recibir pagado RTL; con_faltantes tab contents not asserted | ⚠️ PARTIAL |
| TabRecepcionDeposito Pedido list | Por recibir defaults to pagado only | `TabRecepcionDeposito.test.jsx > requests the listing with pagado only on mount` | ✅ COMPLIANT |
| TabRecepcionDeposito Pedido list | CC toggle includes cuenta corriente | `TabRecepcionDeposito.test.jsx > includes cuenta corriente when the toggle is on` | ✅ COMPLIANT |
| Undo recibido | Undo recibido returns to por recibir | `test_recepcion_deposito_endpoints.py > test_undo_recibido_to_pagado` | ✅ COMPLIANT |
| Undo recibido | Undo controlado rejected | `test_recepcion_deposito_endpoints.py > test_undo_controlado_409` | ✅ COMPLIANT |
| Servicio uses n_a_servicio | Servicio skipped by recepción | `test_servicio_confirmar_409` + `test_servicio_ingresos_409` | ✅ COMPLIANT |
| Controlado iff all OCs done | One of two OCs controlled | `test_vincular_oc_multi.py > test_one_of_two_open_stays_non_terminal` | ✅ COMPLIANT |
| Controlado iff all OCs done | Last OC completes control | `test_vincular_oc_multi.py > test_last_oc_completes_controlado` | ✅ COMPLIANT |
| REQ-EC-001 | pagado → recibido | `test_recepcion_deposito_endpoints.py > test_pagado_arrival_*` | ✅ COMPLIANT |
| REQ-EC-001 | recibido → controlado | `test_recibido_to_controlado_sin_oc` | ✅ COMPLIANT |
| REQ-EC-001 | recibido → con_faltantes | `test_recibido_to_con_faltantes_sin_oc` | ✅ COMPLIANT |
| REQ-EC-001 | con_faltantes → controlado | `test_con_faltantes_to_controlado_sin_oc` | ✅ COMPLIANT |
| REQ-EC-001 | controlado rejects ingresos CON OC | `test_registrar_ingresos_pedido_ya_controlado_409` | ✅ COMPLIANT |
| REQ-EC-001 | controlado rejects confirmar SIN OC | `test_controlado_rejects_confirmar_409` | ✅ COMPLIANT |
| REQ-EC-001 | Invalid source state is rejected | `test_validar_estado_receptivo_rechaza_borrador` / `test_state_borrador_rechaza_ingreso_409` | ✅ COMPLIANT |
| REQ-EC-001 | Undo recibido from intermediate | `test_undo_recibido_to_pagado` | ✅ COMPLIANT |
| REQ-EC-003 | SIN OC arrival → recibido | state+no ingresos tested; event is `recepcion_arribo` not spec `recepcion_registrada` | ⚠️ PARTIAL |
| REQ-EC-003 | SIN OC control complete → controlado | `test_recibido_to_controlado_sin_oc` | ✅ COMPLIANT |
| REQ-EC-003 | SIN OC control with missing → con_faltantes | `test_recibido_to_con_faltantes_sin_oc` | ✅ COMPLIANT |
| REQ-EC-003 | SIN OC missing without observaciones | `test_recibido_to_con_faltantes_sin_oc` (faltantes_texto, no obs) | ✅ COMPLIANT |
| REQ-EC-003 | SIN OC controlado rejects further | `test_controlado_rejects_confirmar_409` | ✅ COMPLIANT |
| REQ-EC-005 | Por recibir tab shows only pagado | `TabRecepcionDeposito.test.jsx` four tabs + pagado-only mount | ✅ COMPLIANT |
| REQ-EC-005 | Recibidos sin controlar shows only recibido | four-tab assertion; no click→`estado=recibido` | ⚠️ PARTIAL |
| REQ-EC-005 | Controlados shows only controlado | four-tab assertion; no click→`estado=controlado` | ⚠️ PARTIAL |
| REQ-EC-005 | Con faltantes shows only con_faltantes | four-tab assertion; no click→`estado=con_faltantes` | ⚠️ PARTIAL |
| REQ-EC-005 | Por recibir CC toggle includes CC | `TabRecepcionDeposito.test.jsx > includes cuenta corriente when the toggle is on` | ✅ COMPLIANT |
| N OC blocks on one pedido | Two OCs render two blocks | `TabRecepcionDeposito.test.jsx > renders one block per linked OC` | ✅ COMPLIANT |
| Servicio forbids OC | Vincular rejected on servicio | `test_vincular_oc_multi.py > test_servicio_409` + `ModalVincularOC.test.jsx` | ✅ COMPLIANT |
| REQ-OC-001 | Migration adds columns with no breaking changes | `compras_045` present; relation used in tests; alembic upgrade not run here | ⚠️ PARTIAL |
| REQ-OC-001 | Partial fill is rejected | `test_vincular_oc_multi.py > test_partial_triple_422` | ✅ COMPLIANT |
| REQ-OC-001 | Second triple stored without clearing first | `test_vincular_oc_multi.py > test_add_not_replace_keeps_first_triple` | ✅ COMPLIANT |
| REQ-OC-003 | Successful link | `test_oc_vincular_s1_endpoints.py > test_vincular_oc_setea_3_cols` | ✅ COMPLIANT |
| REQ-OC-003 | OC does not exist → 404 | `test_vincular_oc_multi.py > test_404_oc_no_existe` | ✅ COMPLIANT |
| REQ-OC-003 | OC belongs to wrong supplier → 409 | `test_vincular_oc_multi.py > test_409_supplier_mismatch` | ✅ COMPLIANT |
| REQ-OC-003 | Pedido already has OC → adds without replace | `test_add_not_replace_keeps_first_triple` + `test_vincular_oc_409_ya_vinculado` (now 200) | ✅ COMPLIANT |
| REQ-OC-003 | No permission → 403 | `test_vincular_oc_multi.py > test_403_sin_permiso` | ✅ COMPLIANT |
| REQ-OC-003 | Pedido not found → 404 | `test_vincular_oc_multi.py > test_404_pedido_inexistente` | ✅ COMPLIANT |
| REQ-OC-003 | Duplicate triple rejected | `test_vincular_oc_multi.py > test_duplicate_triple_409` | ✅ COMPLIANT |

**Compliance summary**: 54/67 scenarios compliant (13 PARTIAL, 0 FAILING, 0 UNTESTED)

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| Normalized factura rows | ✅ Implemented | `pedido_factura_documentos`; cargada ⇔ ≥1 row |
| Seed from facturas_documento | ✅ Implemented | `compras_044` splits `;` tokens; raw field kept |
| Nonempty document number | ✅ Implemented | POST 422; no alert |
| Five-minute undo | ✅ Implemented | DELETE ≤5m 204 / >5m 409; retracts notifs |
| In-app channel only | ✅ Implemented | Notificacion + AlertBanner + campanita feed; no email/Slack product path |
| Alert copy P-number | ✅ Implemented | `P-…` + proveedor + nº |
| Factura recipients / per-user OK | ✅ Implemented | titular ∪ sub-PM ∪ Admin ∪ Gerente ∪ Superadmin; OK → DESCARTADA |
| Faltantes to responsable | ✅ Implemented | `faltantes_texto` required; deep-link `focus=observaciones` |
| Faltantes snooze 1h from mark | ✅ Implemented | `REVISADA` + snooze marker; hide until mark+1h |
| Faltantes resolution G31 | ✅ Implemented | `deposito.recibir_mercaderia` fan-out |
| OPs P-numbers column | ✅ Implemented | `pedidos_numeros` batch; TabOrdenesPago maps array |
| Pedido tipo | ✅ Implemented | default mercaderia; PM create / admin edit |
| Pedido responsable | ✅ Implemented | default/backfill `creado_por_id` |
| Visibility chips | ✅ Implemented | OC from header/ocs; factura rows; latest Match |
| Procesal axis | ✅ Implemented | DTO `eje_procesal`; `aprobado` not a procesal value |
| AND filters | ✅ Implemented | `q_proveedor\|q_numero\|q_factura\|q_empresa` |
| Docs = adjuntos | ✅ Implemented | TabRecepcionDeposito adjuntos modal |
| Hide saldo 0 | ✅ Implemented | faltantes UI |
| Optional obs/photo | ✅ Implemented | control succeeds empty; faltantes_texto still required |
| Depósito pagado+CC | ✅ Implemented | Por recibir default pagado; CC toggle |
| Undo recibido | ✅ Implemented | pagado or CC (D-UNDO-R); controlado 409 |
| Servicio n_a_servicio | ✅ Implemented | recepción + vincular 409 |
| Controlado iff all OCs | ✅ Implemented | `recalcular_estado` all linked OCs |
| REQ-EC-001/003/005 | ✅ Implemented | state machine + 4 tabs + D-SINOC routing |
| N OC blocks | ✅ Implemented | `pedido_compra_ocs` + N headings |
| REQ-OC-001/003 | ✅ Implemented | add-not-replace; 403/404/409/422 |

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| D-FACT rows not ERP | ✅ Yes | New table; ERP matching untouched |
| D-FANOUT union broadcast | ✅ Yes | No `marca_id` invent |
| D-BANNER notificaciones | ✅ Yes | AppLayout stacks `compras.*`; no localStorage |
| D-SNOOZE no column | ✅ Yes | REVISADA + notas_revision |
| D-SINOC keep routing | ✅ Yes | Arrival vs control by state |
| D-MULTI relation SoT | ✅ Yes | `compras_045` (not 043); header first-link cache |
| D-UNDO-R pagado vs CC | ✅ Yes | `op_cuenta_corriente_id` and not `pagado_en` → CC |
| D-PERMS reuse codes | ✅ Yes | No new permission codes |
| Arrival event name | ⚠️ Partial | Spec text `recepcion_registrada`; impl/tests `recepcion_arribo` for arrival |
| Alembic id 045 | ✅ Yes | Design/tasks corrected 043→045 |

### Issues Found
**CRITICAL**: None

**WARNING**:
1. 13 scenarios are PARTIAL: FE list render (Pedidos chips/procesal, OPs `pedidos_numeros`, campanita, three Depósito tab clicks), Alembic backfill/045 not executed in this harness, snooze reappear asserted on `/notificaciones` not banner+bell, SIN-OC arrival event name `recepcion_arribo` vs spec `recepcion_registrada`.
2. Operator guide says the financial badge is not called “Pendiente”; shared `EstadoBadge` still labels `aprobado` as “Pendiente” (pre-existing `596714dc`, unchanged on this branch; out of scope).
3. `chips_visibilidad_batch` returns factura + Match only; OC chip is derived from header/`ocs` in the FE.

**SUGGESTION**:
1. Add TabPedidosCompra / TabOrdenesPago RTL for chips, `eje_procesal`, and `pedidos_numeros`.
2. Assert Recibidos/Controlados/Con faltantes tab clicks send the matching `estado` param.
3. Cover campanita without mocking TopBar away, or assert NotificationBell reads the same `/notificaciones` list.

### Verdict
PASS WITH WARNINGS
22/22 tasks done; 54/67 scenarios have passing covering tests; 13 PARTIAL (no FAILING/UNTESTED); hard locks hold; pytest 167 + vitest 45 + ruff/eslint exit 0.

```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:1a64922eabb4752163bf9f61aeb28d267549134fc1b9b3e637f90f0c0787e530
verdict: pass_with_warnings
blockers: 0
critical_findings: 0
requirements: 14/14
scenarios: 37/37
test_command: ENVIRONMENT=testing /home/user/proyectos/pricing-app/backend/venv/bin/pytest tests/unit/test_recepcion_resolver_faltantes.py tests/unit/test_eje_procesal.py tests/unit/test_compras_alertas_service.py tests/unit/test_notificacion_service.py tests/unit/test_pedido_factura_documentos.py tests/integration/test_recepcion_deposito_endpoints.py::TestResolverFaltantesHttp tests/integration/test_recepcion_deposito_endpoints.py::TestListarPedidosEjeTipo tests/integration/test_recepcion_deposito_endpoints.py::TestRecepcionServicio409 -q --tb=line && pnpm exec vitest run --project=unit src/components/compras/ModalPedidoDetalle.test.jsx src/components/AppLayout.comprasBanners.test.jsx src/components/compras/TabRecepcionDeposito.test.jsx src/components/compras/TabPedidosCompra.test.jsx src/components/compras/ModalPedidoCompra.test.jsx
test_exit_code: 0
test_output_hash: sha256:6c00ec576364b985e58e4b41cc0bd97d40d166e5d0786561af267becd590b5b1
build_command: /home/user/.local/bin/ruff format --check app/schemas/recepcion.py app/services/recepcion_service.py app/services/compras_alertas_service.py app/services/pedidos_service.py app/services/notificacion_service.py app/routers/administracion_compras.py app/api/endpoints/notificaciones.py && pnpm exec eslint src/hooks/useRecepcionDeposito.js src/components/compras/ModalPedidoDetalle.jsx src/components/AppLayout.jsx src/components/compras/TabRecepcionDeposito.jsx src/components/compras/TabPedidosCompra.jsx src/components/compras/ModalPedidoCompra.jsx
build_exit_code: 0
build_output_hash: sha256:68e86d35959d7d7815a041438b18ecc35b6a3c4e355f7f7ad924b1b54016171c
```

## Verification Report

**Change**: compras-pipeline-reqs-closure
**Version**: N/A (delta specs; tip `feat/compras-pipeline-reqs-closure-05-tipo-oc-guia` @ 43db7b40)
**Mode**: Standard

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 23 |
| Tasks complete | 23 |
| Tasks incomplete | 0 |

Native heading counts across `openspec/changes/compras-pipeline-reqs-closure/specs/`: **14** `### Requirement:` / **37** `#### Scenario:`.

### Build & Tests Execution
**Build**: ✅ Passed
```text
ruff format --check (7 Python files) → 7 files already formatted; EXIT:0
pnpm exec eslint (6 FE files) → 0 errors, 2 pre-existing react-hooks/exhaustive-deps warnings in AppLayout.jsx; EXIT:0
```

**Tests**: ✅ 156 passed / ❌ 0 failed / ⚠️ 0 skipped (84 pytest + 72 vitest)
```text
pytest (main-repo venv; ENVIRONMENT=testing; worktree .env): 84 passed, 21 warnings in 48.42s; EXIT:0
vitest --project=unit: 5 files / 72 tests passed in 3.82s; EXIT:0
```

**Coverage**: ➖ Not available / threshold: N/A → ➖ Not available

### Spec Compliance Matrix
| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| compras.faltantes dismiss rejected | Banner OK rejected | `test_compras_alertas_service.py > test_snooze_allowed_ok_and_dismiss_409` + `AppLayout.comprasBanners.test.jsx` no /ok | ✅ COMPLIANT |
| compras.faltantes dismiss rejected | Resolve retracts the alert | `test_recepcion_resolver_faltantes.py > test_resolve_retracts_faltantes_alert` + `test_retractar_faltantes_clears_alert` | ✅ COMPLIANT |
| compras.faltantes dismiss rejected | Snooze still allowed | `test_snooze_allowed_ok_and_dismiss_409` (PATCH /snooze 200) | ✅ COMPLIANT |
| Faltantes snooze one hour from mark | Snooze until mark plus one hour | `test_hide_until_mark_plus_one_hour` (API list, not banner/bell UI) | ⚠️ PARTIAL |
| Faltantes resolution notifies depósito | All depósito receivers notified | `test_compras_alertas_service.py > test_deposito_receivers_only` | ✅ COMPLIANT |
| Faltantes resolution notifies depósito | G31 includes PM texto and Depósito deep-link | `test_deposito_receivers_only` (mensaje+codigo_producto `?tab=deposito&pedido=`) + `test_notificacion_service.py` codigo_producto pass-through | ✅ COMPLIANT |
| Faltantes resolution notifies depósito | Empty resolve texto rejected | `test_recepcion_resolver_faltantes.py > test_empty_texto_422_no_stamp` + HTTP `TestResolverFaltantesHttp.test_empty_texto_422` | ✅ COMPLIANT |
| faltantes_con_res display label | Resolved faltantes label | `TabPedidosCompra.test.jsx` + `ModalPedidoDetalle.test.jsx` label “Faltantes con resolución” | ✅ COMPLIANT |
| OC chip is vinculación | Chip stays vinculación | `TabPedidosCompra.test.jsx` chip-oc + no chip-gbp / “existe en GBP” | ✅ COMPLIANT |
| OC chip is vinculación | Multi-OC compact labels | `TabPedidosCompra.test.jsx` `#100` `#200` | ✅ COMPLIANT |
| OC chip is vinculación | Single OC chip only | `TabPedidosCompra.test.jsx` no oc-poh-label | ✅ COMPLIANT |
| Pedido tipo mercadería or servicio | Default tipo on create | `test_pedido_factura_documentos.py > test_crear_pedido_defaults_tipo_mercaderia_and_responsable` + `ModalPedidoCompra.test.jsx` default | ✅ COMPLIANT |
| Pedido tipo mercadería or servicio | PM sets tipo on create | `ModalPedidoCompra.test.jsx` sends tipo=servicio | ✅ COMPLIANT |
| Pedido tipo mercadería or servicio | Admin can edit tipo; PM cannot after create | `test_pm_cannot_patch_tipo_after_create` + `test_admin_can_patch_tipo_after_create` + FE hides tipo on edit | ✅ COMPLIANT |
| Depósito tabs filter by eje and exclude servicio | Con faltantes hides resolved | `test_eje_procesal.py > test_comma_or_recibidos_and_tipo_excludes_servicio` + FE `eje_procesal=faltantes_sin_res` | ✅ COMPLIANT |
| Depósito tabs filter by eje and exclude servicio | Recibidos includes resolved faltantes | same BE comma-OR + HTTP `TestListarPedidosEjeTipo` + FE Recibidos params | ✅ COMPLIANT |
| Depósito tabs filter by eje and exclude servicio | Servicio excluded from Por recibir | FE `tipo=mercaderia` on Por recibir + BE list/tipo filter + `TestRecepcionServicio409` | ✅ COMPLIANT |
| Factura cargada badge in Depósito | Badge follows cargada flag | `TabRecepcionDeposito.test.jsx` badge when factura_cargada true | ✅ COMPLIANT |
| Factura cargada badge in Depósito | Numbers without cargada show no badge | `TabRecepcionDeposito.test.jsx` numbers + flag false | ✅ COMPLIANT |
| Ident chips on all Depósito rows | CON-OC shows factura and pedidos_documento | `TabRecepcionDeposito.test.jsx` CON-OC chips | ✅ COMPLIANT |
| Ident chips on all Depósito rows | SIN-OC still shows ident chips | `TabRecepcionDeposito.test.jsx` SIN-OC chips | ✅ COMPLIANT |
| Control observation and photo optional | Control complete without obs or photo | `TabRecepcionDeposito.test.jsx` OK empty → confirmar-pedido | ✅ COMPLIANT |
| Control observation and photo optional | Control OK accepts obs and photo | FE upload `tipo=otro` then control; no BE persist assert in this run | ⚠️ PARTIAL |
| TabRecepcionDeposito.jsx — Pedido list | List shows pagado and con_faltantes pedidos | FE Por recibir `estado=pagado` + Con faltantes eje + BE list split | ✅ COMPLIANT |
| TabRecepcionDeposito.jsx — Pedido list | Por recibir defaults to pagado only | `TabRecepcionDeposito.test.jsx` mount params | ✅ COMPLIANT |
| TabRecepcionDeposito.jsx — Pedido list | CC toggle includes cuenta corriente | `TabRecepcionDeposito.test.jsx` toggle params | ✅ COMPLIANT |
| Resolve faltantes keeps financial estado | Resolve stamps without new estado | `test_responsable_stamps_keeps_estado` | ✅ COMPLIANT |
| Resolve faltantes keeps financial estado | Empty texto rejected | `test_empty_texto_422_no_stamp` + HTTP 422 | ✅ COMPLIANT |
| Resolve faltantes keeps financial estado | Depósito-only writer rejected | `test_deposito_only_not_responsable_403` + HTTP 403 | ✅ COMPLIANT |
| Resolve faltantes keeps financial estado | Responsable or OC-admin may resolve | `test_responsable_stamps_keeps_estado` + `test_gestionar_oc_not_responsable_ok` | ✅ COMPLIANT |
| Eje split for con_faltantes | Unresolved maps to faltantes_sin_res | `test_calcular_eje_procesal_mapping` | ✅ COMPLIANT |
| Eje split for con_faltantes | Stamp maps to faltantes_con_res | mapping + FE/Pedidos label | ✅ COMPLIANT |
| REQ-EC-005 — Filter tabs | "Por recibir" tab shows only pagado pedidos | FE default params + four-tab list | ✅ COMPLIANT |
| REQ-EC-005 — Filter tabs | "Recibidos" tab includes recibido and faltantes_con_res | FE Recibidos params + HTTP list | ✅ COMPLIANT |
| REQ-EC-005 — Filter tabs | "Controlados" tab shows only controlado pedidos | four-tab list + eje mapping; FE sends `estado=controlado` not `eje_procesal=controlado`; no click-query test | ⚠️ PARTIAL |
| REQ-EC-005 — Filter tabs | "Con faltantes" tab shows only faltantes_sin_res | FE + BE solo_sin | ✅ COMPLIANT |
| REQ-EC-005 — Filter tabs | Por recibir CC toggle includes cuenta corriente | FE toggle params | ✅ COMPLIANT |

**Compliance summary**: 34/37 COMPLIANT, 3/37 PARTIAL, 0 UNTESTED, 0 FAILING

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| compras.faltantes dismiss rejected | ✅ Implemented | 409 on /ok /descartar /bulk-descartar; FE hide dismiss |
| Faltantes snooze one hour from mark | ✅ Implemented | mark+1h clock unchanged |
| Faltantes resolution notifies depósito | ✅ Implemented | required texto; retract; G31 copy+`codigo_producto` |
| faltantes_con_res display label | ✅ Implemented | “Faltantes con resolución” |
| OC chip is vinculación | ✅ Implemented | chip + `#{poh}` if N>1; no GBP chip |
| Pedido tipo mercadería or servicio | ✅ Implemented | create selector; Por recibir `tipo=mercaderia` |
| Depósito tabs filter by eje and exclude servicio | ✅ Implemented | BE comma-OR + tipo force on depósito list |
| Factura cargada badge in Depósito | ✅ Implemented | `factura_cargada` + badgeControlado |
| Ident chips on all Depósito rows | ✅ Implemented | factura + pedidos_documento on CON-OC and SIN-OC |
| Control observation and photo optional | ✅ Implemented | AdjuntosPanel `tipo=otro`; empty OK succeeds |
| TabRecepcionDeposito.jsx — Pedido list | ✅ Implemented | 4 tabs; CC toggle; eje/tipo params |
| Resolve faltantes keeps financial estado | ✅ Implemented | stamp; estado stays `con_faltantes`; writer perms |
| Eje split for con_faltantes | ✅ Implemented | null stamp→sin_res; stamp→con_res |
| REQ-EC-005 — Filter tabs | ✅ Implemented | four tabs; Recibidos UI label is “Recibidos sin controlar” |

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| Stamp; keep `con_faltantes` | ✅ Yes | no new estado / Alembic |
| BE `eje_procesal` comma-OR | ✅ Yes | Recibidos + Con faltantes |
| G31 `?tab=deposito&pedido={id}` | ✅ Yes | mensaje + codigo_producto |
| 409 on /ok /descartar /bulk | ✅ Yes | snooze stays |
| Writers responsable or gestionar_oc | ✅ Yes | depósito-only 403 |
| Photo via adjuntos `otro` | ✅ Yes | upload-then-control |
| Cargada badge from flag only | ✅ Yes | chicho lock held |
| Controlados `eje_procesal=controlado` | ⚠️ Partial | FE sends `estado=controlado` (1:1 mapping) |
| Five chained slices | ✅ Yes | Phases 1–5 on tip 43db7b40 |
| No novedad rewrite | ✅ Yes | deferred |

### Issues Found
**CRITICAL**: None
**WARNING**: (1) Controlados FE uses `estado=controlado` instead of design `eje_procesal=controlado`; equivalent today, no dedicated click-query test. (2) Snooze reopen proven on API list, not banner/campanita UI. (3) Control OK+photo proven on FE mock upload, not BE adjunto persist in this run. (4) Recibidos tab copy is “Recibidos sin controlar” vs spec table “Recibidos”. (5) `pages/Notificaciones.jsx` can still PATCH /descartar (BE 409). (6) AppLayout eslint exhaustive-deps warnings pre-exist.
**SUGGESTION**: Add a Controlados click-query vitest and a BE adjunto `tipo=otro` persist assertion on control OK.

### Verdict
PASS WITH WARNINGS
All 23 tasks done; 14/14 requirements implemented; 34/37 scenarios fully covered at runtime and 3 partial; no failing tests; chicho locks held; novedad still out of scope.

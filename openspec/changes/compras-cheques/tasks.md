# Tasks — Módulo de Cheques

**Change ID:** `compras-cheques`
**Fase:** tasks
**Status:** draft
**Estrategia de entrega:** PRs encadenados por slice. Cada slice shippable y verificable. TDD estricto en backend (`cd backend && venv/bin/pytest tests/ -x`).

---

## Slice 1 — Núcleo + cheque propio en la OP

### Backend
- [x] **T1.1** Migración Alembic `20260619_cheques_modulo.py`: tablas `chequeras`, `cheques`, `orden_pago_cheque`, `cheque_evento` (esquema completo del design) + constraints/índices. Seed del permiso `tesoreria.gestionar_cheques` (sin asignar a rol). [No destructivo.]
- [x] **T1.2** Modelos SQLAlchemy: `Chequera`, `Cheque`, `OrdenPagoCheque`, `ChequeEvento`. Tipos explícitos, CheckConstraints.
- [x] **T1.3** `cheques_service.py`: `crear_chequera`, `listar_chequeras`, `proximo_numero(chequera)`.
- [x] **T1.4** `cheques_service.emitir_cheque_propio(...)`: valida fechas (pago ≥ emisión), numeración (única por chequera, avanza próximo número), estado inicial (`emitido`/`diferido`), evento `emitido`. **Test RED→GREEN.**
- [x] **T1.5** Máquina de estados `transicionar_cheque(...)` + `TRANSICIONES_CHEQUE` (propios). `anular` (con motivo) → estado `anulado` + evento. Transición inválida → 422. **Test.**
- [ ] **T1.6** Integración OP: extender payload de pago (`crear_y_pagar`/`ejecutar_pago`) con `cheques: [...]`; emitir + crear `orden_pago_cheque` (monto derivado a moneda OP por TC) + imputar `cc_proveedor`, todo en la misma transacción. **Test (incluye cross-moneda).**
- [ ] **T1.7** `validar_balance_op`: sumar `Σ orden_pago_cheque.monto_op_moneda` a la cobertura, tolerancia `< 0.005`. **Test: cubre, falta cubrir, combinado cheque+caja, cross-moneda.**
- [x] **T1.8** Endpoints (`require_permiso("tesoreria.gestionar_cheques")`): `POST /chequeras`, `GET /chequeras`, `GET /cheques` (filtros), `POST /cheques/propio`, `POST /cheques/{id}/anular`, `GET /cheques/{id}`. **Tests de integración (incl. 403 sin permiso). [standalone; sin integración OP — eso es T1.6/T1.7]**

### Frontend
- [x] **T1.9** `useCheques.js` hook (listar, crear chequera, emitir, anular, obtener).
- [x] **T1.10** `ModalCheque.jsx` (emisión de propio): tipo/instrumento, banco, chequera (autocompleta número), número editable, beneficiario, monto/moneda, fechas (badge diferido), resumen. Validaciones. Tesla DS + CSS Modules + dark mode.
- [x] **T1.11** Página `Cheques` (`TabCheques.jsx` o ruta): tabla con filtros (estado/tipo/banco/moneda/fechas), `EstadoBadge`, acción anular.
- [x] **T1.12** Integración en modal de OP: `PanelCheques` como VALOR (igual que NC) → abre `ModalCheque` en modo OP (sin llamada backend hasta submit) → suma a la cobertura via sumaChequesOP en diferencia y en Resumen de pago.
- [x] **T1.13** Permiso en frontend (`PermisosContext`): TabCheques gateada por `tesoreria.gestionar_cheques`; tab registrada en AdministracionCompras.jsx.

### Verificación
- [ ] **T1.14** Suite backend verde + lint (ruff). Frontend lint. QA manual: emitir cheque propio (al día y diferido), pago combinado, cross-moneda, anular (revierte CC).

### Review Workload Forecast
- Estimado > 400 líneas → **chained PRs recomendado** (separar backend núcleo + integración OP de la UI). Decisión de delivery al iniciar apply.

---

## Slice 2 — Cheques de terceros (cartera + endoso)
- [ ] Modal de carga de cheque de tercero → `en_cartera`. (frontend — pendiente)
- [ ] Página de cartera (cheques `en_cartera`). (frontend — pendiente)
- [x] **FR-2.1** `recibir_cheque_tercero` — alta a cartera + validaciones + evento `recibido`. Tests RED→GREEN.
- [x] **FR-2.2** Endoso a proveedor en la OP (`en_cartera → entregado` + imputa CC) via `cheque_id` en payload. Helper `_imputar_cheque_en_op` factorizado para propios y terceros. Tests.
- [x] **FR-2.4** Estados terceros: `entregar / anular / rechazar` + transición inválida 422. Tests.
- [x] Des-endoso al anular OP: cheque vuelve a `en_cartera` + imputación CC revertida. Fix pure-cheque path en `anular`. Tests.
- [x] Endpoint `POST /cheques/tercero` con permiso + tests de integración (201, 403, validaciones, listado).

## Slice 3 — e-cheq
- [ ] `instrumento=echeq` (propios + terceros), número del banco.
- [ ] Estados `aceptado`/`rechazado_emision`/`en_custodia` (carga manual) + tests.

## Slice 4 — Conciliación bancaria
- [ ] `debitar` (propio) / `acreditar` (tercero) → `banco_movimiento`, paso explícito.
- [ ] Validación no debitar/cobrar antes de `fecha_pago`.
- [ ] Reporte de cheques por estado (cartera, a debitar, vencidos).

---

## Notas
- Reusar: derive-at-edge por TC + tolerancia medio centavo (PRs #781/#782), `EstadoBadge`, patrón de transiciones de pedidos/NCs.
- No-goals: GL doble partida, integración bancaria automática, cobranzas, descuento de cheques.

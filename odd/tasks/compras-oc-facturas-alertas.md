# Compras: OC refresh + multi-factura + alertas + bug faltantes

Objective: Deliver the closed Compras package (refresh OC, multi-OC UX polish, M:N facturas, auto-vínculo post-cargada, worker alertas, bug faltantes banner).
Branch: `feat/compras-oc-facturas-alertas` (slice children as needed)
Delivery: `ask-on-risk` → chain strategy `stacked-to-main` (PRs to `sernafernando/pricing-app:main`, ≤400 lines each)
Test runner: `ENVIRONMENT=testing pytest` (focused unit/integration) + FE lint/tests as touched

## Specs

S1: Bug faltantes / banner Ignacio — "si el pedido ya no está en faltantes (p.ej. pasó a controlado / resuelto), retractar `compras.faltantes`; y/o permitir cierre cuando el estado ya no admite resolver. Regla general, no solo este pedido. Verificar/reparar la notif 364200." Deadlock: `resolver_faltantes` exige `con_faltantes` and OK prohibited → banner revives after snooze.

S2: Alertas factura → worker + Gabe siempre notificado — "Migrar `dispatch_factura_cargada_alerts` (y lo razonable de compras alertas) al patrón worker `REGISTRY` (precedente rrhh). Destinatarios: permiso `administracion.ver_alertas_factura` y asegurar que Gabriel DeMarco (user id 3) siempre reciba… Notificar en todos los casos de factura cargada (tras la ventana de arrepentimiento, como hoy)."

S3: Botón refrescar OC ya vinculada — "Sync de esa OC al espejo GBP (`tb_purchase_order_*`) + releer líneas/saldos en UI. No corrige recepciones ya cargadas (append-only). Caso viejo P-02-2026-00250 out of scope." Multi-OC UX: "Asegurar UX clara de control por OC cuando hay varias; no hace falta reinventar el modelo N-OC."

S4: Multi-factura M:N (NUEVO) — "Poder vincular más de una factura a un pedido y una misma factura a varios pedidos. Junction (estilo `pedido_compra_ocs`), no la columna 1:1 `ct_transaction_id` como SoT. No modificar `pedido.monto` al vincular. Sell-in / `lineas_facturadas`: solo snapshot si esa CT queda ligada a exactamente 1 pedido. Si la CT tiene 2+ pedidos → vínculo documental sí, no copiar líneas. Prorrateo explícito = futuro. UI vincular/desvincular; candidatas dejan de excluir CTs ya usadas en otros pedidos."

S5: Auto-vínculo post "Cargada" + 5 min — "al vencer ventana, si sigue `cargada`, vincular por número (constancia `pedido_factura_documentos.numero` / checks del OC match) a factura ERP vigente. Match por número a los pedidos que tengan esa constancia (M:N). Mantener desvínculo manual. No auto-ajustar monto."

Out of scope: P-02-2026-00250 reception correction; explicit sell-in proration; reinventing N-OC model.

## Tasks

- T1 [S1] — Fix faltantes retract/close when estado no longer admits resolver; repair path for notif 364200 — route: inline — status: done — commit: 3538a813c — PR: https://github.com/sernafernando/pricing-app/pull/2183
- T2 [S2] — Migrate factura_cargada alerts to worker REGISTRY; ensure user id 3 always notified — route: inline — status: done — commit: 35b6047ed — PR: https://github.com/sernafernando/pricing-app/pull/2184
- T3 [S3] — Per-OC GBP mirror refresh API+UI; light multi-OC depósito UX polish — route: inline — status: pending — commit:
- T4 [S4] — Junction M:N pedido↔CT; sell-in snapshot only when CT has exactly 1 pedido; UI/candidatas — route: inline — status: pending — commit:
- T5 [S5] — Auto-link ERP invoice on alert sweep by documento.numero (depends T4) — route: inline — status: pending — commit:

## Log

L1: Sos el **change agent** de Pricing App para el paquete **Compras: OC refresh + multi-factura + alertas + bug faltantes**. [full brief as provided 2026-11-10] Scope 1–6 closed with Gabe; delivery: explore, plan ≤400 slices (bug → worker → refresh OC → M:N → auto-vínculo), implement chained PRs to main.

# Exploration: compras-ops-pipeline-ux

Usability boost for Compras (Pedidos → pago → depósito → alerts), driven by Admin + PM/Depósito operators. Product discovery completed in-session (2026-09-22); decisions locked below.

## Current state (summary)

- Hub: `/administracion/compras` — ~10 tabs; core entity is **Pedido** (header amount, no native lines).
- **OC** = ERP purchase order link (single `oc_*` triple today). **OP** = payment. **Depósito** = receive/control.
- Doc refs already on `main` (PRs #1314/#1317): `facturas_documento`, `pedidos_documento` (`; `-separated Text, max 500, OC Match write-once). Do not conflate with Pricing `P-…` number.
- List Pedidos does not surface OC linked / factura cargada / OC Match status → Admin parallel spreadsheets.
- Single `estado` mixes finance + logistics; depósito states barely visible on Pedidos.
- Alerts system exists (`AlertBanner` + campanita/`notificaciones`); no domain fan-out to marca PMs.
- “PM of ≥1 brand” for product identity = titular in `marcas_pm`; scope UNION includes sub-PM. **This change alerts titular ∪ sub-PM ∪ Admin ∪ Gerente** (product lock).

## Problem clusters

1. Visibility on Pedidos/OPs (OC, Match, docs, pedido numbers on OPs).
2. Process flags: tipo mercadería|servicio, factura(s) cargada with 5‑min undo, responsable, procesal vs financiero.
3. In-app alerts: factura cargada (broadcast); faltantes (responsable + snooze 1h + depo ack on resolution).
4. Depósito UX: filters, default solo pagado, undo recibido, faltantes lines, obs+foto, docs button.
5. Multi-OC (separate PR slice): N OCs per pedido; Depósito blocks; controlado when all OCs controlled.

## Recommended approach

Program of chained PRs (not one mega-PR):

1. Model + Pedidos/OPs visibility (tipo, responsable, factura document rows, chips, obs field).
2. Alerts (reuse alertas/banner + notificaciones).
3. Depósito filters/undo/faltantes/docs.
4. Multi-OC.

Normalize invoice “cargada” as **rows** (option A), seeded from `facturas_documento` tokens — not ERP multi-link (deprecated).

## Out of session research

Unselected: evidence already from codebase + merged PRs + operator questionnaire. No external research required for proposal admission.

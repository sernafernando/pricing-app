# ML bot panel redesign (`/ml-preguntas`)

Objective: restyle the four tabs of `frontend/src/pages/MLQuestions.jsx` to follow the Stitch designs (project "Pricing App - Bot de Preguntas ML", id 9661431541092616317), with no backend changes and no new features.
Branch: `feat/ml-bot-panel-redesign` (from origin/main). Delivery: ask-on-risk (forecast > 400 lines). Runner: `pnpm exec vitest run src/pages/MLQuestions.test.jsx` (frontend/).

## Specs

- **S1** User request (L1, L3): "usate stitch para generar una mejor vista del bot de preguntas ml que quedó re tirado, así no estoy gastando tokens al pedo y se puede usar esa página" / "dale, implementá todo". The page has to match the approved Stitch screens ("claro, así tenía que ser, como salió ahora").
- **S2** Configuración tab: the LLM roster becomes an ordered list of provider rows (order number, provider select, model select or custom input, `Activo` switch, delete button, dashed "Agregar proveedor" button) with ONE save button for the roster. Business variables become a form (monospace key, description below it, input on the right) instead of a table. Few-shot examples become an add form above a two-column grid of cards (category chip, P:, R:, delete).
- **S3** Preguntas tab: the 8-column table becomes a list of row cards. Each card has a left zone (question, nickname, item link, date), a middle zone (draft preview, confidence, provider) and a right zone (status badge, countdown or fallback chip or last error, actions). Actions are LABELED buttons. The expanded detail keeps its Detalle and Historial del comprador sub-tabs. Filters get visible labels and pagination stays.
- **S4** Mensajes tab: becomes master-detail. The left pane holds the labeled filters, the conversation cards (nickname, pack, message count, last-message preview, bot status badge, bot/fallback chip) and pagination. The right pane holds the selected conversation: a header with order context chips and the "Ver en MercadoLibre" link, the thread of loaded messages with read and moderation markers, the draft card (category, confidence), and labeled actions (Tomar, Enviar respuesta del bot, Editar, Crear pendiente), plus the send-disabled hint and the failure alert.
- **S5** Pendientes tab (no Stitch screen; the generation failed twice): same visual system, with labeled filters, a compact table using the existing columns, labeled action buttons, and the existing two-panel expanded detail.
- **S6** Constraints:
  - Keep every existing behavior, permission gate, API call, SSE refresh, modal and status mapping.
  - Do NOT implement anything Stitch made up: version badge, telemetry footer, search box, "Descartar / Bloquear", tokens and latency, "Copiar", stock and price, "Asignado a", "Ver hilo", tab counters, operator replies in the thread.
  - Use CSS Modules and design tokens only (light and dark mode), and Tesla button classes.
- **S7** Add a Novedades entry in the same PR.

## Tasks

| ID | Specs | Route | Status | Commit |
|----|-------|-------|--------|--------|
| T1 | S2, S6 | delegated (context backstop) | pending | |
| T2 | S3, S6 | delegated (context backstop) | pending | |
| T3 | S4, S6 | delegated (context backstop) | pending | |
| T4 | S5, S6 | delegated (context backstop) | pending | |
| T5 | S7 | inline | pending | |

## Log

- L1 (2026-10-26) user: "usate stitch para generar una mejor vista del bot de preguntas ml que quedó re tirado, así no estoy gastando tokens al pedo y se puede usar esa página"
- L2 (2026-10-26) user, after seeing the Configuración screen only: "el diseño solo veo la parte de configuración no de las preguntas, ni ninguna otra parte del diseño"; then "claro, así tenía que ser, como salió ahora"
- L3 (2026-10-26) user: "dale, implementá todo"
- L4 Decision: the card and master-detail layouts drop the resizable columns (`ResizableTableShell` and "Restablecer columnas") in Preguntas and Mensajes. Pendientes keeps its table. Tests that pin column resizing for those two tabs are updated with the layout.
- L5 Reference screenshots (job scratch): Configuración, Preguntas and Mensajes PNGs from Stitch; the Stitch HTML was read by the parent.

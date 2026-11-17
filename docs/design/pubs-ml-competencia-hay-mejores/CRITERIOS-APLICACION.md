# Publicaciones ML — Criterios de aplicación (hay mejores)

Living design notes. Product conversation started 2026-11-16 after #2294 / #2295 (Activa ahora baseline) merged. Update this file as decisions land; do not invent criteria the owner has not named.

## Intent

Keep the **canonical** hay_mejores comparison rule. Add a **Criterios de aplicación** surface that layers **special limitations / extra criteria** on top of that base, and shows **catalog** context for how those rules apply to the open MLA.

This is **not** a rewrite of `es_mejor_oferta`.

## Layered model

| Layer | Role | Status |
| --- | --- | --- |
| A. Canonical comparison | `es_mejor_oferta` / FE `esMejorOferta`: markup↑ at same price; markup≥ at lower price; **higher consumer price never better**. Baseline = Activa ahora (lowest-price `started` / `application_status === 'active'`), else plain sale. Sell-in/out only when both sides have it (`markups_comparables`). | **Shipped — do not replace** |
| B. Special limitations / extras | Configurable rules (below) that clamp, alternate-path, or filter who counts in catalog. Global via bulk on filtered MLAs and/or per MLA. | **Listed 2026-11-16 — refining** |
| C. Catalog + display | Fresh catalog snapshot feeds B; Criterios UI shows how rules + catalog interact. | **Depends on B** |

Flag / fingerprint / discard / `hay_mejores_excluido` / slots SMART·DEAL·Premium stay tied to “what counts as suggestible” once composition of A+B is decided.

## Panel UX — shared right column with Competencia

Today **Ver competencia** opens a second column in the wide Promos panel (col1 = promos compact, col2 = catalog ranking). See [UX.md](./UX.md).

**Criterios de aplicación** reuses that **exact same space**:

| Behavior | Rule |
| --- | --- |
| Open Criterios while Competencia is open | Close Competencia; open Criterios in the same column |
| Open Competencia while Criterios is open | Close Criterios; open Competencia in the same column |
| Close the active one | Column dismisses (narrow / no col2), same as today’s **Ocultar competencia** |
| Mutual exclusion | Only one of {Competencia, Criterios} occupies col2 at a time — toggle that **replaces**, not stacks |

Control: **Criterios de aplicación** button alongside **Ver competencia**. Open/close labels TBD.

## Scope of rules (product)

- **Global**: bulk actions on the **currently filtered** MLAs.
- **Per MLA**: set on a single publication.
- Persistence shape TBD (new table vs row-pattern reuse).

---

## Criteria catalog (owner list, 2026-11-16)

Proposed grouping for design (not implementation order):

### Family 1 — Clamp on canonical “mejor” (promo → suggest / flag)

| # | Name | Rule (owner wording) | Notes |
| --- | --- | --- | --- |
| **C1** | **Límite de markup** | Upper and/or lower markup bound. Potential markups outside the range are **not** “mejor” even if they pass the canonical rule. | Filters layer A. **Decided 2026-11-17**: uses the **same markup** as status-quo comparison (canonical / sell-in-out when applicable). When C1 is active, that markup must fall **inside** the configured band. |

### Family 2 — Catalog win path (needs fresh catalog on promo refresh)

| # | Name | Rule (owner wording) | Notes |
| --- | --- | --- | --- |
| **C2** | **Ganar catálogo** | Consider promos that would **win the catalog**. Fresh catalog when new promos are reviewed is **required**. **Toggle “solo markup positivo”**: **ON** → only suggest catalog-win when the candidate markup is **&gt; 0**; **OFF** → may suggest catalog-win even if that promo yields **negative** markup. | Alternate path vs A. Markup = same basis as status-quo / C1. “Positivo” = literal **% &gt; 0**, not “mejor que status quo”. |

### Family 3 — Who counts (competitor table — sole source for C2 / C6)

**Decided 2026-11-17:** the **competitor table for this tramo** is the **only** source of who counts in the effective ranking. **PM responsibility** that it is correct. No automatic soft weights; no auto-hide rules that override the table.

| UX | Behavior |
| --- | --- |
| Rows | All competitors in the current catalog tramo / same bucket for the open MLA |
| Columns (info) | Attributes the PM needs to judge: **Full**, **intl**, stock residual (if available), reputación, nombre visible, precio, etc. Missing ML fields → empty / “sin dato”, not a hidden filter |
| Checkbox | **All checked by default** (= count as competitors). PM **unchecks** sellers to exclude them from effective ranking |
| Persistence | Saved per MLA (unchecked set / inclusion flags). **New sellers** that appear on refresh → **checked by default**; previous unchecks kept |
| R-AUTO / C2 / C6 | Use **only** the currently saved table state. If the PM left everyone checked, everyone counts |

Former C3–C5 / C7 / C8 as **automatic toggles** are **superseded** by this table (attributes become columns; hide = uncheck). The earlier “C3 N configurable default 3” idea is **dropped** in favor of PM judgment on the stock column.

### Family 4 — Monopoly ceiling (price-up opportunity, not “apply cheaper promo”)

| # | Name | Rule (owner wording) | Notes |
| --- | --- | --- | --- |
| **C6** | **Techo por monopolio** | If we **are winning** the catalog and gap to 2nd place (**among checked competitors**) is **≥ gap mínimo**, we may **raise** our price — with or without a promo. **Toggle**: notify **only** when raise is possible **via a promo**, vs notify in any case. | **Decided 2026-11-17**: **gap mínimo** configurable (default **≥ $5000**); **distancia objetivo** al 2º configurable (default **$100** → Premium at 2nd − distancia). |

### Dependency sketch

```text
Catalog snapshot (fresh on promo review)
    → competitor table (checked = counts)  ⇒  effective ranking
        → C2: promo that would put us #1 (effective) ?
        → C6: we are #1 and gap to #2 > threshold ?

Canonical A + C1 clamp  ⇒  classic “mejor markup/precio” candidates
```

### C6 UX (owner draft 2026-11-16 — agent agrees in spirit)

Same flag as hay_mejores; **different lead** when the novelty is monopoly headroom (not “better cheaper promo”):

> Example tone: “Tenés oportunidad de aumentar el precio en $XXXX con X% de markup y mantener tu posición en el catálogo.”
> (Not: “Hay candidatas mejores que el precio vigente en MeLi. Markup vigente ~ …”)

Suggestion content:

1. If a **promo exists** that helps reach that raise while keeping #1 (effective ranking) → suggest that promo (same apply control pattern as today).
2. If **no** such promo → suggest a **Premium** at the max price that still keeps position: **(effective 2nd-place price) − distancia objetivo** (default **$100**), **editable** by the PM.
3. If Premium **cannot be enrolled** (or enroll fails) → still **enter the C6 circuit** (flag / monopolio lead), **without** a suggested promo, plus a **banner**: we can raise price but Premium application failed + **concrete reason**.

Clarification (owner 2026-11-17): “2nd place” = among **checked** competitors in the table — not a second markup math. Raising price while staying #1 improves markup with the higher price.

**Dual case (decided 2026-11-17):** when classic “mejor” and C6 both apply on the same MLA, **show both** — not pick one. **Order:** candidatas (classic) **above** monopolio. **C6 block only if the monopoly criterion is enabled** (off → no monopolio UI even if the gap exists).

---

## Suggested composition (proposal — not decided)

| Outcome | Proposed logic |
| --- | --- |
| Classic suggestible promo | Passes **A** AND passes **C1** (if bounds set) |
| Catalog-win suggestible promo | Passes **C2** on **effective** ranking (checked competitors only); if C2 “solo markup positivo” **ON**, require markup **&gt; 0**; if **OFF**, catalog win alone (even negative markup) |
| Flag / suggestions | Classic ∪ (C2 according to its toggle) — pending finer UX |
| Monopoly (C6) | Same `hay_mejores` flag + **different lead copy** (not “Hay candidatas mejores…”). Raise-price opportunity while already winning; toggle promo-only vs any raise. See **C6 UX** below. |

## Data / capability gates

| Criterion | Needs | If missing |
| --- | --- | --- |
| C2, C6 | Fresh catalog + **competitor table** state | Feature inert / no catalog path |
| Table columns | Full / intl / stock / reputación when ML exposes them | Column empty; PM still checks/unchecks |

## Audit as-is (2026-11-17 — inventory for criterios design)

### When a pub is flagged

Stored on **`ml_item_seller_promotions`** (current row only, overwritten): `hay_mejores_ofertas`, `hay_mejores_fingerprint` (`promotion_key:price|…`), `hay_mejores_descartado_fingerprint`, `hay_mejores_excluido`. Live `raw` + sale price exist on related tables but are **not** a flag-time snapshot.

**Not stored:** flag timestamp; status-quo price / Activa ahora id; markups (plain or sell-in/out) of status quo or candidates; cost / sell-in batch used. No `ml_item_events` / `auditoria` row for flag flips. Successful enroll **clears** flag + fingerprints (`limpiar_hay_mejores_ofertas`).

→ **Cannot reconstruct** status quo vs candidata *at flag time* later; recomputing from today’s `raw` is today’s world.

### When a promo is applied (enroll)

**`ml_write_log`** (`resource=promotion`, `action=enroll`) if status is submitted/reconciled: user, time, promo id/type, `precio_visto` / `deal_price`, optional `markup_visto` (SMART-like suggestion path), `precio_aplicado`. Failed enrolls often leave **no** row.

Later worker may add **`ml_item_events`** (`promotion_activated`, `price_changed`) and **`ml_change_log`** (promotions JSON old/new) — eventual ML mirror, not the click instant. **`auditoria`** is unused for promos.

→ **Partial** before/after on price (seen vs applied + later sale events). Status-quo markup at click and post-apply markup are **not** a durable audit pair.

### Implication for criterios — **requirement (decided 2026-11-17)**

Ship **lean audit** as part of the criterios package (not optional follow-up):

1. **Flag transition event** when `hay_mejores_ofertas` becomes true or `hay_mejores_fingerprint` changes: persist timestamp + status-quo snapshot (price, markups, Activa ahora key if any) + beating candidates (key, price, markups) + rules/criteria version. **Do not** write on no-op boundaries ticks. → table **`ml_hay_mejores_audit`** (`kind=flag_transition`).
2. **Enroll enrich** on `ml_write_log.payload`: `auto_aplicacion` + latest `hay_mejores_flag_snapshot` when present + existing prices/markups seen vs applied.
3. **Auto toggle log** on each flip → same table (`kind=auto_toggle`, old→new, usuario, alcance).
4. Retention / UI to browse “por qué se flageó / qué se aplicó” can follow; persistence is in scope for the package.

Motivation: owner needs this audit trail to support **R-AUTO** (auto-aplicación).

### R-AUTO — Auto-aplicación (requirement, owner / dueño, 2026-11-17)

**Toggle** (not a multi-option selector) that, when **on**, fully automates enroll for publications that get flagged `hay_mejores`, evaluating **all** criterios in this package (C1–C8 + canonical A). Used **under the responsibility of whoever enables it**.

| Rule | Detail |
| --- | --- |
| Effect | When the engine would flag/suggest and Auto is **ON**, it **enrolls that suggestion instead of flagging** (same rules). If there is **no enrollable promo** (e.g. C6 Premium unavailable), it **does not** invent an enroll — leaves the suggestion/banner path. |
| Responsibility | Explicit “bajo responsabilidad de quien lo active”. |
| Visible message while ON (decided 2026-11-17) | **Text under the toggle** while Auto-aplicación is **ON** (responsibility / what it will do). Appears whenever it is on — not a one-shot toast. No blocking modal. |
| Scope (decided 2026-11-17) | **Per MLA and bulk** on the filtered set — same pattern as the other criterios. |
| `hay_mejores_excluido` (decided 2026-11-17) | While excluded, MLA is **fully out of the hay_mejores circuit** — nothing is processed (no flag, C2/C6, table motor, or R-AUTO), even if Auto or other toggles are on. |
| What auto does (decided 2026-11-17) | Auto-aplicación does **not** invent a parallel path. When the engine would have **flagged** + shown a suggestion to the PM, with the toggle **ON** it **accepts that same suggestion automatically** and **enrolls** the promo that would have been suggested — **instead of flagging**. Same pick order / criterios motor as the manual suggestion. |
| Auto enroll failure (decided 2026-11-17) | If enroll **fails**, fall back to the **same suggestion/flag path as if Auto were OFF**, plus an added message: **“Autoapply falló”** + **the concrete failure reason**. Audit still records the failed auto attempt. |
| Auto vs manual | Distinction lives in **audit** (enroll + toggle logs): every apply records whether it was **auto** or **manual**. No extra per-apply UI toast required beyond that. |
| Scope of toggle | **Per MLA and bulk** (same as other criterios). |
| What is applied (decided 2026-11-17) | **1)** Auto-apply the **mejores condiciones** candidata (classic path) if any. **2)** Else, if we can **raise price** (C6 monopolio, when enabled) **and there is an enrollable action**, do that. **3)** On a **tie** between those paths, **mejores condiciones** wins. Among several classic slots that qualify, pick the one with **best markup** (same basis as status-quo / C1). |

Depends on lean audit (flag snapshot + enroll enrich) so every auto-run is reconstructible.

### Size / complexity estimate (2026-11-17, pricing_db)

Live scale: ~28k `ml_item_seller_promotions` rows, **~136 flagged**, ~6.6k promo enrolls / 30d, `raw` ~0.8–1.6 KB/row, `ml_write_log` enroll payload ~217 B.

| Approach | Eng complexity | Storage (order of magnitude) |
| --- | --- | --- |
| **Lean audit** — event only on flag **transition** (new flag / fingerprint change) + enrich enroll `ml_write_log` with status-quo + candidate snapshot (~1–2 KB JSON) | Medium: table/migration, hook in `actualizar` (skip no-op ticks), enrich write path, tests; optional panel “por qué” later | Flag: hundreds–low thousands events/mo → **≪ 100 MB/year**. Enroll enrich: tens of MB/year. Trivial vs DB size. |
| **Full dump** — store entire `raw` + costs on every event | Same hook + larger payload | Still small at this volume if transition-only |
| **Naive every boundaries tick** (~every 5 min × ~136 flagged) | Same write path, disastrous volume | ~GB/month territory — **do not** |

Recommendation: lean transition events + enroll enrich; never write when fingerprint/flag unchanged.

## What we are not doing (yet)

- Implementing until composition + persistence are decided.
- Assuming a dormant hay_mejores criteria table (none found 2026-11-16).
- Replacing layer A.

## Follow-up (parallel — not criterios scope unless owner pulls it in)

**Competencia bucket / cuotas bug (confirmed 2026-11-17 on `MLA2126104891`):**

- Intent: `same_bucket` = same `listing_type_id` **and** same cuotas (`_bucket_key` = `listing_type|installments`).
- Repro: our row is **Premium · 6 cuotas** (`gold_pro`); UI listed **22** Premium rows mixing **3 / 6 / 9 / 12** cuotas. Clásica (`gold_special`, 9 rows) was correctly hidden.
- Root cause: proxy stores `installments` as a bare number (`3`, `6`, …) but `_normalize_installments` only accepts a dict `{quantity, rate}`; on `int` it catches `AttributeError` and degrades to `"0"` → every Premium collapses to `gold_pro|0`.
- Fix: teach `_normalize_installments` to accept int/str quantity (rate 0), optional label fallback; refresh snapshots. **Small PR aparte** (or before Criterios table). Criterios competitor table must use the fixed bucket.

## Open questions

1. ~~C2 vs flag~~ → **Decided 2026-11-16**: C2 toggle **solo con markup positivo** vs **siempre**.
2. ~~R-AUTO message~~ → text under toggle while ON; auto/manual in audit.
3. ~~C1 markup basis~~ → **same markup as status-quo comparison**; must be inside C1 band when C1 is on.
4. ~~C2 “markup positivo”~~ → **ON**: suggest catalog-win only if markup **&gt; 0**; **OFF**: allow negative. Same markup basis as A/C1.
5. ~~Non-catalog MLAs~~ → **out of hay_mejores by default**. If a non-catalog MLA is in scope, it is **associated to a catalog MLA** and is treated **as catalog** for the whole process (same ranking/table path).
6. ~~C3–C5 / C7 / C8 auto-filters~~ → **competitor table** sole source; PM checks/unchecks; info columns; new sellers checked by default.
7. ~~C7 hard vs soft~~ → superseded (no weights; table only).
8. ~~Persistence~~ → `ml_hay_mejores_criterios` PK=`item_id` upsert; P2 adds excluded-sellers JSONB.
8b. ~~`hay_mejores_excluido`~~ → **fully out of the circuit**; nothing is processed (no flag, no C2/C6, no R-AUTO, no table motor) while excluded — even if other toggles are on.
9. ~~R-AUTO semantics~~ → instead of flagging, auto-accepts the **same** suggestion and enrolls. Trigger = whenever the engine would have flagged/suggested.
10. ~~R-AUTO enroll failure~~ → same suggestion as Auto OFF + message **“Autoapply falló”** + motivo.
11. ~~C6 gap / distancia~~ → both configurable; defaults **gap ≥ $5000**, **distancia $100**.
12. ~~C6 Premium not enrollable~~ → still enter circuit, no promo suggested, banner + motivo.
13. ~~Criteria change / recompute~~ → **new runs only**. Bulk apply of criterios may ask to discard open suggestions — default **No**. With Auto ON there should normally be **no** open suggestion except **Auto enroll failures**; those **must not** be cleared by that bulk discard. Dialog warns about Auto ON pubs.
14. ~~Scope of Auto-aplicación~~ → **per MLA and bulk**, same as the other criterios.

## Conversation log

- **2026-11-16**: Next large change = several criteria; likely new table unless deprecated design reusable.
- **2026-11-16**: Canonical apply rule stays; window **adds** limitations + catalog display.
- **2026-11-16**: Global (bulk on filter) or per MLA; UI toggle sharing Competencia col2.
- **2026-11-16**: Owner listed C1–C8 (markup clamp; win catalog; residual stock; international; low reputation; monopoly ceiling; Full; hide sellers by name). Documented and grouped above.
- **2026-11-16**: C2 composition → toggle like C6: **solo con markup positivo** vs **siempre**. Owner asked to clarify the C6 “separate signal” suggestion.
- **2026-11-16**: Owner: unsure whether C6 deserves a distinct flag. Agent lean: **not** a separate boolean by default — reuse flag (or a reason/subtype); separate flag only if the table needs its own filter/badge. Pending owner call.
- **2026-11-16**: C6 UX: same flag; different lead (“oportunidad de aumentar el precio… mantener posición”); if a promo assists, suggest it; else Premium at (2nd price − 100) editable. Agent: agrees; capture −100 / Premium / dual-reason priority as open.
- **2026-11-17**: Owner: “ranking after filters” = only which competitors count for 2nd place; markup follows the higher price. Dual classic-vs-C6 question was unclear — rephrase with example.
- **2026-11-17**: Dual case → **show both** blocks (classic + C6), not exclusive lead.
- **2026-11-17**: Order: candidatas above monopolio; monopolio only if C6 is enabled.
- **2026-11-17**: Lean audit (flag transition + enroll enrich) is an **in-scope requirement** of the criterios package; owner has one more requirement that depends on it.
- **2026-11-17**: **R-AUTO** — toggle Auto-aplicación (dueño): under enabler’s responsibility; on flag with hay_mejores + all new criteria, auto-apply; **log every toggle change**. Clarified: toggle, not selector.
- **2026-11-17**: R-AUTO pick order: **mejores condiciones** first; else monopolio raise; on tie → mejores condiciones. Among classic slots: **best markup**.
- **2026-11-17**: R-AUTO UX: non-blocking visible message **every time** toggle → ON; each auto-apply also leaves a quiet visible trace (surface TBD).
- **2026-11-17**: Clarified: message = **text under the toggle while ON**; auto vs manual = **audit only** (no per-apply UI toast required).
- **2026-11-17**: C1 uses the same markup as status-quo comparison; when C1 is active that markup must sit inside the band.
- **2026-11-17**: C2 toggle ON = only suggest catalog-win when markup &gt; 0; OFF = allow negative markup.
- **2026-11-17**: C3 stock residual threshold N configurable beside toggle; default **3**.
- **2026-11-17**: **Supersedes** auto C3–C5/C7/C8: competitor **table** is sole source of who counts (all checked by default; PM unchecks; PM responsibility). No soft weights.
- **2026-11-17**: Non-catalog MLAs ignored by hay_mejores by default; if present, they are associated to a catalog MLA and count as catalog.
- **2026-11-17**: R-AUTO = auto-accept the same suggestion and enroll **instead of flagging** (not a separate invent-apply path).
- **2026-11-17**: R-AUTO enroll fail → flag/suggestion as Auto OFF + “Autoapply falló” + reason.
- **2026-11-17**: C6 gap and target distance configurable; defaults ≥ $5000 and $100.
- **2026-11-17**: C6 Premium fail/unavailable → still enter circuit, no suggested promo, banner + reason.
- **2026-11-17**: `hay_mejores_excluido` → ignore MLA entirely; no processing while excluded.
- **2026-11-17**: Auto-aplicación scope = **per MLA + bulk**, like the other criterios.
- **2026-11-17**: Criteria changes apply to **new runs only**. Bulk criterios apply may ask to discard open suggestions on selected pubs (opt-in; default No).
- **2026-11-17**: Bulk discard: Auto ON normally has no open suggestion; **Auto-fail** suggestions are **exempt** from bulk discard; dialog warns for Auto ON.
- **2026-11-17**: Short edge rules OK (Auto+C6 sin promo; tabla vacía; asociación no-catálogo).
- **2026-11-17**: Confirmed bucket bug on `MLA2126104891`: numeric `installments` → all Premium share `gold_pro|0`.

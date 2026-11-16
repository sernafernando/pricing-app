# hay-mejores-baseline-started

Objective: When ML applies a started promo (Activa ahora = lowest-price started), hay_mejores compares candidates against that offer (price + markup), not against plain sale when prices diverge.
Branch: `feat/hay-mejores-baseline-started` (base `main`, not stacked on #2294)
Delivery: `stacked-to-main` (independent of candidatas-split)
Test runner: pytest unit; vitest pickPonerPreciosPromos / MejoresCandidatasBlock (CI only locally)

## Specs

S1: "cuando tiene algo aplicado deberia comparar contra lo que este aplicado, sea lo que fuere"
S2: "considera todas las posibles promos activas, no solo smart"
S3: (Chicho) Activa ahora = lowest-price `started` (same as `derivar_application_status` / FE `application_status === 'active'`); among those, best `nuestro_markup`.
S4: Comparison uses that promo's offer price as status-quo price and its markups; if none applied (or none with markup), keep plain `markup_para_precio(sale)` and sale price.
S5: FE `pickMejoresCandidatas` / `baselinePromo` stay in sync with BE `markups_baseline_vigente`.

## Tasks

- [x] T1 S1-S4 — BE baseline + listar compare price — route: inline — status: done
- [x] T2 S5 — FE baselinePromo + MejoresCandidatasBlock — route: inline — status: done
- [x] T3 S1-S5 — tests + ayuda/novedad — route: inline — status: done
- [x] T4 S3 — Chicho: min-price started (not best markup among all started); unstack from #2294

## Log

L1: User (MLA1609415777): SMART started 814999 ~12.10% vs sale 771149; suggested PRICE_MATCHING 764813 ~4.73% because baseline required price match ±$1.
L2: User: compare against applied whatever it is; all active promos not only SMART; Activa ahora = started; authorize implement.
L3: First ship used any started + best markup; stacked on #2294 split.
L4: Chicho (#2295): unstack from #2294; Activa ahora = lowest-price started (derivar_application_status); then markup tie-break; tests + docs.

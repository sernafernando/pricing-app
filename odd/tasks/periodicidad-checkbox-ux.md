# Periodicidad checkbox UX (P3.2)

Objective: EAN catalog respects Sin/Con criterio; detail is MLA checkboxes + tipo/lista/tienda filters; drop rules from UI; Todo el EAN shortcut. New-MLA notify = next slice.
Branch: `feat/promo-local-refresh-mirror`
Delivery: ask-on-risk · tests: pytest unit periodicidad + vitest periodicidadForm

## Specs

- S1: User: "estaria bueno que tambien filtren los eans por aquellos que al menos un mla tiene criterio aplicado"
- S2: User: "tienda tipo y lista sean filtros que me achiquen o agranden el listado de mlas y que haya un listado con checkboxes el mla, el tipo y la lista y tienda"
- S3: User accepted Todo el EAN shortcut; drop magic rules; "dejemos los checkboxes en lugar de un modo magico"
- S4: New-MLA notify/filter deferred to next slice (agent decision, user: "lo que te parezca mejor")
- S5: Legacy `scope_mode=rules` still loadable from API; UI offers convert via all/mlas save (no new rules writes from UI)

## Tasks

- T1 S1 — backend catalog `criterios_aplicados` EAN EXISTS — inline — done
- T2 S2 — MLA catalog fields + FE filters/checkboxes — inline — done
- T3 S3 — remove rules from UI; Todo el EAN — inline — done
- T4 S1-S3 — tests + docs + commit — inline — in progress

## Log

- L1: User accepted criterios EAN filter + checkbox UX; drop rules; prefer checkboxes over magic; new MLA notify later; "lo que te parezca mejor a vos hagamos"
- L2: Implemented P3.2; pytest 8 pass; vitest periodicidadForm 5 pass; nuevos deferred

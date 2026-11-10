# Publicaciones ML — Ver competencia (wide panel)

## Intent

When the operator clicks **Ver competencia** on the publication Promos panel, the panel expands to **wide** mode. The extra width is **not** used to stretch Promos fields.

## Layout

| Region | Behavior |
| --- | --- |
| Column 1 (Promos) | Same compact width and field layout as the narrow panel (≈420px). Promo rows, hay_mejores suggestions, LIGHTNING stay here unchanged. |
| Column 2 (Competencia) | New column that consumes the extra wide space. Catalog ranking for this publication tranche (`same_bucket`). |

## Column 2 content

Dense ranked table from stored snapshot field `same_bucket` (all same-bucket competitors, **no** `is_cheaper_than_us` filter; sorted by `price_ars`). Legacy `undercutting` stays for Productos tree.

- `#` — position
- **Nombre** — competitor title / seller (truncated)
- **Precio** — monospace
- **Markup %** — monospace, plus **c/ sell in/out** under it when the product has sell in / sell out today (same basis as promo rows in column 1)

Also show `fecha_consulta` and **Actualizar** (`promos.ver`). Highlight our own listing row. Toggle label becomes **Ocultar competencia**.

## Stitch

- Project: `3755131242097604736`
- Screen (v2 wide): `c5cba5e2992c495f8f6a236079632210`
- PNG: `stitch-v2-wide-competencia.png`

## Implementation notes

- API: `same_bucket` on `GET/POST …/catalogo-competencia/{mla}` (full bucket ranking); `undercutting` unchanged.
- FE: `Ver competencia` → `SplitPanelLayout` `width=xl` + `expanded` (lifts 42vw cap); Promos col1 compact, col2 ranking.
- Stitch inventado chrome is not implemented.

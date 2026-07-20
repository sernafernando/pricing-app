# Product Color Teams — Frontend Data Contract

Backend reference for `productos-color-teams` (PR1–PR4). Rendering choices
(dot vs. badge, layout, styling) are entirely the frontend's call — this
document only describes the data shape and API surface.

## Layer selector data source: `GET /api/equipos`

Response: array of teams the current user belongs to, plus the global ("U")
team.

```json
[
  { "id": 1, "nombre": "Global", "es_global": true },
  { "id": 7, "nombre": "Ventas ML", "es_global": false }
]
```

Use this to populate a selector such as "View colors of: Mine / Team X /
Global":

- The entry with `es_global: true` is always present (implicit membership —
  every user can view/write it, subject to the existing
  `productos.marcar_color` permission).
- All other entries are teams where the user has an explicit
  `equipo_miembro` row (any `rol`).

## `equipo_id` query param on product list/read endpoints

Product listing/detail endpoints (`productos_listing.py`, `productos.py`,
etc.) accept an optional `equipo_id` query param to select which team's
color layer is read:

- Omitted → resolves to the global ("U") team (today's default behavior,
  unchanged).
- Set to the global team's id → always allowed.
- Set to any other team id → the caller must be a member of that team, or
  gets `403`.

## Row payload color fields (PR3)

Each product row in list/detail responses now includes:

| Field | Meaning |
|---|---|
| `color` | The active layer's fill color (the layer resolved by `equipo_id`, see above). This is what should render as the marked color for the current view. |
| `color_hint_global` | The global ("U") team's color for this product, used to render a hint dot in an otherwise-empty cell when viewing a non-global team layer that hasn't marked this product. |
| `color_hint_equipo_inicial` | The initial letter of the team name that has this product marked, for a hint badge — helps a user viewing one layer notice "team X already marked this." |

## Write endpoints accept `equipo_id` (default global)

`PATCH /productos/{item_id}/color`, `PATCH /productos/{item_id}/color-tienda`,
`POST /productos/actualizar-color-lote`, `POST
/productos/actualizar-color-tienda-lote` all accept an optional `equipo_id`
(query param for the two PATCH endpoints, body field for the two batch
endpoints). Omitted → defaults to the global ("U") team, and existing
`{color}`-only calls remain fully backward-compatible (they still write the
global layer and legacy `productos_pricing.color_marcado[_tienda]` columns,
same as before PR1).

## Team management (PR4)

`POST /api/equipos`, `GET /api/equipos/{id}/miembros`, `POST
/api/equipos/{id}/miembros`, `PATCH /api/equipos/{id}/miembros/{usuario_id}`,
`DELETE /api/equipos/{id}/miembros/{usuario_id}`, `PATCH /api/equipos/{id}`,
`DELETE /api/equipos/{id}` — team CRUD and membership management. Any
authenticated user may create a team (becomes its admin); only a team's
admin can manage membership, rename, or delete it. The global team rejects
all of these (`400`, "implicit membership").

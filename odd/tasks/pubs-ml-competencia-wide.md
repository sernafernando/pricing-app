# pubs-ml-competencia-wide

Objective: Ver competencia expands the publication Promos panel to wide; extra width is column 2 with same-bucket catalog ranking (nombre, precio, markup). Stitch inventado chrome is out of scope.
Branch: `feat/pubs-ml-promos-competencia-catalogo`
Delivery: ask-on-risk (base `main`)
Test runner: `pytest` (backend unit) + `pnpm test` focused (frontend)

## Specs

S1: "el boton de \"ver competencia\" amplie el panel a modo wide pero en lugar de estirar y mover los campos para acomodarse al espacio extra, que ese espacio extra se use como una columna dos en el panel y ahi figure el ranking del catalogo para ese tramo de publicaciones, con el nombre, el precio, y el markup"
S2: "si eso no rompe nada, esta aprobado" — layout approved; Stitch invented chrome must not be implemented
S3: "is_cheaper_than_us no quiero exclusivamente los is cheaper than us, quiero todos los del mismo bucket sin restriccion de precio"
S4: Keep existing `undercutting` behaviour for Productos tree (product decision #6) unchanged
S5: Ranking is read from the stored snapshot — no new MeLi fetch for the list filter

## Tasks

- [x] T1 S3-S5 — Backend: `same_bucket_competitors` + expose on snapshot API — route: inline — commit: pending
- [x] T2 S1-S2 — FE: Ver competencia / Ocultar + SplitPanel wide + Promos two columns — route: inline — commit: pending
- [x] T3 S1 — Ayuda Publicaciones ML — route: inline — commit: pending

## Log

L1: User — Ver competencia wide col2 ranking; then approved inventado-if-ignored; then same-bucket without cheaper filter.

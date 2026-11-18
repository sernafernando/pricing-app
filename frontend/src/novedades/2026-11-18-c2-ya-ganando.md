# C2 no flagea si ya ganás el catálogo

**Fecha:** 2026-11-18

**Resumen ejecutivo:** con **C2 — Ganar catálogo** prendido, si tu precio vigente **ya es #1** en el ranking efectivo, el sistema **no** te marca “hay mejores” con promos peores. El criterio queda armado y, en **Criterios de aplicación**, ves un aviso **Ya estás ganando el catálogo…** hasta que dejes de ganar.

## Qué cambia

1. C2 solo suma al flag cuando el status quo **no** gana el catálogo (mismos rivales tildados que en Ver competencia).
2. Si ya ganás, el toggle puede seguir ON: en cuanto pierdas el #1, C2 vuelve a buscar una promo que te recupere la posición.
3. El aviso aparece en la columna de criterios mientras C2 está prendido y el snapshot diga que seguís ganando.

# OpenSpec — Pricing App

Este directorio contiene changes/specs en formato Spec-Driven Development (SDD).

## Estructura

```
openspec/
├── changes/                    # Cambios en curso (por feature/refactor)
│   └── <change-id>/
│       ├── proposal.md         # Why / What / Scope / Risks
│       ├── tasks.md            # Checklist de implementación
│       ├── design.md           # Decisiones técnicas y diagramas
│       ├── specs/              # Delta specs (por capability)
│       └── state.yaml          # Estado SDD (fase, status, decisiones)
└── specs/                      # Specs consolidadas (post-archive)
```

## Modo de persistencia

Este repo usa **hybrid**: los artefactos se persisten en Engram (memoria) y también se materializan como archivos acá. Engram es la fuente primaria para recuperación cross-session; los archivos son la referencia humana versionable en git.

## Fases

1. `explore` → investigación previa (solo Engram)
2. `proposal` → `proposal.md` + `state.yaml`
3. `spec` → `specs/*.md` (delta por capability)
4. `design` → `design.md`
5. `tasks` → `tasks.md`
6. `apply` → implementación (código real)
7. `verify` → validación contra specs
8. `archive` → merge a `openspec/specs/` y cierre

## Changes activos

- `modulo-compras` — Módulo de compras (pedidos, OPs, CC proveedor, imputaciones). Fase: proposal.

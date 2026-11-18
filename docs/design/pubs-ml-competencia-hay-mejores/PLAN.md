# Plan — Criterios de aplicación + auditoría + Auto-aplicación

Source of truth for decisions: [CRITERIOS-APLICACION.md](./CRITERIOS-APLICACION.md). Competencia col2 UX: [UX.md](./UX.md).  
Baseline canónico ya shipped (#2294 / #2295).

**Ship scope (this PR):** C1, C2, competitor table (tildes), auditoría lean, R-AUTO. **C6 (monopolio) is deferred to its own PR** — do not treat C6 sections below as in-scope for the Criterios ship.

## 1. Objetivo

Mantener la regla canónica de hay_mejores y sumar:

1. **Criterios de aplicación** (limitaciones / caminos extra + catálogo).
2. **Auditoría lean** (flag + apply reconstruibles).
3. **Auto-aplicación** (toggle bajo responsabilidad del PM).

## 2. Capas (no reemplazan lo canónico)

| Capa | Qué |
| --- | --- |
| **A — Canónico** (shipped) | `es_mejor_oferta`: markup↑ mismo precio; markup≥ precio más bajo; nunca precio más alto. Baseline = Activa ahora; sell-in/out solo si ambos lados lo tienen. |
| **B — Criterios** | C1–C8 configurables (global bulk sobre filtro y/o por MLA). |
| **C — Catálogo + UI** | Snapshot fresco alimenta B; panel Criterios muestra reglas + contexto. |

## 3. UI panel

- Botón **Criterios de aplicación** junto a **Ver competencia**.
- Misma columna derecha: abrir uno **cierra** el otro; cerrar el activo quita la columna.
- Mismo flag `hay_mejores_ofertas`; no flag aparte para monopolio.
- Si hay candidatas clásicas **y** monopolio: **mostrar ambos** bloques; **candidatas arriba**; monopolio **solo si C6 está activado**.

### Copy monopolio (C6)

En lugar del lead clásico, tono: *“Tenés oportunidad de aumentar el precio en $XXXX con X% de markup y mantener tu posición en el catálogo.”*

- Si hay promo que asiste → sugerirla.
- Si no → Premium editable a *(precio 2º efectivo − distancia objetivo)*; default distancia **$100**.
- “2º efectivo” = después de filtrar competidores (C3–C5, C7–C8).

## 4. Criterios (C1–C8)

| ID | Nombre | Resumen |
| --- | --- | --- |
| **C1** | Límite de markup | Floor y/o techo; fuera de rango no es “mejor” aunque pase A. |
| **C2** | Ganar catálogo | Promo que gana catálogo (ranking efectivo). Toggle **solo markup positivo**: ON → markup &gt; 0; OFF → permite negativo. Catálogo fresco obligatorio. **2026-11-18**: solo flagea si el status quo **no** es ya #1; si ya ganamos, toggle ON + banner UI, sin flag de promos peores. |
| **C3–C5, C7–C8** | Tabla de competidores | **Única** fuente de quién cuenta. Columnas informativas (Full, intl, stock, reputación, …). Todos tildados por defecto; el PM destilda. Responsabilidad del PM. |
| **C6** | Techo monopolio | Ganando + gap al 2º **entre tildados** ≥ gap mín (default **$5000**) → subir. Distancia objetivo al 2º configurable (default **$100**). Toggle: solo vía promo vs cualquier caso. |

Dependencia: catálogo → tabla (tildados) → ranking efectivo → C2 y C6. Canónico A + C1 → candidatas clásicas.

## 5. Auditoría lean (requirement)

Hoy **no** alcanza (flag overwrite; markups de flag no se guardan).

Incluir en el paquete:

1. **Evento en transición de flag** (flag on o fingerprint nuevo): timestamp, status quo (precio, markups, Activa ahora), candidatas (key, precio, markups), versión de reglas. **No** escribir en ticks no-op de boundaries.
2. **Enrich de enroll** (`ml_write_log` u store unificado): status quo al click + candidata + precios/markups vistos vs aplicados.
3. **Log de cada cambio del toggle Auto-aplicación** (quién, cuándo, old→new, alcance).
4. Auto-applies marcados (`auto_aplicacion=true` / actor sistema) ligados al snapshot del flag.

Escala actual (~136 flageadas, ~6.6k enrolls/mes): espacio trivial si es por transición; **prohibido** auditar cada tick de 5 min.

## 6. R-AUTO — Auto-aplicación (requirement dueño)

- **Toggle** (no selector), bajo responsabilidad de quien lo active.
- Mientras el toggle está **ON**: **texto debajo del toggle** (responsabilidad / qué hace). No toast one-shot.
- Auto vs manual queda en **auditoría** de cada apply + log de cambios del toggle (sin toast por cada auto-apply).
- Con toggle **ON**: cuando el motor habría **flageado** + sugerido al PM → **acepta esa misma sugerencia** y **enrola** esa promo **en lugar de flagear**. Mismo motor / pick order.
- Alcance del toggle: **por MLA y bulk**, igual que el resto de criterios.
- Si enroll auto **falla** → misma sugerencia que con Auto OFF + mensaje **“Autoapply falló”** + motivo.

**Orden de pick:**

1. Candidata de **mejores condiciones** (camino clásico), si hay.
2. Si no, **subir precio** (C6) si aplica y está habilitado.
3. Empate entre caminos → gana **mejores condiciones**.
4. Varias slots clásicas → la de **mejor markup**.

## 7. Entregas sugeridas (orden de implementación)

| Slice | Contenido | Notas |
| --- | --- | --- |
| **P0** | Persistencia criterios + UI col2 Criterios (toggle mutual con Competencia) + C1 | Valor sin catálogo |
| **P1** | Auditoría lean (flag transition + enroll enrich + log toggle auto) | Piso para R-AUTO y “por qué” |
| **P2** | Tabla competidores (persistencia tildes) + ranking efectivo + C2 | Gates de datos ML para columnas |
| **P3** | C6 UX (doble bloque, gap/distancia configurables, toggles) | Mismo flag |
| **P4** | R-AUTO worker/hook post-flag + confirm responsabilidad | Depende P1 + motor criterios |
| **P5** | Bulk aplicar criterios / auto sobre filtro; ayuda + novedad | Cierre producto |

PRs a `main`, slices ~≤400 líneas. Cambio de criterios → **solo corridas nuevas** (sin recompute automático de flageadas). Bulk criterios: confirm opcional para descartar sugerencias abiertas del filtro.

## 8. Abierto (no bloquea el plan, sí el detalle)

- ~~Bug cuotas~~ → [#2308](https://github.com/sernafernando/pricing-app/pull/2308) (read-time bucket; no bloquea este stack).
- ~~Persistencia~~ → tabla nueva **`ml_hay_mejores_criterios`** PK=`item_id` (upsert sparse, estilo `ml_item_overrides`): C1/C2/C6/Auto (+ gap/distancia); P2 agrega JSONB de sellers destildados. **No** reutilizar `offset_grupo_filtros` ni `seller_promotions.raw`.
- ~~Alcance Auto~~ → por MLA + bulk.
- ~~Recompute al cambiar criterios~~ → solo corridas nuevas; bulk puede ofrecer descartar sugerencias abiertas (default No); **no** limpia sugerencias por fallo de Auto; aviso si hay Auto ON.
- ~~Base de markup de C1~~ → misma que status quo; dentro del rango si C1 activo.
- ~~“markup positivo” en C2~~ → ON: solo si markup &gt; 0; OFF: permite negativo.
- ~~Familia 3 auto-filtros / C7 pesos~~ → **tabla** única fuente; PM destilda; sellers nuevos tildados.
- ~~MLA no-catálogo~~ → fuera de hay_mejores por defecto; si entra, es por asociación a una de catálogo (= tratar como catálogo).
- ~~Trigger auto~~ → mismo momento en que se habría flageado/sugerido; enroll en lugar de flag.
- ~~Fallo enroll auto~~ → sugerencia como Auto OFF + “Autoapply falló” + motivo.
- ~~Gap / −100 C6~~ → configurables; defaults gap **≥ $5000**, distancia **$100**.
- ~~Premium no enrollable~~ → entra al circuito C6 sin promo sugerida; cartel + motivo.
- ~~`hay_mejores_excluido`~~ → fuera del circuito por completo; no se procesa nada mientras esté excluida.

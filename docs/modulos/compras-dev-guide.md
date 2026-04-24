# Módulo de Compras — Guía técnica para devs

> **Audiencia:** backend + frontend devs que tocan el módulo.
> **Objetivo:** que cualquier dev nuevo pueda entender el módulo en
> ≈ 1 hora de lectura + 30 min de exploración del código.

---

## 0. Antes de leer

Este doc NO reemplaza al design. Lo complementa con el foco en:

- Dónde está cada pieza (archivos reales, no diagramas).
- Cómo fluye una operación desde el click hasta la DB.
- Qué invariantes NO se deben romper y por qué.

Docs padre:

- `openspec/changes/modulo-compras/proposal.md` — qué y por qué.
- `openspec/changes/modulo-compras/design.md` — decisiones (D1..D22),
  riesgos (RD1..RD10), refinements.
- `openspec/changes/modulo-compras/specs/*.md` — 9 delta specs con 49+
  requirements y scenarios.

---

## 1. Arquitectura — alto nivel

```
┌───────────────────────────────────────────────────────────────────────┐
│                          Frontend (React)                              │
│  /administracion/compras  → AdministracionCompras.jsx (5 tabs)         │
│     TabPedidos  TabOPs  TabCCProv  TabRecon  TabSaleDocCatalog         │
│     Modales: ModalPedido(Compra|Detalle)                               │
│              ModalOrdenPagoNueva, ModalEjecutarPago                    │
│     Hooks:   useComprasPedidos  useComprasOP  useCCProveedor           │
└─────────────────────────────────┬─────────────────────────────────────┘
                                  │ HTTPS + JWT
                                  ▼
┌───────────────────────────────────────────────────────────────────────┐
│      Backend router: /api/administracion/compras  (28 endpoints)       │
│   backend/app/routers/administracion_compras.py (~1100 LOC)            │
└───────────────────────────────────────────────────────────────────────┘
           │                     │                       │
           ▼                     ▼                       ▼
  ┌────────────────┐   ┌────────────────────┐   ┌────────────────────┐
  │  Services      │   │  Integraciones      │   │  Cron jobs         │
  │ pedidos_svc    │◀─▶│ CajaService          │   │ reconciliar_cc... │
  │ ordenes_pago   │◀─▶│ PermisosService      │   │ sync_ct_guid (hook)│
  │ imputaciones   │   │ erp_matching_service │   │                    │
  │ cc_proveedor   │   │ sale_document_class  │   │                    │
  │ numeracion     │   │                      │   │                    │
  └────────────────┘   └────────────────────┘   └────────────────────┘
           │                     │                       │
           └─────────────────────┴───────────────────────┘
                                 │
                                 ▼
                       ┌──────────────────┐
                       │  PostgreSQL       │
                       │  14 migraciones   │
                       │  Vista filtrada   │
                       └──────────────────┘
```

### Flujo fundamental (pedido → OP → pago)

```
1. PM crea pedido (POST /pedidos)
   ↓
2. Numeración: SELECT FOR UPDATE en numeracion_contadores
   ↓
3. INSERT en pedidos_compra con estado='borrador'
   ↓
4. Evento 'pedido_creado' en compras_eventos (polimórfico)
   ↓
5. PM envía a aprobación (POST /pedidos/:id/enviar-aprobacion)
   → estado='pendiente_aprobacion' + evento
   ↓
6. Aprobador aprueba (POST /pedidos/:id/aprobar)
   → estado='aprobado'
   → INSERT cc_proveedor_movimientos (DEBE)
   → Evento 'pedido_aprobado'
   ↓
7. PM crea OP (POST /ordenes-pago)
   → check anti-duplicado ERP (puede explotar 409)
   → INSERT ordenes_pago con estado='creada'
   → INSERT imputaciones (modo específica) o nada (a cuenta)
   → Evento 'op_creada'
   ↓
8. Tesorería ejecuta pago (POST /ordenes-pago/:id/pagar)
   → validación caja.moneda == op.moneda (422 si falla)
   → CajaService.registrar_movimiento (egreso)
   → CajaService.crear_documento (entidad_tipo='orden_pago')
   → INSERT N cc_proveedor_movimientos (HABER por imputación)
   → UPDATE ordenes_pago.estado='pagada'
   → UPDATE pedidos_compra.estado='pagado' (si cubierto)
   → Evento 'op_pagada'
   ↓
9. Post-pago: el pedido aparece en CC con saldo 0 y en la caja como egreso
   con link "Ver OP" que navega al tab OPs con el op_id como query param.
```

---

## 2. Modelo de datos

### Tablas nuevas (8)

| Tabla                            | Rol                                             | Append-only? |
| -------------------------------- | ----------------------------------------------- | ------------ |
| `pedidos_compra`                 | Pedidos (estado machine de 7 estados).          | ❌           |
| `compras_eventos`                | Timeline polimórfico (pedido + OP + imput.).    | ✅           |
| `ordenes_pago`                   | OPs (estado machine de 3 estados).              | ❌           |
| `imputaciones`                   | Vínculos origen-destino (reversals son nuevas filas). | ✅    |
| `cc_proveedor_movimientos`       | Libro mayor propio (DEBE/HABER por proveedor).  | ✅           |
| `numeracion_contadores`          | Contador PK=(tipo, empresa_id, anio).           | ❌           |
| `tb_sale_document`               | Catálogo del ERP (seed estático ~43 filas).    | ❌ (manual)  |
| `cc_reconciliacion_log`          | Log diario de la reconciliación automática.     | ✅           |

### Tabla modificada

- `etiquetas_envio`: se extendió con `tipo_envio`, `proveedor_id`,
  `proveedor_direccion_id`, `pedido_compra_id` (todas nullable → backward
  compatible con etiquetas de venta existentes). Migración en 2 pasos
  (RD1): primero los nullables, después el `cliente_id` queda nullable
  (para etiquetas de compras que no tienen cliente).

### Vista SQL

- `v_facturas_compra_vigentes` — filtra de `tb_commercial_transactions` las
  facturas **vigentes** (ni anuladas ni contrapartes, por matching de
  `ct_docnumber` y `sd_isannulment`). Es la fuente de verdad financiera
  para el matching ERP — el clasificador Python es sólo auditoría puntual.

### Invariantes (NO romper)

1. **Append-only:** `imputaciones`, `compras_eventos`,
   `cc_proveedor_movimientos`. CERO UPDATE, CERO DELETE sobre estas tablas.
   Las "correcciones" son filas nuevas (reversals).

2. **Numeración correlativa por (tipo, empresa_id, anio):** siempre vía
   `numeracion_service.generar_siguiente_numero()` que hace SELECT FOR
   UPDATE. Nunca calcular el siguiente número desde SQL suelto.

3. **Moneda caja == moneda OP** al ejecutar pago. La validación está en
   `ordenes_pago_service.ejecutar_pago` — si intentás saltarla vas a
   corromper la CC (saldo en la moneda equivocada).

4. **1 fila de estado por OP en `ordenes_pago`** — NO clonar la OP al
   anular. La anulación se expresa como evento + reversals de imputaciones
   + caja; la OP queda como `estado='anulada'`.

5. **Seed tb_sale_document vía Alembic, NO vía script.** El refinement
   2026-04-17 eliminó el sync automático. Para agregar tipos nuevos:
   nueva migración `compras_NNN_seed_tb_sale_document_extra.py`.

---

## 3. State machine — pedidos

```
                    enviar_aprobacion
         ┌─────────┐                  ┌────────────────────┐
         │         │─────────────────▶│                     │
┌────────│BORRADOR │                  │PENDIENTE_APROBACION │──aprobar──┐
│ cancelar│        │◀────rechazar─────│                     │           │
│        └─────────┘  (vuelve_borrador)└────────────────────┘           │
│             │                                  │                      │
│             │                                  │ rechazar              │
│             ▼                                  │ (cancela)             ▼
│        ┌────────┐                              │                ┌──────────┐
└───────▶│CANCELAD│◀─────cancelar_aprobado───────│                │ APROBADO │
         └────────┘     (reverso CC)             │                └──────────┘
                                                 ▼                      │
                                            ┌────────┐                  │
                                            │CANCELAD│                  │
                                            └────────┘                  │
                                                                        │ pagar (impl.
                                                                        │ via OP)
                                                                        ▼
                                                                   ┌─────────┐
                                                                   │ PAGADO  │
                                                                   └─────────┘
```

Implementado en `pedidos_compra_service.py` con dict `TRANSICIONES_VALIDAS`.
Cada transición genera un evento en `compras_eventos` con
`tipo_evento='transicion_estado'` y metadata.

---

## 4. Clasificador semántico (sale_document)

**Problema:** el ERP tiene ~43 tipos de documento (`tb_sale_document`) y
nuestro código tiene que saber cuál es una factura de compra, cuál una
anulación, cuál una contraparte. Hardcodear IDs era frágil (cambian sin
aviso).

**Solución:** 5 predicados flag-based en `sale_document_classifier.py`:

```python
clasificar_documento_compra(sd, session=None) -> Literal[
    "factura", "nota_credito", "nota_debito", "anulacion",
    "contraparte", "orden_pago", "remito", "ajuste",
    "orden_pago_rechazada", "ignorar", "unknown"
]

afecta_cc_proveedor(sd, session=None) -> bool
signo_contable(sd) -> Literal[1, -1]     # lee sd.sd_plusorminus
es_anulacion(sd) -> bool                  # sd.sd_isannulment
es_contraparte(sd, session) -> bool       # busca par en tb_sale_document
                                          # con mismo hacc_group y
                                          # plusOrminus opuesto
```

### 5 predicados y prioridad

```
1. es_anulacion(sd)        → retorna "anulacion"
2. es_contraparte(sd, session)  (solo si session)  → "contraparte"
3. sd.sd_ispurchase + sd.sd_iscreditnote → "nota_credito"
4. sd.sd_ispurchase + sd.sd_isdebitnote  → "nota_debito"
5. sd.sd_ispurchase (resto)              → "factura" / "remito" / "ajuste"
6. sd.sd_isbanking + sd_id=106           → "orden_pago"
...
```

### SD_IDS_AMBIGUOS

Hay un set `SD_IDS_AMBIGUOS` (sd_id 124, 125, 128, 129) que por sus flags
podrían clasificarse de múltiples formas. El clasificador los mapea
explícitamente al comportamiento elegido por el equipo (documentado en el
código + design §4).

### Por qué session es opcional

Paso 3 (`es_contraparte`) requiere una query adicional a
`tb_sale_document` para buscar el par. En hot paths (matching masivo) no
queremos queries N+1 → se pasa `session=None` y se salta ese paso.

La vista SQL `v_facturas_compra_vigentes` ya filtra contrapartes a nivel
DB usando otro mecanismo (CTE con `plusOrminus` invertido y `ct_docnumber`
compartido). Entonces el clasificador Python no necesita detectar
contrapartes en el flujo financiero — sólo en dashboards/auditoría donde
el costo de la query no importa.

---

## 5. Matching ERP

### 5.1 Forward (pedido → factura ERP)

`erp_matching_service.match_forward(pedido_id) -> list[dict]`

Busca en `v_facturas_compra_vigentes` facturas candidatas:

- Mismo `supp_id` (proveedor del pedido mapeado al supp_id del ERP).
- Rango de fechas (ct_date >= pedido.fecha_creacion ± ventana).
- Monto aproximado (≤ 2% delta).
- No ya matcheada por otro pedido.

### 5.2 Backward (factura ERP → pedido)

Hook en `sync_commercial_transactions_guid.py`: cada vez que entra una
factura nueva, intenta matchearla contra pedidos aprobados no pagados
del mismo proveedor. Si encuentra match único → autoimputación tentativa
con flag `sugerida=true` que el usuario confirma.

### 5.3 Vista v_facturas_compra_vigentes

- **Input:** `tb_commercial_transactions` + `tb_sale_document`.
- **Filtros:**
  - `sd_ispurchase=true`
  - NOT `sd_isannulment`
  - `ct_iscancelled=false`
  - Excluye contrapartes (CTE con par por `ct_docnumber` + `hacc_group`).
  - Excluye ajustes explícitamente no-financieros.
- **Output:** 1 fila por factura vigente con clasificación pre-calculada.

Implementada como vista normal (no materialized) en v1 — se re-evalúa en
cada query. Si escala (> 100k facturas/año) considerar migrate a
materialized view con refresh cada 10 min.

---

## 6. Anti-doble-contabilización

Problema: el usuario carga una OP en la app **y** además la carga
directamente en el ERP (o viceversa). El pago se contabiliza 2 veces.

### Dos capas de defensa

1. **Banner UI (UX):** `ModalOrdenPagoNueva.jsx` muestra un banner rojo
   dismissable arriba del form:
   > "Si este pago ya se registró directamente en el ERP, NO lo cargues
   > aquí. Se contabilizaría dos veces."

   Storage: `sessionStorage.compras_op_doble_contab_banner_dismissed_{userId}_{YYYYMMDD}`.
   Se reinicia cada día naturalmente (la key incluye la fecha).

2. **Detección server-side (HTTP 409):** en
   `POST /ordenes-pago` el service `ordenes_pago_service.crear` primero
   corre `detectar_duplicado_erp(supp_id, ct_docnumber, ct_date_limit)`
   que busca en `tb_commercial_transactions`:

   - `sd_id=106` (Orden de Pago ERP)
   - mismo `supp_id`
   - `ct_docnumber` coincide con algún `numero_factura` del body
   - `ct_date >= today - 7 días`
   - NOT `ct_iscancelled`

   Si match → HTTP 409 con payload estructurado:
   ```json
   {
     "codigo": "POSIBLE_DUPLICADO_OP_ERP",
     "mensaje": "Detectamos una OP en el ERP para esta factura...",
     "duplicados_detectados": [
       {"ct_transaction": 12345, "ct_date": "2026-04-18", "ct_docnumber": "00389000", "ct_total": "150000.00"}
     ]
   }
   ```

   El frontend abre modal → si el usuario confirma, reenvía con
   `confirmar_duplicado=true` → backend salta la validación y registra
   evento `op_creada_con_duplicado_confirmado` en `compras_eventos`.

### Gotcha: exception handler (F7 fix)

En F5 el handler global stringificaba los dicts con clave `codigo`, y los
tests validaban con `'POSIBLE_DUPLICADO_OP_ERP' in str(body)` lo cual
"funcionaba" por accidente. En F7 se arregló para preservar el dict
estructurado como raíz del body (usando `jsonable_encoder` para datetime/
Decimal). Backward-compat: dicts con clave `code` (inglés, resto del
proyecto) siguen envueltos en `{error:{...}}`.

---

## 7. Reconciliación

### 7.1 Algoritmo

`reconciliar_cc_proveedor.py` (cron 03:00 AM):

```
for proveedor in proveedores_con_movs_ultimos_365d:
    for moneda in ('ARS', 'USD'):
        saldo_propio = sum(cc_proveedor_movimientos.signo * monto)
        saldo_erp = cuentas_corrientes_proveedores.saldo
        delta = |saldo_propio - saldo_erp|
        tolerancia = leer_configuracion('compras.cc_reconciliacion_tolerancia_{moneda}')
        if delta > tolerancia:
            insert cc_reconciliacion_log (divergencia)
            crear alerta banner
            notificar usuarios con ver_cuentas_corrientes
        else:
            insert cc_reconciliacion_log (ok)
```

### 7.2 Tolerancia configurable por moneda

La tabla `configuracion` (preexistente, k/v generic) tiene las claves:

- `compras.cc_reconciliacion_tolerancia_ars` (default 100.00)
- `compras.cc_reconciliacion_tolerancia_usd` (default 1.00)

Leídas vía `app.schemas.configuracion_compras.leer_configuracion()` con
fallback a defaults. Editables desde admin UI (Cierre 2 del usuario).

### 7.3 Idempotencia

Constraint UNIQUE `(fecha_corrida, proveedor_id, moneda)` en
`cc_reconciliacion_log`. Re-correr con la misma fecha explota en el flush
y rollbackea (no hay duplicados). Útil si el cron corre y falla a mitad
de camino — se puede re-ejecutar sin lastimar nada.

---

## 8. Append-only — por qué y cómo

### Por qué

- **Auditoría:** nada se borra, todo se puede reconstruir.
- **Reconciliación futura:** podemos comparar "estado a fecha X" sin
  arquear sobre backups.
- **Concurrencia:** INSERTs no generan locks de escritura en filas
  existentes (UPDATE sí).

### Cómo se expresa una corrección

**Ejemplo 1 — desimputar:**

```sql
-- Imputación original (monto=5000)
INSERT INTO imputaciones (origen_tipo, origen_id, destino_tipo, destino_id, monto, ...)
  VALUES ('orden_pago', 10, 'pedido_compra', 33, 5000.00, ...);

-- Desimputación = reversal (monto negativo o flag 'reversal')
INSERT INTO imputaciones (origen_tipo, origen_id, destino_tipo, destino_id, monto, reversal_de_id, motivo_reversal, ...)
  VALUES ('orden_pago', 10, 'pedido_compra', 33, -5000.00, {id_original}, 'motivo...');
```

Saldo efectivo = suma de todas las filas → si hay imput + reversal, neto = 0.

**Ejemplo 2 — reverso de CC por cancelación de pedido aprobado:**

```sql
-- Al aprobar pedido (INSERT DEBE)
INSERT INTO cc_proveedor_movimientos (proveedor_id, moneda, tipo, monto, entidad_tipo, entidad_id, ...)
  VALUES (5, 'ARS', 'debe', 50000, 'pedido_compra', 33, ...);

-- Al cancelar pedido aprobado (INSERT HABER tipo 'ajuste')
INSERT INTO cc_proveedor_movimientos (proveedor_id, moneda, tipo, monto, entidad_tipo, entidad_id, categoria, ...)
  VALUES (5, 'ARS', 'haber', 50000, 'pedido_compra', 33, 'ajuste_cancelacion', ...);
```

### Regla

Si en el service ves un `session.query(Imputacion).update(...)` o
`session.delete(imputacion)` → **BUG**. Reportarlo y reemplazarlo por
un INSERT compensatorio.

---

## 8.5 Post-PR #606 — CC funcional + cambios quirúrgicos

Estado del módulo después del PR #606 + batch de limpieza. Leer esta
sección si el doc base (secciones 1-8) quedó corto o si hay ambigüedad
con commits viejos.

### 8.5.1 CC funcional (cockpit del proveedor)

`TabCCProveedores` dejó de ser solo consulta: es el **punto único de
entrada** para operar sobre un proveedor. Acciones A-H:

| Acción | Entrypoint UI                       | Endpoint/Modal                  |
| ------ | ----------------------------------- | ------------------------------- |
| A      | Botón "Aplicar NC" en imputaciones  | `ModalAplicarNC`                |
| B      | Botón "+ Nueva OP"                  | `ModalOrdenPagoNueva`           |
| C      | Desimputar/reimputar (panel integr.)| `PanelImputaciones`             |
| D      | Click en fila de movimiento         | Detalle del doc origen          |
| E      | Botón "+ Nueva NC"                  | `ModalNCLocal`                  |
| F      | Botón "+ Nuevo pedido"              | `ModalPedidoCompra`             |
| G      | Botón "Pago rápido"                 | `POST /cc-proveedor/:id/pago-rapido` |
| H      | Botón "Ajuste manual"               | `POST /cc-proveedor/:id/ajuste-manual` |

El **panel de imputaciones** se integró como sección colapsable adentro
del tab CC — antes era un sub-tab aparte. Backend mantuvo el endpoint
`/imputaciones` (listado global, paginado), el front ahora pasa
`proveedorIdFijo` al panel cuando vive dentro de CC.

### 8.5.2 OP editable/cancelable en estado `pendiente`

OPs recién creadas (aún NO pagadas) ahora son editables y cancelables:

- `PUT /ordenes-pago/{id}` — edita `monto_total`, `moneda`,
  `modo_imputacion`, `items`, `observaciones`, `tipo_cambio`.
- `POST /ordenes-pago/{id}/cancelar-pendiente` — transición
  `pendiente → cancelado` (estado nuevo en CHECK constraint de
  `compras_024_op_estado_cancelado`).

**Append-only preservado**: editar items inserta un NUEVO evento
`items_editados` en `compras_eventos`. El original `items_registrados`
NO se borra. `ejecutar_pago` lee el más reciente entre ambos. Así
nunca se pierde la auditoría de cómo se creó la OP.

Cancelar en estado `pagado` → 409. Anular (estado `pagado → anulado`)
sigue teniendo su endpoint separado con reverso contable; NO se unifica
con cancelar.

### 8.5.3 TC override al ejecutar pago (USD)

Si el TC del pedido difiere del TC del día del pago, `ejecutar_pago`
acepta `tipo_cambio_override`. Además se permite cross-moneda (OP en
USD pagada desde caja ARS) **solo si se provee TC**. Sin TC → 422
`OP_CAJA_MONEDA_MISMATCH`.

- Frontend (`ModalEjecutarPago`): campo "Tipo de cambio al pagar"
  visible solo si `op.moneda==='USD'`, default = `op.tipo_cambio` o TC
  del día.
- `ModalPedidoDetalle`: muestra equivalente ARS `(monto * tipo_cambio)`
  como info readonly si USD.

Evento `op_pagada` incluye `tc_aplicado` para auditoría.

### 8.5.4 Multi-documentos ERP por pedido

Las imputaciones siempre fueron polimórficas (un pedido puede recibir N
imputaciones de N documentos). Lo que faltaba era un **listado** que
exponga todos los documentos ERP asociados:

`GET /pedidos/{id}/documentos-erp-imputados` → factura(s) + NCs + NDs +
NCs locales, ordenado por fecha desc. Schema `DocumentoERPImputado`.

`numero_factura` / `ct_transaction_id` en el pedido siguen existiendo
como "principal/hint" pero NO son la fuente de verdad — la verdad está
en las imputaciones.

### 8.5.5 Vincular factura con UPDATE directo si no hay imputaciones

`POST /pedidos/{id}/vincular-factura` con `ajustar_monto=True`:

- Si el pedido NO tiene imputaciones vigentes → UPDATE directo del
  monto. Evento `monto_actualizado_sin_imputaciones`. **No se genera
  ajuste en CC** (no hay contrapartes al monto viejo).
- Si SÍ tiene imputaciones → ajuste compensatorio append-only (comportamiento
  existente, preserva integridad contable).

Esto evita contaminar la CC con "ajustes cosméticos" cuando el pedido
aún no tuvo vida contable real.

### 8.5.6 Facturas ERP vigentes por proveedor (sub-batch 3)

`GET /cc-proveedor/{proveedor_id}/facturas-erp-vigentes?moneda=ARS|USD`
lista facturas del ERP del proveedor (vía `v_facturas_compra_vigentes`)
sin filtrar por pedido. Usado por `ModalAplicarNC` cuando el usuario
elige destino `factura_erp`.

Si el proveedor no tiene `supp_id` ERP → lista vacía + log WARNING.
En SQLite tests → lista vacía silenciosa (vista no existe).

### 8.5.7 Ajuste manual de CC proveedor (permiso crítico)

`POST /cc-proveedor/{proveedor_id}/ajuste-manual` — inserta un movimiento
`tipo='ajuste'`, `origen_tipo='ajuste_manual'`, `origen_id=NULL`. Append-only.

Migración `compras_025_ajuste_cc_manual` seedéa el permiso
`administracion.ajustar_cc_proveedor_manual` con `es_critico=true` y
**SIN asignación default** — el admin debe asignarlo a tesorería senior
manualmente. Sin esto, el botón "Ajuste manual" no aparece en la UI.

### 8.5.8 Notificaciones: fan-out por permisos

Antes: varias partes del módulo creaban `Notificacion(user_id=None)` o
hacían fan-out manual por `RolUsuario.ADMIN`. Eso era un bug silencioso
(el listado `/notificaciones` filtra estricto por `user_id`).

Ahora: usar SIEMPRE
`app.services.notificacion_service.crear_notificaciones_para_permisos`:

```python
from app.services.notificacion_service import crear_notificaciones_para_permisos

crear_notificaciones_para_permisos(
    session,
    permisos_requeridos=["administracion.gestionar_ordenes_compra"],
    tipo="compras.pedido_monto_difiere_factura",
    mensaje="...",
    severidad=SeveridadNotificacion.WARNING,
    item_id=pedido.id,
)
```

El helper:

1. Resuelve destinatarios vía `PermisosService.tiene_algun_permiso`
   (rol base + overrides). SUPERADMIN siempre matchea.
2. Crea 1 notificación por destinatario activo.
3. Si nadie matchea → log WARNING + retorna `[]`. **NO** crea filas
   con `user_id=None`.

Callers migrados en el batch de limpieza:

- `cc_proveedor_service._crear_alerta_y_notificaciones_divergencia`
- `sync_commercial_transactions_guid._notificar_admin_catalogo_vacio`
- `erp_matching_service.*` (ya en PR #599)

NO migrar: scripts que notifican a un usuario específico (ej:
`agregar_metricas_ml_*` → `user_id=usuario.id` del dueño del markup).

### 8.5.9 IDs crudos → nombres legibles en UI

Todas las tablas del módulo que muestran FKs deben usar nombres humanos.
Pattern backend: **enriquecimiento batch** (sin N+1) que devuelve
`{empresa,proveedor}_nombre` + `{origen,destino}_descripcion`.

- `_enriquecer_imputaciones(db, imps)` — 6 batch lookups (proveedores,
  empresas, pedidos, OPs, NCs locales, CTs ERP). Usado en:
  - `GET /imputaciones` (listado)
  - `GET /pedidos/{id}` (detalle → `detalle.imputaciones`)
  - `GET /ordenes-pago/{id}` (detalle → `detalle.imputaciones`)
  - `GET /ncs-locales/{id}` (detalle → `detalle.imputaciones`)
- `_enriquecer_movimientos_cc(db, movs)` — 4-5 batch lookups + hop
  `imputacion → origen real (OP/NC local/NC ERP)`. Usado en:
  - `GET /cc-proveedor/{id}` (cronológico)
  - `GET /cc-proveedor/{id}/por-pedido` (agrupado)
  - `POST /cc-proveedor/{id}/ajuste-manual` (respuesta)

Mapping: OP → `"OP {numero}"`, NC → `"NC {numero}"`, ajuste manual →
`"Ajuste manual"`, factura ERP → `"Factura {ct_docnumber}"`, saldo →
`"Saldo a cuenta"`.

Frontend: si el backend no pudo resolver (FK huérfana o vista ERP
ausente en SQLite), fallback al ID crudo `${tipo} #${id}`.

---

## 8.6 Permisos del módulo (cheatsheet)

Todos con prefijo `administracion.*`:

| Código                                         | Qué hace                                                           | Crítico | Asignación default |
| ---------------------------------------------- | ------------------------------------------------------------------ | ------- | ------------------ |
| `administracion.ver_ordenes_compra`            | Ver listados/detalle de pedidos, OPs, NCs                          | No      | Amplia             |
| `administracion.gestionar_ordenes_compra`      | Crear/editar/eliminar pedidos, OPs, NCs (pre-aprobación)           | No      | Compras            |
| `administracion.aprobar_ordenes_compra`        | Aprobar/rechazar pedidos                                           | Sí      | Jefe compras       |
| `administracion.aprobar_ncs_locales`           | Aprobar/rechazar NCs locales                                       | Sí      | Jefe compras       |
| `administracion.ejecutar_pagos`                | Ejecutar pago de OP / pago rápido                                  | Sí      | Tesorería          |
| `administracion.ajustar_monto_pedido`          | Ajustar monto post-aprobación (vincular factura con ajuste)        | Sí      | Jefe compras       |
| `administracion.ver_cuentas_corrientes`        | Ver CC de proveedores                                              | No      | Amplia             |
| `administracion.gestionar_cuentas_corrientes`  | Forzar reconciliación CC manualmente                               | Sí      | Admin              |
| `administracion.ajustar_cc_proveedor_manual`   | Ajuste manual de CC (append-only, permiso crítico)                 | Sí      | **Sin default**    |
| `administracion.eliminar_compras_basura`       | Hard-delete de papelera (cancelados >30d sin imputaciones)         | Sí      | Admin              |

Permisos críticos (`es_critico=true`) NO se pueden quitar del SUPERADMIN
— ver `PermisosService.USER_PROTEGIDO_SUPERADMIN`.

---

## 8.7 Endpoints REST — referencia rápida

Prefijo común: `/api/administracion/compras`.

### Pedidos (§9.1)

- `GET    /pedidos` — listado paginado con joinedload (sin N+1).
- `POST   /pedidos` — crear.
- `GET    /pedidos/{id}` — detalle (con imputaciones enriquecidas + eventos).
- `PUT    /pedidos/{id}` — editar (depende del estado).
- `DELETE /pedidos/{id}` — soft-delete → papelera.
- `POST   /pedidos/{id}/enviar-aprobacion`
- `POST   /pedidos/{id}/aprobar`
- `POST   /pedidos/{id}/rechazar`
- `POST   /pedidos/{id}/reabrir` (estado pagado → pagado_parcial)
- `GET    /pedidos/{id}/etiqueta-envio`
- `PUT    /pedidos/{id}/etiqueta-envio`
- `POST   /pedidos/{id}/vincular-factura` (UPDATE directo o ajuste según
  imputaciones vigentes)
- `POST   /pedidos/{id}/desvincular-factura`
- `GET    /pedidos/{id}/facturas-candidatas` (ERP vigentes sin vincular a
  otros pedidos)
- `GET    /pedidos/{id}/documentos-erp-imputados` (multi-docs)
- `GET    /pedidos/pendientes-pago?proveedor_id=&moneda=`

### Órdenes de pago (§9.2)

- `GET    /ordenes-pago` — paginado, joinedload.
- `POST   /ordenes-pago` — crear en `pendiente`.
- `GET    /ordenes-pago/{id}` — detalle con caja_movimiento_resumen si pagada.
- `PUT    /ordenes-pago/{id}` — editar (solo estado pendiente).
- `POST   /ordenes-pago/{id}/cancelar-pendiente` — cancelar pendiente.
- `POST   /ordenes-pago/{id}/pagar` — ejecutar pago (acepta `tipo_cambio_override`).
- `POST   /ordenes-pago/{id}/anular` — anular pagada (reverso contable).
- `POST   /ordenes-pago/{id}/distribuir` — re-distribuir items (helper).
- `GET    /ordenes-pago/pendientes?proveedor_id=`

### NCs locales (§9.*)

- `GET    /ncs-locales`
- `POST   /ncs-locales`
- `GET    /ncs-locales/{id}`
- `PUT    /ncs-locales/{id}`
- `DELETE /ncs-locales/{id}` → papelera
- `POST   /ncs-locales/{id}/aprobar`
- `POST   /ncs-locales/{id}/rechazar`
- `POST   /ncs-locales/{id}/aplicar` (crea imputación; destino pedido/factura/saldo)

### Imputaciones (§9.3)

- `GET    /imputaciones` — paginado, enriquecidas.
- `POST   /imputaciones/{id}/desimputar` — inserta reversal append-only.
- `POST   /imputaciones/{id}/reimputar` — reversal + nueva en atómico.

### CC proveedor + reconciliación (§9.4)

- `GET    /cc-proveedor/{id}` — saldos por moneda + movimientos enriquecidos.
- `GET    /cc-proveedor/{id}/por-pedido` — drill-down.
- `GET    /cc-proveedor/{id}/facturas-erp-vigentes?moneda=` (sub-batch 3).
- `POST   /cc-proveedor/{id}/pago-rapido` (crea OP a_cuenta + ejecuta en atómico).
- `POST   /cc-proveedor/{id}/ajuste-manual` (permiso crítico).
- `GET    /reconciliacion`
- `POST   /reconciliacion/forzar`
- `GET    /reconciliacion/metricas`

### Adjuntos + papelera + eventos

- `GET    /pedidos/{id}/adjuntos`, `POST`, `DELETE`
- `GET    /ordenes-pago/{id}/adjuntos`, `POST`, `DELETE`
- `GET    /ncs-locales/{id}/adjuntos`, `POST`, `DELETE`
- `GET    /papelera` — listado con filtros por tipo.
- `GET    /papelera/{id}` — snapshot JSONB.
- `POST   /papelera/{id}/restaurar`
- `DELETE /papelera/{id}` — hard-delete (cancelados >30d).

### Catálogo

- `GET    /sale-documents` — catálogo con `clasificacion` derivada.
- `GET    /health` — smoke (no auth).

---

## 9. Extensión futura (v2)

Ver `openspec/changes/modulo-compras/proposal.md` §Out of Scope para la
lista oficial. Resumen de los candidatos más pedidos:

### 9.1 Deprecar snapshot CC

Eliminar la tabla legacy `cuentas_corrientes_proveedores` cuando se
cumplan los 3 criterios (30 días sin divergencias + 80% cobertura +
aprobación de usuarios clave). Change nuevo, out of scope v1.

### 9.2 Facturas locales

Hoy las facturas vienen del ERP vía `tb_commercial_transactions`. v2
permitiría cargar facturas directamente en la app (sin pasar por ERP),
útil para proveedores chicos o casos urgentes. Requiere:

- Tabla nueva `facturas_proveedor_local`
- UI de alta/edición
- Integración con el matching y la CC.

### 9.3 Notas de crédito locales

Similar a 9.2 pero para NCs. Cerraría el ciclo completo de
documentación propia.

### 9.4 Adjuntos en pedidos/OPs

Hoy no hay adjuntos (presupuestos, PDFs, facturas escaneadas). v2
agregaría una tabla `compras_adjuntos` polimórfica (como `compras_eventos`)
con storage en disco o S3.

### 9.5 Workflow multi-step de aprobación

v1 tiene un único paso de aprobación. v2 podría tener:

- Aprobación por montos (< X autoaprueba, > X requiere gerente, > Y
  requiere CFO).
- Aprobación múltiple (2 aprobadores deben estar de acuerdo).

---

## 10. Archivos clave — mapa rápido

### Backend

| Área        | Path                                                           |
| ----------- | -------------------------------------------------------------- |
| Config ERP  | `backend/app/core/compras_empresa_erp_map.py`                  |
| Models      | `backend/app/models/pedido_compra.py`, `orden_pago.py`, `imputacion.py`, `cc_proveedor_movimiento.py`, `numeracion_contador.py`, `tb_sale_document.py`, `cc_reconciliacion_log.py`, `compras_evento.py` |
| Services    | `backend/app/services/pedidos_compra_service.py`, `ordenes_pago_service.py`, `imputaciones_service.py`, `cc_proveedor_service.py`, `numeracion_service.py`, `sale_document_classifier.py`, `erp_matching_service.py` |
| Router      | `backend/app/routers/administracion_compras.py` (~45 endpoints — ver §8.7) |
| Scripts     | `backend/app/scripts/reconciliar_cc_proveedor.py`, `verify_compras_pre_deploy.py`, `verificar_permisos_compras.py` |
| Migrations  | `backend/alembic/versions/compras_001...025_*.py` (25 total — ver §8.6/§8.7 para lo agregado post-v1) |
| Tests unit  | `backend/tests/unit/test_sale_document_classifier.py`, `test_numeracion_service.py`, `test_state_machine_pedidos.py`, ... |
| Tests integ | `backend/tests/integration/test_compras_endpoints.py` (42+ tests), `test_jukebox_fixture.py`, `test_numeracion_concurrencia.py` |

### Frontend

| Área        | Path                                                           |
| ----------- | -------------------------------------------------------------- |
| Page        | `frontend/src/pages/AdministracionCompras.jsx`                 |
| Tabs        | `frontend/src/components/compras/Tab*.jsx`                     |
| Modales     | `frontend/src/components/compras/Modal*.jsx`                   |
| Autocomplete| `frontend/src/components/compras/ProveedorComprasAutocomplete.jsx` |
| Panel       | `frontend/src/components/compras/PanelImputaciones.jsx`        |
| Hooks       | `frontend/src/hooks/useComprasPedidos.js`, `useComprasOP.js`, `useCCProveedor.js` |
| Nav         | `frontend/src/components/Navbar.jsx` (dropdown "Administración") |

### Docs / SDD

| Tipo        | Path                                                           |
| ----------- | -------------------------------------------------------------- |
| Proposal    | `openspec/changes/modulo-compras/proposal.md`                  |
| Design      | `openspec/changes/modulo-compras/design.md`                    |
| Specs       | `openspec/changes/modulo-compras/specs/*.md` (9 archivos)      |
| Tasks       | `openspec/changes/modulo-compras/tasks.md`                     |
| State       | `openspec/changes/modulo-compras/state.yaml`                   |
| Baseline    | `openspec/changes/modulo-compras/performance-baseline.md`      |
| Deploy      | `openspec/changes/modulo-compras/deploy-setup.md`              |
| User guide  | `docs/modulos/compras-guia-usuario.md`                         |
| Dev guide   | `docs/modulos/compras-dev-guide.md` (este archivo)             |
| Post-deploy | `docs/modulos/compras-post-deploy-checklist.md`                |

---

## 11. Engram — topic_keys relevantes

Para devs que usan Engram para recuperar contexto histórico:

| Topic key                                          | Contenido                                      |
| -------------------------------------------------- | ---------------------------------------------- |
| `sdd/modulo-compras/explore`                       | Investigación inicial (JUKEBOX, 43 sd_id).     |
| `sdd/modulo-compras/design-decisions`              | D1..D22 del design.                            |
| `sdd/modulo-compras/erp-mapping`                   | Mapeo empresa_id ↔ (comp_id, bra_id).          |
| `sdd/modulo-compras/proposal`                      | Versión final del proposal.                    |
| `sdd/modulo-compras/sale-document-catalog`         | Catálogo completo de los 43 sd_id.             |
| `sdd/modulo-compras/sale-document-no-sync`         | Refinement 2026-04-17 (seed estático).         |
| `sdd/modulo-compras/design`                        | Design doc completo.                           |
| `sdd/modulo-compras/tasks`                         | Tasks breakdown (86 tasks).                    |
| `sdd/modulo-compras/apply-progress`                | Progreso fase por fase (F0..F8).               |

Sesión: `sdd-modulo-compras-2026-04-17`.

---

## 12. Dónde empezar si tocas el módulo por primera vez

**Si es un bug:** reproducilo con un test en `backend/tests/integration/test_compras_endpoints.py` y
después entrá al service correspondiente.

**Si es una feature nueva:** primero leé proposal.md + design.md + el spec
correspondiente. Decidí si cabe en v1 o si requiere un change nuevo.

**Si es cambio cosmético frontend:** el hook + el componente del tab
cubren el 90% de los casos. Si tocás lógica compartida, hacelo en el hook.

**Si tocás algo append-only:** RE-LEÉ este documento sección 8. No hay
excepciones.

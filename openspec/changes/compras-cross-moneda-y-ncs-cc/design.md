# Design: Compras Cross-Moneda + NCs Visibles en CC

> Change: `compras-cross-moneda-y-ncs-cc`
> Mode: hybrid (Engram topic `sdd/compras-cross-moneda-y-ncs-cc/design` + filesystem)
> Depends on: `proposal.md`, `specs.md`, `exploration.md`

## Technical Approach

El change ataca dos problemas que confluyen en el workflow "pagar pedido USD desde caja ARS aprovechando NCs del proveedor":

1. **Cross-moneda OP↔pedido**: hoy `_validar_moneda_consistente` (imputaciones_service) y `_validar_items_misma_moneda_que_op` (ordenes_pago_service, PR #624) rechazan con HTTP 400. El TC obligatorio en la OP resuelve la asimetría: la imp se graba en **moneda destino** (la del pedido) usando el TC para convertir, así `aplicar_imputacion` en `cc_proveedor_service` proyecta el HABER en la moneda real de la deuda sin tocar nada.
2. **NCs invisibles en CC**: el TabCCProveedores no muestra NCs aprobadas con saldo. Se agrega un endpoint `/ncs-locales/disponibles?proveedor_id=X` y se enriquece `/cc-proveedor/{id}/por-pedido` con `tc_ponderado` por pedido y `ncs_disponibles` por proveedor. La UI suma hero con NCs disponibles + dos botones por card de pedido ("Aplicar NC", "Imputar pago") que abren modales pre-cargados.

Decisión técnica clave (ya aprobada en proposal): `moneda_imputada = moneda destino`, no origen. Esto es lo que hace que `cc_proveedor_service.aplicar_imputacion` no requiera cambios — ya usa `imp.moneda_imputada` para el HABER.

Append-only sagrado (D9, NFR-003): cero `UPDATE` sobre imputaciones / cc_proveedor_movimientos / compras_eventos. Cambios = reversal + nueva imp.

---

## 1. Component Map

```
                          UI (TabCCProveedores)
                          ────────────────────
            ┌──────────────────────────────┐
            │  Hero del proveedor          │
            │  ├── Saldos por moneda       │
            │  └── NCs disponibles (NEW)   │── click "Aplicar NC" ──┐
            └──────────────────────────────┘                        │
            ┌──────────────────────────────┐                        ▼
            │  GrupoPedidoCard (por pedido)│              ┌──────────────────┐
            │  ├── tc_ponderado (NEW)      │              │ ModalAplicarNC   │
            │  ├── [Aplicar NC]    (NEW)   │── click ────▶│ + pedidoDestino  │
            │  └── [Imputar pago]  (NEW)   │── click ──┐  └──────────────────┘
            └──────────────────────────────┘           │           │
                                                       ▼           │
                                          ┌──────────────────┐     │
                                          │ ModalOrdenPago   │     │
                                          │ Nueva + pedido   │     │
                                          │ + TC cross-mon.  │     │
                                          └──────────────────┘     │
                                                       │           │
                                       POST /ordenes-pago          │
                                       (tipo_cambio mandatorio si  │
                                        OP.moneda ≠ item.moneda)   │
                                                       │           │
            ─────────────────────────────────── BACKEND ────────────────────────
                                                       ▼           ▼
                                          ┌────────────────────────────────┐
                                          │ ordenes_pago_service           │
                                          │ ├── crear / editar             │
                                          │ │   └── _validar_items_cross_  │
                                          │ │       moneda_con_tc (RENAME) │
                                          │ └── ejecutar_pago              │
                                          │     ├── convierte ARS→USD x TC │
                                          │     └── llama crear_imputacion │
                                          └────────────────────────────────┘
                                                       │
                                                       ▼
                                          ┌────────────────────────────────┐
                                          │ imputaciones_service           │
                                          │ ├── _validar_moneda_consistente│
                                          │ │   (RELAX: con TC permite)    │
                                          │ └── crear_imputacion           │
                                          │     ├── persiste moneda_destino│
                                          │     └── persiste TC            │
                                          └────────────────────────────────┘
                                                       │
                                                       ▼
                                          ┌────────────────────────────────┐
                                          │ cc_proveedor_service           │
                                          │ └── aplicar_imputacion         │
                                          │     (SIN CAMBIOS — ya usa      │
                                          │     imp.moneda_imputada)       │
                                          │     genera HABER en MONEDA     │
                                          │     DESTINO (USD para deuda    │
                                          │     USD)                        │
                                          └────────────────────────────────┘
                                                       │
                                                       ▼
                                          ┌────────────────────────────────┐
                                          │ pedidos_service                │
                                          │ ├── calcular_tc_ponderado_     │
                                          │ │   pedido (NEW)               │
                                          │ ├── calcular_tc_ponderado_     │
                                          │ │   pedido_batch (NEW)         │
                                          │ └── calcular_saldos_pendientes │
                                          │     _batch (SIN CAMBIOS — ya   │
                                          │     filtra por moneda destino) │
                                          └────────────────────────────────┘
                                                       │
                                                       ▼
                                          ┌────────────────────────────────┐
                                          │ administracion_compras.py      │
                                          │ ├── GET /ncs-locales/disponibles│
                                          │ │   (NEW)                       │
                                          │ └── GET /cc-proveedor/{id}/    │
                                          │     por-pedido                  │
                                          │     ├── + tc_ponderado por ped │
                                          │     └── + ncs_disponibles       │
                                          └────────────────────────────────┘
                                                       │
                                                       ▼
                                                  PostgreSQL
                                          (imputaciones append-only)
```

---

## 2. Data Model

### 2.1 Modelo `Imputacion` — SIN MIGRACIÓN

El modelo `app/models/imputacion.py` ya soporta el caso cross-moneda:

| Campo | Tipo | Comentario |
|---|---|---|
| `monto_imputado` | `Numeric(18, 2)` | Almacena el monto en **moneda destino** |
| `moneda_imputada` | `String(3)` | Pasa a registrar `pedido.moneda` (era `op.moneda`) |
| `tipo_cambio` | `Numeric(18, 6) NULLABLE` | Ya existe; se llenará obligatoriamente en cross-moneda |
| `es_reversal` | `Boolean` | Append-only, reversal con misma moneda/monto/TC |
| `reimputada_desde_id` | `BigInteger FK` | Trazabilidad |

CHECK constraints existentes (`monto_imputado > 0`, `moneda_imputada IN ('ARS','USD')`) NO se tocan.

**No migración de schema. No migración de datos.** Pedidos same-moneda viejos (FR-013) siguen viendo `moneda_imputada == op.moneda == pedido.moneda` — la igualdad accidental no rompe nada porque `aplicar_imputacion` y `calcular_saldos_pendientes_batch` ya filtran por `Imputacion.moneda_imputada == pedido.moneda`.

### 2.2 Campo derivado `tipo_cambio_ponderado` en `PedidoCompraResponse`

Calculado server-side, **NO persistido**:

```
tc_ponderado(pedido) = SUM(imp.tipo_cambio * imp.monto_imputado) / SUM(imp.monto_imputado)
                       WHERE imp.destino_tipo = 'pedido_compra'
                         AND imp.destino_id = pedido.id
                         AND imp.moneda_imputada = pedido.moneda
                         AND imp.tipo_cambio IS NOT NULL
                         AND imp.es_reversal = FALSE
```

Interpretación: numerador = total ARS aportado (TC × monto USD = ARS), denominador = total USD imputado al pedido. Cociente = ARS por unidad USD ponderado por aporte.

- `None` si sin imps cross-moneda (todas same-moneda o sin imps).
- Reversals excluidos (append-only: imp original sigue contando si la reversal aún no fue compensada por una nueva imp).

> **Trade-off de reversals**: si una imp cross-moneda se reversa SIN una nueva imp que la reemplace, el reversal NO se descuenta del cálculo. Esto es consciente: el TC ponderado describe el costo histórico declarado de las imps activas. Los reversals se descuentan correctamente en `calcular_saldos_pendientes_batch` (que sí los resta); el TC ponderado es métrica complementaria, no replacement del saldo. Documentar en el docstring.

---

## 3. API Contracts

### 3.1 Nuevo endpoint: `GET /administracion/compras/ncs-locales/disponibles`

**Request**:
```
GET /administracion/compras/ncs-locales/disponibles
  ?proveedor_id=<int, required>
  &limit=<int, default 100, max enforced by project policy>
  &offset=<int, default 0>
```

**Response 200** — `list[NCDisponibleSummary]`:
```python
class NCDisponibleSummary(BaseModel):
    id: int
    numero: str
    fecha: date              # nc.created_at::date
    importe: Decimal         # nc.monto
    moneda: str              # nc.moneda (filtro extra opcional, hoy single)
    saldo_pendiente: Decimal # ncs_locales_service.calcular_saldo_pendiente()
    estado: str              # 'aprobado' | 'aplicada_parcial'
```

**Filtros aplicados** (FR-007):
- `proveedor_id = ?`
- `estado IN ('aprobado', 'aplicada_parcial')`
- `saldo_pendiente > 0` (post-filter en aplicación; el saldo se calcula vía agregación de imps de la NC, no es columna)
- Orden: `created_at DESC, id DESC` (NFR-002)

**Errores**:
- 422 si falta `proveedor_id` (FastAPI valida por `Query(..., ge=1)`)
- 200 con `[]` si proveedor existe pero no tiene NCs disponibles

**Decisión de implementación**: el saldo NO es persistido en `NotaCreditoLocal`. Existe `ncs_locales_service.calcular_saldo_pendiente(db, nc.id)`. Para evitar N+1 en este endpoint, usar batch:
```python
# Pseudocódigo
ncs_candidatas = SELECT nc WHERE proveedor_id=? AND estado IN ('aprobado','aplicada_parcial')
                 ORDER BY created_at DESC LIMIT ? OFFSET ?
imps_por_nc = SELECT origen_id, SUM(CASE WHEN reversal THEN -monto ELSE monto END)
              FROM imputaciones
              WHERE origen_tipo='nota_credito_local' AND origen_id IN (ids)
              GROUP BY origen_id
result = [nc for nc in candidatas if nc.monto - imps_por_nc.get(nc.id, 0) > 0]
```
Si el saldo>0 reduce la página, el caller puede pedir página siguiente. Aceptable v1 (proveedores típicos < 50 NCs).

---

### 3.2 Endpoint modificado: `GET /cc-proveedor/{proveedor_id}/por-pedido`

Schema `CCAgrupadoPorPedido` (en `schemas/cc_proveedor.py`) recibe DOS campos nuevos:

```python
class CCAgrupadoPorPedido(BaseModel):
    # ... existentes ...
    pedido_compra_id: int
    pedido_numero: str
    pedido_estado: str
    pedido_monto: Decimal
    pedido_moneda: str
    pedido_tipo_cambio: Optional[Decimal] = None
    pedido_saldo_pendiente: Optional[Decimal] = None
    movimientos: list[CCMovimientoResponse]

    # NUEVOS (FR-008):
    tc_ponderado: Optional[Decimal] = None        # null si pedido same-moneda

# Response del endpoint pasa de `list[CCAgrupadoPorPedido]` a:
class CCPorPedidoResponse(BaseModel):
    grupos: list[CCAgrupadoPorPedido]
    ncs_disponibles: list[NCDisponibleSummary] = []
```

> **Decisión de estructura**: cambiar el response de `list[...]` a `dict/object {grupos, ncs_disponibles}` **rompe el contrato actual** (consumers del frontend hoy reciben array). Para mantener backward compat (NFR-004), la opción correcta es **mantener `list[CCAgrupadoPorPedido]` y exponer NCs disponibles vía endpoint separado** (`/ncs-locales/disponibles?proveedor_id=X`). El frontend hace 2 fetches en paralelo desde TabCCProveedores. **Recomendación final**: NO modificar el shape de `/cc-proveedor/{id}/por-pedido` para `ncs_disponibles`; solo agregar `tc_ponderado` por grupo (campo nuevo opcional = backward compat). Las NCs disponibles vienen por el endpoint FR-007.

Resultado del trade-off:
- `/cc-proveedor/{id}/por-pedido` — agrega solo `tc_ponderado: Optional[Decimal]` a cada item (additive).
- `/ncs-locales/disponibles?proveedor_id=X` — endpoint dedicado, llamado en paralelo.

### 3.3 Endpoints OP (`POST /ordenes-pago`, `PUT /ordenes-pago/{id}`, `POST /ordenes-pago/{id}/pagar`)

**Sin cambio de contrato Pydantic**. Cambia el comportamiento de validación interna:

| Endpoint | Antes | Después |
|---|---|---|
| `POST /ordenes-pago` | Rechaza si `op.moneda != item.pedido.moneda` (siempre) | Permite si `op.tipo_cambio > 0`; rechaza si TC missing/<=0 |
| `PUT /ordenes-pago/{id}` | Igual | Igual |
| `POST /ordenes-pago/{id}/pagar` | Imp con `moneda_imputada=op.moneda` | Imp con `moneda_imputada=pedido.moneda`, monto convertido por TC |

Para el frontend / clients legacy: la única diferencia observable es que ya no reciben 400 cuando mandan TC válido. Sin migración necesaria de payloads.

---

## 4. Service Logic

### 4.1 `imputaciones_service._validar_moneda_consistente` (RELAJADO)

**Firma actual**:
```python
def _validar_moneda_consistente(origen_moneda: str, destino_moneda: str) -> None
```

**Firma nueva**:
```python
def _validar_moneda_consistente(
    origen_moneda: str,
    destino_moneda: str,
    tipo_cambio: Optional[Decimal] = None,
) -> None:
    if origen_moneda == destino_moneda:
        return
    # Cross-moneda: requiere TC > 0
    if tipo_cambio is None or Decimal(tipo_cambio) <= 0:
        raise HTTPException(400, detail=f"Cross-moneda requiere tipo_cambio > 0 ...")
```

**Caller**: el comentario actual en `crear_imputacion` (líneas 196-201) dice "la moneda destino la valida el caller". Mantenemos esto: el helper `_validar_moneda_consistente` se exporta para que el caller (ej. `ejecutar_pago`) lo llame con TC.

### 4.2 `imputaciones_service.crear_imputacion`

**Sin cambios estructurales**. Sigue siendo agnóstico: confía en que el caller pasa `moneda_imputada` correcta (= moneda destino) y `tipo_cambio` cuando hay cross-moneda. La validación cross-moneda real la hace el caller (`ejecutar_pago`).

> **Por qué no validar acá**: el caller tiene la información completa (`op.moneda`, `pedido.moneda`, `op.tipo_cambio`). Acá llegamos con `moneda_imputada` ya decidida — si la validamos contra `origen_moneda` necesitaríamos pasar más parámetros. Mantener responsabilidad en el caller es coherente con el comentario actual (líneas 196-201).

### 4.3 `ordenes_pago_service._validar_items_cross_moneda_con_tc` (RENAME + REWRITE)

Rename de `_validar_items_misma_moneda_que_op` → `_validar_items_cross_moneda_con_tc`. Firma cambia para recibir TC:

```python
def _validar_items_cross_moneda_con_tc(
    session: Session,
    *,
    items: list[dict],
    op_moneda: str,
    op_tipo_cambio: Optional[Decimal],
) -> None:
    for idx, item in enumerate(items):
        if item.get("tipo") != "pedido_compra":
            continue
        pedido = session.get(PedidoCompra, item["id"])
        if pedido is None or pedido.moneda == op_moneda:
            continue
        # Cross-moneda detectada
        if op_tipo_cambio is None or Decimal(op_tipo_cambio) <= 0:
            raise HTTPException(
                400,
                detail=(
                    f"item[{idx}]: OP en {op_moneda} ↔ pedido #{pedido.id} en {pedido.moneda}. "
                    f"Cross-moneda requiere tipo_cambio > 0 en la OP."
                ),
            )
```

**Call sites afectados**:
- `crear()` (L415) → pasar `op_tipo_cambio=tipo_cambio` (del payload)
- `editar()` (L919, L927) → pasar `tc_final`
- `ejecutar_pago()` (L725) → pasar `op.tipo_cambio` (después de aplicar override)

### 4.4 `ordenes_pago_service.ejecutar_pago` (CONVERSIÓN)

El loop sobre items (líneas 733-750) se modifica:

```python
for item in items:
    monto_item_origen = Decimal(str(item["monto"]))  # SIEMPRE en moneda OP origen

    pedido_destino = (
        session.get(PedidoCompra, item["id"])
        if item["tipo"] == "pedido_compra" and item.get("id")
        else None
    )

    if pedido_destino is not None and pedido_destino.moneda != op.moneda:
        # Cross-moneda: convertir y grabar en moneda destino
        tc_op = op.tipo_cambio  # ya garantizado > 0 por _validar_items_cross_moneda_con_tc
        if op.moneda == "ARS" and pedido_destino.moneda == "USD":
            monto_imputado = (monto_item_origen / Decimal(tc_op)).quantize(Decimal("0.01"))
        elif op.moneda == "USD" and pedido_destino.moneda == "ARS":
            monto_imputado = (monto_item_origen * Decimal(tc_op)).quantize(Decimal("0.01"))
        else:
            # No esperado (validador ya filtró), defensa en profundidad
            raise HTTPException(500, detail="Combinación de monedas no soportada")
        moneda_imp = pedido_destino.moneda
        tc_imp = Decimal(tc_op)
    else:
        # Same-moneda o destino != pedido_compra → comportamiento previo
        monto_imputado = monto_item_origen
        moneda_imp = op.moneda
        tc_imp = None

    imp = imputaciones_service.crear_imputacion(
        session,
        origen_tipo="orden_pago",
        origen_id=op.id,
        destino_tipo=item["tipo"],
        destino_id=item.get("id"),
        monto_imputado=monto_imputado,
        moneda_imputada=moneda_imp,
        tipo_cambio=tc_imp,
        proveedor_id=op.proveedor_id,
        creado_por_id=user_id,
    )
    cc_proveedor_service.aplicar_imputacion(session, imputacion_id=imp.id)
    ...
```

**Fórmula de conversión** (decisión explícita, NO ambigua):
- **TC siempre expresado como "ARS por 1 USD"** (consistente con `pedidos_compra.tipo_cambio` y con la fórmula que ya está en `ejecutar_pago` para el `monto_en_caja` en lineas 685-689 del archivo actual).
- OP ARS pagando pedido USD: `monto_USD = monto_ARS_item / TC`. Ej: `1.500.000 ARS / 1500 = 1000 USD`.
- OP USD pagando pedido ARS: `monto_ARS = monto_USD_item × TC`. Ej: `1000 USD × 1500 = 1.500.000 ARS`.
- Redondeo: `quantize(Decimal("0.01"))` → HALF_EVEN por default de Decimal (consistente con el caja_movimiento ya existente en `ejecutar_pago`).

**Saldo "mixta" / "a_cuenta"** (líneas 753-782): el remanente sigue siendo en moneda OP origen (destino = "saldo" — no hay conversión, el saldo a cuenta queda en la moneda del flujo de plata real, no del pedido).

### 4.5 `pedidos_service.calcular_tc_ponderado_pedido` + batch (NEW)

```python
def calcular_tc_ponderado_pedido(session: Session, pedido_id: int) -> Optional[Decimal]:
    """
    TC ponderado por aporte. Solo considera imps cross-moneda (tipo_cambio IS NOT NULL).
    Reversals excluidos (append-only — la nueva imp ya suma con su TC propio).

    Returns:
        Decimal con 4 decimales (precisión de tipo_cambio) o None si no hay imps cross-moneda.
    """
    pedido = _obtener_pedido_o_404(session, pedido_id)
    row = session.execute(
        select(
            func.coalesce(
                func.sum(Imputacion.tipo_cambio * Imputacion.monto_imputado),
                0,
            ).label("numerador"),
            func.coalesce(func.sum(Imputacion.monto_imputado), 0).label("denominador"),
        ).where(
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id == pedido.id,
            Imputacion.moneda_imputada == pedido.moneda,
            Imputacion.tipo_cambio.is_not(None),
            Imputacion.es_reversal.is_(False),
        )
    ).one()
    num, den = Decimal(row.numerador), Decimal(row.denominador)
    if den == 0:
        return None
    return (num / den).quantize(Decimal("0.0001"))
```

**Batch version** (mismo patrón que `calcular_saldos_pendientes_batch`):

```python
def calcular_tc_ponderado_pedido_batch(
    session: Session,
    pedido_ids: list[int],
) -> dict[int, Optional[Decimal]]:
    """1 query agregada. dict.get(pid) → None si pedido no tiene imps cross-moneda."""
    if not pedido_ids:
        return {}
    rows = session.execute(
        select(
            Imputacion.destino_id,
            func.sum(Imputacion.tipo_cambio * Imputacion.monto_imputado).label("num"),
            func.sum(Imputacion.monto_imputado).label("den"),
        )
        .join(PedidoCompra, PedidoCompra.id == Imputacion.destino_id)
        .where(
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id.in_(pedido_ids),
            Imputacion.moneda_imputada == PedidoCompra.moneda,
            Imputacion.tipo_cambio.is_not(None),
            Imputacion.es_reversal.is_(False),
        )
        .group_by(Imputacion.destino_id)
    ).all()
    result: dict[int, Optional[Decimal]] = {pid: None for pid in pedido_ids}
    for pid, num, den in rows:
        if den and Decimal(den) != 0:
            result[int(pid)] = (Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"))
    return result
```

### 4.6 `cc_proveedor_service.aplicar_imputacion` (SIN CAMBIOS)

Ya usa `imp.moneda_imputada` en línea 343 (`mov = insertar_mov(..., moneda=imp.moneda_imputada, ...)`). Con la nueva semántica, `imp.moneda_imputada` = moneda destino, así que el HABER queda en moneda destino sin tocar el servicio.

**Único cambio**: actualizar docstring de `aplicar_imputacion` para reflejar que en cross-moneda el HABER queda en moneda destino, NO en moneda OP origen.

---

## 5. Reversals cross-moneda (Decisión explícita)

`desimputar` (líneas 526-618 de `imputaciones_service.py`) **NO requiere cambios**: ya copia `moneda_imputada`, `monto_imputado` y `tipo_cambio` de la original al reversal (líneas 578-583). El reversal de una imp cross-moneda genera:

- Una imp reversal con `moneda_imputada=USD`, `monto_imputado=666.67`, `tipo_cambio=1500`, `es_reversal=True`.
- `cc_proveedor_service.aplicar_imputacion` lo proyecta como **DEBE 666.67 USD** en el CC del proveedor (línea 301: `tipo_mov = "debe"` para reversals).
- La OP original sigue ejecutada — el caja_movimiento ARS NO se anula. El proveedor "debe" 666.67 USD de vuelta, pero ya recibió 1.000.000 ARS.

**Consecuencia para el user**: para devolver la plata, debe anular la OP completa (`anular`), no solo desimputar. Si solo desimputa, el saldo se reabre pero la plata no vuelve.

**UI**: en el tooltip del botón "Reversar" / "Desimputar" de la imp cross-moneda, mostrar:
> "Reversar solo desimputa contablemente. La plata pagada en {caja.moneda} no se devuelve — para eso anulá la OP completa."

---

## 6. Frontend Architecture

### 6.1 `ModalOrdenPagoNueva.jsx`

**State afectado**:
- El state `confirmMoneda` (línea 159) — modal de confirmación destructivo — **se mantiene solo para el caso a_cuenta sin TC**. Para cross-moneda con TC > 0, NO se dispara.

**Cambios en `handleChange('moneda', valor)`** (líneas 188-217):
```javascript
if (campo === 'moneda' && valor !== f.moneda) {
  const tienePedidos = items.some(it => it.tipo === 'pedido_compra' && it.id);
  const tcNum = parseFloat(f.tipo_cambio);
  const tcValido = Number.isFinite(tcNum) && tcNum > 0;

  // NUEVO: cross-moneda con TC válido → permitir sin confirm
  if (tienePedidos && !tcValido) {
    // Solo confirmar destructivo si NO hay TC válido
    setConfirmMoneda({ from: f.moneda, to: valor });
    return f;
  }
  // Cross-moneda con TC OK o sin items pedidos → aplicar cambio + convertir monto
  // (el resto de la lógica de conversión existente queda igual)
}
```

**Render condicional del campo TC** (existente, líneas 504-520): el campo `tipo_cambio` ya se renderiza cuando `form.moneda === 'USD'`. **Extender** para renderizarlo también cuando `form.moneda === 'ARS'` y hay al menos 1 item con `pedido.moneda === 'USD'`:

```jsx
const tieneCrossMoneda = items.some(it => {
  if (it.tipo !== 'pedido_compra' || !it.id) return false;
  const pedido = pendientesDelProveedor.find(p => String(p.id) === String(it.id));
  return pedido && pedido.moneda !== form.moneda;
});

{(form.moneda === 'USD' || tieneCrossMoneda) && (
  <input
    name="tipo_cambio"
    value={form.tipo_cambio}
    ...
    placeholder={tieneCrossMoneda ? `TC ${form.moneda}↔Items` : 'TC OP→ARS'}
  />
)}
```

**Validación submit** (líneas 285-294 — donde se construye `tcEnviable`):
```javascript
const requiereTc = form.moneda === 'USD' || tieneCrossMoneda;
const tcNum = parseFloat(form.tipo_cambio);
if (requiereTc && !(Number.isFinite(tcNum) && tcNum > 0)) {
  return 'TC requerido (> 0) para cross-moneda.';
}
const tcEnviable = requiereTc ? tcNum : null;
```

**Props nuevos**: `pedidoInicial` ya existe — ahora puede venir con `moneda` distinta al `proveedorInicial`. No requiere prop nuevo.

### 6.2 `TabCCProveedores.jsx`

**State nuevo**:
```javascript
const [ncsDisponibles, setNcsDisponibles] = useState([]);
const [showAplicarNCDesdeCard, setShowAplicarNCDesdeCard] = useState(null); // { ncId?, pedidoId? }
const [showImputarPagoDesdeCard, setShowImputarPagoDesdeCard] = useState(null); // { pedidoId }
```

**Fetch nuevo** (paralelo a `fetchPorPedido` / `fetchImputaciones`):
```javascript
const fetchNcsDisponibles = useCallback(async () => {
  if (!proveedorIdActivo) return;
  try {
    const { data } = await api.get('/administracion/compras/ncs-locales/disponibles', {
      params: { proveedor_id: proveedorIdActivo, limit: 100 },
    });
    setNcsDisponibles(data || []);
  } catch {
    setNcsDisponibles([]);
  }
}, [proveedorIdActivo]);

useEffect(() => {
  if (proveedorIdActivo) {
    fetchDetalle();
    fetchPorPedido();
    fetchImputaciones();
    fetchNcsDisponibles();  // NEW
  }
}, [proveedorIdActivo, ...]);
```

**Hero NCs disponibles** (después del header del proveedor, antes de las pestañas/filtros):
```jsx
{ncsDisponibles.length > 0 && (
  <section className={styles.ncsDisponiblesHero}>
    <h3>NCs disponibles del proveedor</h3>
    <DataTable
      columns={[
        { key: 'numero', label: 'Número' },
        { key: 'fecha', label: 'Fecha' },
        { key: 'importe', label: 'Importe', render: r => formatCurrency(r.importe, r.moneda) },
        { key: 'saldo_pendiente', label: 'Saldo', render: r => formatCurrency(r.saldo_pendiente, r.moneda) },
        { key: 'estado', label: 'Estado' },
      ]}
      rows={ncsDisponibles}
    />
  </section>
)}
```

**`GrupoPedidoCard` (línea 786)** — agregar props + render:

```jsx
function GrupoPedidoCard({
  grupo,
  imputaciones,
  onMovClick,
  onDesimputar,
  onAplicarNC,      // NEW
  onImputarPago,    // NEW
}) {
  return (
    <div className={styles.grupoCard}>
      <header>
        <span>{grupo.pedido_numero} · {grupo.pedido_estado}</span>
        <span>{formatCurrency(grupo.pedido_saldo_pendiente, grupo.pedido_moneda)}</span>
        {grupo.tc_ponderado && (
          <span className={styles.tcPonderado}>
            TC ponderado: {Number(grupo.tc_ponderado).toFixed(2)}
          </span>
        )}
      </header>
      {/* movimientos ... */}
      <footer className={styles.grupoActions}>
        <button onClick={() => onAplicarNC?.(grupo.pedido_compra_id)}>
          Aplicar NC
        </button>
        <button onClick={() => onImputarPago?.(grupo.pedido_compra_id, grupo.pedido_moneda)}>
          Imputar pago
        </button>
      </footer>
    </div>
  );
}
```

En el render del listado por-pedido, las props se cablean:
```jsx
<GrupoPedidoCard
  ...
  onAplicarNC={(pid) => setShowAplicarNCDesdeCard({ pedidoId: pid })}
  onImputarPago={(pid) => setShowImputarPagoDesdeCard({ pedidoId: pid })}
/>
```

Y los modales reciben el contexto pre-cargado:
```jsx
{showAplicarNCDesdeCard && (
  <ModalAplicarNC
    nc={null}  // user elige una NC del proveedor
    pedidoDestinoId={showAplicarNCDesdeCard.pedidoId}
    onClose={(reload) => {
      setShowAplicarNCDesdeCard(null);
      if (reload) { fetchPorPedido(); fetchNcsDisponibles(); }
    }}
  />
)}
{showImputarPagoDesdeCard && proveedorCtx && (
  <ModalOrdenPagoNueva
    empresas={empresas}
    proveedorInicial={proveedorCtx}
    pedidoInicial={porPedido.find(g => g.pedido_compra_id === showImputarPagoDesdeCard.pedidoId)}
    onClose={(reload) => {
      setShowImputarPagoDesdeCard(null);
      if (reload) { fetchDetalle(); fetchPorPedido(); fetchNcsDisponibles(); }
    }}
  />
)}
```

### 6.3 `ModalAplicarNC.jsx`

**Prop nuevo**: `pedidoDestinoId: number | null = null`.

**Cambio de signatura** (línea 42):
```jsx
export default function ModalAplicarNC({ nc, onClose, pedidoDestinoId = null }) {
```

**Effect on mount**:
```jsx
useEffect(() => {
  if (pedidoDestinoId) {
    setDestinoTipo('pedido_compra');
    setPedidoId(String(pedidoDestinoId));
  }
}, [pedidoDestinoId]);
```

**UX**: si `pedidoDestinoId` viene, el selector de pedido se renderiza pero **deshabilitado** (read-only) — el user no puede cambiar el destino accidentalmente. Si quiere cambiar, cierra y abre desde otro card.

**Selector de NC**: si `nc=null` Y `pedidoDestinoId` viene → el modal muestra dropdown de NCs disponibles del proveedor (fetch en mount). Este flujo es el que se invoca desde TabCCProveedores cuando el user clickea "Aplicar NC" en un card sin haber seleccionado una NC primero.

> **Trade-off de scope**: el `ModalAplicarNC` hoy asume `nc` viene siempre. Si el flujo desde CC requiere también elegir la NC, hay que extenderlo. **Decisión**: para v1 del change, si `nc=null` Y `pedidoDestinoId` viene, mostrar dropdown de NCs disponibles (filtrar por moneda compatible o cross-moneda con TC explícito). Esto agrega complejidad — alternativa es exigir que el user pase por la hero ("Aplicar" desde la tabla de NC disponibles → ahí ya se elige NC, pero al pedir destino el pedido viene pre-cargado por context). Implementación recomendada: **el botón "Aplicar NC" en GrupoPedidoCard abre ModalAplicarNC con un dropdown de NCs disponibles del proveedor y el pedido pre-cargado**. Si solo hay 1 NC disponible, auto-selecciona.

---

## 7. Testing Strategy

| Layer | Test | Path | Cubre |
|---|---|---|---|
| Unit BE | `test_cross_moneda_sin_tc_raise_400` (RENAME) | `tests/unit/test_imputaciones_service.py` | FR-001 (rechazo sin TC) |
| Unit BE | `test_cross_moneda_con_tc_ok` (NEW) | `tests/unit/test_imputaciones_service.py` | FR-001 + FR-002 |
| Unit BE | `test_op_cross_moneda_ejecuta_pago_genera_imp_usd` (NEW) | `tests/unit/test_ordenes_pago_service.py` | FR-003 (conversión + persistencia) |
| Unit BE | `test_op_cross_moneda_sin_tc_400` (NEW) | `tests/unit/test_ordenes_pago_service.py` | FR-004 (rechazo) |
| Unit BE | `test_tc_ponderado_calcula_promedio_correcto` (NEW) | `tests/unit/test_pedidos_service.py` | FR-005 (cálculo) |
| Unit BE | `test_tc_ponderado_batch_evita_n1` (NEW) | `tests/unit/test_pedidos_service.py` | FR-005 (batch, NFR-001) |
| Unit BE | `test_tc_ponderado_pedido_same_moneda_devuelve_none` (NEW) | `tests/unit/test_pedidos_service.py` | FR-005 (edge) |
| Integration BE | `test_endpoint_ncs_disponibles_filtra_por_proveedor_y_saldo` (NEW) | `tests/integration/test_administracion_compras_router.py` | FR-007 |
| Integration BE | `test_por_pedido_incluye_tc_ponderado` (NEW) | `tests/integration/test_administracion_compras_router.py` | FR-008 |
| Integration BE | `test_e2e_op_cross_moneda_ars_paga_pedido_usd` (NEW) | `tests/integration/test_cross_moneda_e2e.py` | E2E completo: OP ARS + ejecutar → imp USD + CC HABER USD + caja ARS |
| Manual QA FE | Checklist en `tasks.md` | — | FR-009/010/011 |

**Tests existentes a invertir**:
- `test_imputaciones_service.py::test_cross_moneda_raise_400` → rename `test_cross_moneda_sin_tc_raise_400` y mantener la aserción (sigue siendo 400 sin TC). Agregar nuevo test con TC válido que pase.

**Tests a NO tocar** (siguen válidos):
- `test_pedidos_vincular_factura.py::test_moneda_factura_distinta_a_pedido_400` (es factura ERP, distinto contexto).
- `test_ordenes_pago_service.py::test_cross_moneda_caja_op_con_tc_override_ok` (PR #624, caja ARS pagando OP USD con override — ortogonal a este change).

---

## 8. Migration Path

**Schema**: NO requiere migración Alembic. Todos los campos necesarios ya existen en `imputaciones`.

**Datos**: NO requiere backfill. Imputaciones same-moneda viejas siguen funcionando (FR-013):
- `moneda_imputada == op.moneda == pedido.moneda` → `aplicar_imputacion` proyecta a CC en esa moneda → saldos se calculan correctamente.
- `tipo_cambio_ponderado` retorna `None` porque las imps viejas same-moneda tienen `tipo_cambio IS NULL` → filtrado por `Imputacion.tipo_cambio.is_not(None)`.

**Tests**: 1 test renombrado (`test_cross_moneda_raise_400` → `test_cross_moneda_sin_tc_raise_400`) + tests nuevos.

**Frontend**: `PedidoCompraResponse.tipo_cambio_ponderado` es nuevo y opcional — clients que lo ignoran no rompen (NFR-004).

---

## 9. Rollout

**Estrategia**: 1 PR único en branch feature → merge a `develop` → validación manual → PR a `main`.

**Pasos**:
1. Branch `feature/compras-cross-moneda-y-ncs-cc` desde `develop`.
2. Backend cambios + tests unitarios pasando.
3. Frontend cambios.
4. Test integration E2E pasando local.
5. Manual QA checklist (incluido en `tasks.md`):
   - [ ] Crear OP ARS con item pedido USD + TC → OK (no 400).
   - [ ] Ejecutar OP → imp con `moneda_imputada=USD`, monto convertido, TC persistido.
   - [ ] CC del proveedor muestra HABER USD; caja ARS muestra egreso ARS.
   - [ ] `GET /pedidos-compra/{id}` devuelve `tipo_cambio_ponderado` correcto.
   - [ ] Hero del CC muestra NCs disponibles del proveedor.
   - [ ] Click "Aplicar NC" en card de pedido → modal pre-carga pedido.
   - [ ] Click "Imputar pago" en card de pedido → modal pre-carga pedido + proveedor.
   - [ ] Reversal de imp cross-moneda → DEBE USD en CC, OP no se anula (tooltip explica).
6. Merge a `develop`.
7. Validar en staging.
8. PR a `main`.

**Rollback**: revert del PR. Imputaciones cross-moneda creadas durante el periodo quedan en BD con `moneda_imputada=USD` + TC; el CC las sigue mostrando correctamente porque `aplicar_imputacion` no cambió. Frontend tolera campos opcionales ausentes.

---

## 10. Architecture Decisions (resumen + rationale)

### Decision 1: `moneda_imputada` = moneda destino, no origen
**Choice**: La imp graba `moneda_imputada = pedido.moneda` (destino), no `op.moneda` (origen).
**Alternatives considered**:
- (A) Grabar `moneda_imputada = op.moneda` y agregar campo `moneda_destino` separado.
- (B) Crear dos imps: una en moneda origen + una en moneda destino con un linking ID.
**Rationale**: opción elegida no requiere migración de schema ni cambios en `cc_proveedor_service.aplicar_imputacion`. El HABER de CC queda en la moneda real de la deuda (USD para deuda USD), que es lo contablemente correcto. Las alternativas duplican datos o agregan complejidad sin beneficio.

### Decision 2: TC obligatorio por OP, no por imp
**Choice**: el TC vive en `OrdenPago.tipo_cambio`. Cada imp cross-moneda copia ese TC.
**Alternatives considered**: TC por item de OP (cada pedido en distinta moneda podría tener TC distinto).
**Rationale**: en la práctica, el TC efectivo del momento de pago es uno solo para toda la OP. Múltiples TCs por OP complica UX y no aporta — si el user necesita TCs distintos, debe crear OPs distintas. Mantiene consistencia con `tipo_cambio_override` existente (PR #624).

### Decision 3: `tipo_cambio_ponderado` como campo derivado, no persistido
**Choice**: cálculo al vuelo con batch helper (1 query agregada).
**Alternatives considered**: columna materializada en `pedidos_compra` actualizada por trigger / job.
**Rationale**: append-only en imputaciones implica que el TC ponderado puede cambiar con cada reversal/reimputación. Mantener una columna persistida exige sincronización compleja. El batch helper espeja el patrón ya probado de `calcular_saldos_pendientes_batch`.

### Decision 4: NCs disponibles vía endpoint separado, NO inline en `/cc-proveedor/{id}/por-pedido`
**Choice**: `GET /ncs-locales/disponibles?proveedor_id=X` como endpoint dedicado.
**Alternatives considered**: incluir `ncs_disponibles[]` en el response de `/cc-proveedor/{id}/por-pedido` (root-level).
**Rationale**: cambiar el shape del response actual (`list[CCAgrupadoPorPedido]` → `{grupos, ncs_disponibles}`) rompe backward compat (NFR-004). Endpoint separado mantiene aditivo + frontend hace fetch en paralelo (overhead despreciable).

### Decision 5: Reversal cross-moneda no devuelve plata
**Choice**: `desimputar` solo crea reversal contable (DEBE en CC). Para devolver plata, user debe `anular` la OP completa.
**Alternatives considered**: reversal devuelve caja_movimiento ARS correspondiente.
**Rationale**: append-only — anular caja_movimiento implicaría UPDATE o lógica de compensación cross-modulo. La OP tiene su propio flujo de `anular` que sí hace la compensación completa. Documentar en UI evita confusión.

---

## 11. Open Questions

- [ ] **Redondeo**: `quantize(Decimal("0.01"))` usa HALF_EVEN (banker's rounding) por default de Decimal. ¿El proyecto tiene política explícita de HALF_UP? Si sí, ajustar con `ROUND_HALF_UP`. Verificar con el equipo contable antes de implementar.
- [ ] **Selector NC en ModalAplicarNC desde CC**: si el user clickea "Aplicar NC" en un card sin haber elegido NC en hero, ¿el modal muestra dropdown de NCs disponibles o exige cerrar y volver? Recomendación: dropdown auto-cargado en mount (mejor UX, +30 LOC).
- [ ] **Filtro moneda NC ↔ pedido**: cuando user aplica NC desde card, ¿filtrar NCs a las de misma moneda que el pedido, o permitir cross-moneda con TC? Por consistencia, **permitir cross-moneda en imps NC↔pedido también** (FR-001 no distingue origen OP vs NC). Confirmar.
- [ ] **`tipo_cambio_ponderado` para detalle vs listado**: ¿el endpoint detalle `GET /pedidos-compra/{id}` usa la versión single-pedido o el batch (con 1 ID)? Recomendación: single para detalle (más simple), batch para listados. Documentar.

# Design — Módulo de Compras (v1)

**Change:** `modulo-compras`
**Fase:** design
**Status:** draft
**Persistence mode:** hybrid
**Fecha:** 2026-04-17

---

## 0. Resumen ejecutivo de decisiones

| # | Tema | Decisión | Cierra OPEN_QUESTION |
|---|------|----------|----------------------|
| D1 | `ct_transaction` tipo | **BIGINT** (coincide con `tb_commercial_transactions.ct_transaction = Column(BigInteger, PK)`) | ERP-01, IMP-01 |
| D2 | Eventos de OP | **Polimórfico**: renombrar `pedido_compra_eventos` → `compras_eventos` con `entidad_tipo ∈ {'pedido_compra','orden_pago'}` | OP-01 |
| D3 | Cross-moneda en imputaciones | **Prohibido en v1** (HTTP 400). Origen/destino deben compartir moneda | OP-02 |
| D4 | Vista `v_facturas_compra_vigentes` | **Vista normal** en v1. Materialized diferida si hay lentitud real medida | ERP-03 |
| D5 | Cron reconciliación CC | **Standalone diario** (03:00 AM) — NO hook post-sync | CC-02 |
| D6 | Notificaciones admin divergencia CC | **Reuso** `alertas` (banner) + `notificaciones` (feed individual) — tablas existentes | CC-01 |
| D7 | OP.moneda ≠ Caja.moneda | **Bloquear HTTP 422** en v1. Usuario elige caja de la moneda correcta | CAJ-03 |
| D8 | `caja_service` signature real | `registrar_movimiento(caja_id, fecha, detalle, tipo, monto, user_id, categoria_id, observaciones, origen)` + `crear_documento(...)` separados. **No existe** `crear_movimiento` | CAJ-01, CAJ-02 |
| D9 | Re-imputación | **Append-only** con flag `es_reversal`. 6 combos whitelist. Cero UPDATE/DELETE | — |
| D10 | Tolerancia reconciliación | Configurable por clave `compras.cc_reconciliacion_tolerancia` en tabla `configuracion` existente | — |
| D11 | Anti-doble-contabilización | Banner sessionStorage dismissable + HTTP 409 con flag `confirmar_duplicado` | — |
| D12 | Nombre tabla ERP para catálogo | Queda como tarea previa a apply: query al ERP worker para confirmar (`tbSaleDocument`/`tb_sale_document`/`vSaleDocument`). Script aborta ruidosamente si la tabla no existe | SDC-01 (no bloqueante) |
| D13 | Reimputación de imputación ya reimputada | **Prohibida** (valida `reimputada_desde_id IS NULL` en la original) | IMP-02 |
| D14 | Mapeo `empresa_id` pricing-app ↔ `comp_id` ERP | **Hardcoded 1↔1 en v1**. Tabla de mapeo diferida a v2 | ERP-02 |
| D15 | `sd_id=125` (Reversión OP rechazada) | Clasifica como `AJUSTE_SALDO` en v1 (no requiere categoría aparte) | SDC-02 |
| D16 | Regeneración de etiqueta de retiro | HTTP 409 si ya existe. Para cambiar dirección: anular la vieja + crear nueva | LOG-03 |
| D17 | `proveedor_direccion` flag "retiro" | Usar campo `es_principal` existente como fallback + nuevo `tipo='retiro'` opcional en `etiqueta` (VARCHAR). No agregar columna | LOG-02 |
| D18 | Año de numeración | **Zona horaria Argentina (UTC-3)** del servidor | NUM-01 |
| D19 | `CajaDocumento` en anulación de OP | **Crear uno nuevo** `tipo_documento='orden_pago_anulada'` (seed adicional). Preserva trazabilidad bidireccional | CAJ-01 |
| D20 | Caja con saldo insuficiente | v1: **permitido** — caja puede quedar en negativo. Alerta UI en frontend de cajas. No bloquear | CAJ-02 |
| D21 | Numeración con rollback | Se aceptan **gaps legítimos** en la secuencia. Documentado en guía de usuario | NUM-03 |
| D22 | ERP API vs DB directa para sync catálogo | **DB directa** (reusa config del worker existente) | SDC-03 |

---

## 1. Schemas detallados

### 1.1 `pedidos_compra` (NUEVA)

```sql
CREATE TABLE pedidos_compra (
    id                    BIGSERIAL PRIMARY KEY,
    numero                VARCHAR(32)     NOT NULL,
    empresa_id            INT             NOT NULL REFERENCES empresas(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    proveedor_id          INT             NOT NULL REFERENCES proveedores(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    moneda                VARCHAR(3)      NOT NULL CHECK (moneda IN ('ARS','USD')),
    monto                 NUMERIC(18,2)   NOT NULL CHECK (monto > 0),
    fecha_pago_texto      VARCHAR(200),
    fecha_pago_estimada   DATE,
    requiere_envio        BOOLEAN         NOT NULL DEFAULT FALSE,
    numero_factura        VARCHAR(50),
    ct_transaction_id     BIGINT,  -- FK lógica a tb_commercial_transactions.ct_transaction (no FK física: tabla externa)
    estado                VARCHAR(24)     NOT NULL DEFAULT 'borrador'
                          CHECK (estado IN ('borrador','pendiente_aprobacion','aprobado','rechazado',
                                            'cancelado','pagado_parcial','pagado')),
    creado_por_id         INT             NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    aprobado_por_id       INT                      REFERENCES usuarios(id) ON DELETE SET NULL,
    created_at            TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT uq_pedidos_compra_numero UNIQUE (numero)
);

CREATE INDEX ix_pedidos_compra_empresa_estado  ON pedidos_compra (empresa_id, estado);
CREATE INDEX ix_pedidos_compra_proveedor_created ON pedidos_compra (proveedor_id, created_at DESC);
CREATE INDEX ix_pedidos_compra_numero_factura
    ON pedidos_compra (proveedor_id, numero_factura) WHERE numero_factura IS NOT NULL;
CREATE INDEX ix_pedidos_compra_ct_transaction
    ON pedidos_compra (ct_transaction_id) WHERE ct_transaction_id IS NOT NULL;
```

**DECISIÓN DE DISEÑO**: `ct_transaction_id` es **BIGINT** (D1) SIN FK física — `tb_commercial_transactions` se rellena por sync externo y una FK física implicaría referencial blocks indeseados durante el sync. Validación de existencia la hace el servicio de matching.

---

### 1.2 `compras_eventos` (NUEVA — polimórfica, reemplaza `pedido_compra_eventos`)

**DECISIÓN DE DISEÑO (D2)**: evitamos dos tablas paralelas (`pedido_compra_eventos` + `ordenes_pago_eventos`) que duplicarían índices y lógica. Usamos una sola tabla polimórfica con `entidad_tipo` VARCHAR abierto (mismo patrón que `imputaciones` y `CajaDocumento.entidad_tipo`).

```sql
CREATE TABLE compras_eventos (
    id            BIGSERIAL PRIMARY KEY,
    entidad_tipo  VARCHAR(32)  NOT NULL CHECK (entidad_tipo IN ('pedido_compra','orden_pago')),
    entidad_id    BIGINT       NOT NULL,
    tipo          VARCHAR(48)  NOT NULL,  -- 'creado','enviado_aprobacion','aprobado','rechazado',
                                          -- 'reabierto','cancelado','pago_parcial_aplicado','pago_completado',
                                          -- 'reverso_cancelacion','editado','matcheado_con_erp',
                                          -- 'etiqueta_envio_generada','op_pagada','op_anulada',
                                          -- 'op_creada_con_duplicado_confirmado'
    usuario_id    INT          NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    payload       JSONB,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX ix_compras_eventos_entidad ON compras_eventos (entidad_tipo, entidad_id, created_at DESC);
CREATE INDEX ix_compras_eventos_tipo    ON compras_eventos (tipo);
```

**Append-only enforcement**: NO se exponen rutas `PUT`/`DELETE`. A nivel DB, opcionalmente un trigger `BEFORE UPDATE OR DELETE` que raise `exception` ("compras_eventos es append-only"). v1: no incluimos el trigger (confianza en la capa servicio), se agrega en v2 si hace falta defensa adicional.

---

### 1.3 `ordenes_pago` (NUEVA)

```sql
CREATE TABLE ordenes_pago (
    id                     BIGSERIAL PRIMARY KEY,
    numero                 VARCHAR(32)    NOT NULL,
    empresa_id             INT            NOT NULL REFERENCES empresas(id) ON DELETE RESTRICT,
    proveedor_id           INT            NOT NULL REFERENCES proveedores(id) ON DELETE RESTRICT,
    moneda                 VARCHAR(3)     NOT NULL CHECK (moneda IN ('ARS','USD')),
    monto_total            NUMERIC(18,2)  NOT NULL CHECK (monto_total > 0),
    tipo_cambio            NUMERIC(18,6),  -- snapshot al pagar si aplica conversión en vista consolidada
    modo_imputacion        VARCHAR(16)    NOT NULL CHECK (modo_imputacion IN ('especifica','a_cuenta','mixta')),
    estado                 VARCHAR(16)    NOT NULL DEFAULT 'pendiente'
                           CHECK (estado IN ('pendiente','pagado','anulado')),
    caja_id                INT                     REFERENCES cajas(id) ON DELETE RESTRICT,
    caja_movimiento_id     BIGINT                  REFERENCES caja_movimientos(id) ON DELETE RESTRICT,
    caja_documento_id      INT                     REFERENCES caja_documentos(id) ON DELETE RESTRICT,
    fecha_pago_estimada    DATE,
    fecha_pago_real        DATE,
    observaciones          TEXT,
    creado_por_id          INT            NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    pagado_por_id          INT                     REFERENCES usuarios(id) ON DELETE RESTRICT,
    created_at             TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ    NOT NULL DEFAULT now(),
    paid_at                TIMESTAMPTZ,

    CONSTRAINT uq_ordenes_pago_numero UNIQUE (numero)
);

CREATE INDEX ix_ordenes_pago_proveedor_estado ON ordenes_pago (proveedor_id, estado);
CREATE INDEX ix_ordenes_pago_empresa_created  ON ordenes_pago (empresa_id, created_at DESC);
CREATE INDEX ix_ordenes_pago_caja_mov         ON ordenes_pago (caja_movimiento_id) WHERE caja_movimiento_id IS NOT NULL;
```

**DECISIÓN DE DISEÑO**: los nombres reales de las tablas de caja son `caja_movimientos`, `caja_documentos` (confirmar al generar la migration con `alembic autogenerate` y corregir si difieren). FKs `ON DELETE RESTRICT` porque anular un movimiento de caja jamás debe cascadear borrando la OP.

---

### 1.4 `imputaciones` (NUEVA)

```sql
CREATE TABLE imputaciones (
    id                      BIGSERIAL PRIMARY KEY,
    origen_tipo             VARCHAR(32)   NOT NULL,  -- ABIERTO: 'orden_pago' | 'nota_credito_erp'
    origen_id               BIGINT        NOT NULL,
    destino_tipo            VARCHAR(32)   NOT NULL,  -- ABIERTO: 'pedido_compra' | 'factura_erp' | 'saldo'
    destino_id              BIGINT,                  -- NULL SOLO si destino_tipo='saldo'
    monto_imputado          NUMERIC(18,2) NOT NULL CHECK (monto_imputado > 0),
    moneda_imputada         VARCHAR(3)    NOT NULL CHECK (moneda_imputada IN ('ARS','USD')),
    tipo_cambio             NUMERIC(18,6),
    proveedor_id            INT           NOT NULL REFERENCES proveedores(id) ON DELETE RESTRICT,
    es_reversal             BOOLEAN       NOT NULL DEFAULT FALSE,  -- D9: append-only, reversal = nueva fila
    reimputada_desde_id     BIGINT                REFERENCES imputaciones(id) ON DELETE RESTRICT,
    creado_por_id           INT           NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT chk_imputacion_saldo_id
        CHECK ((destino_tipo = 'saldo' AND destino_id IS NULL)
            OR (destino_tipo <> 'saldo' AND destino_id IS NOT NULL))
);

CREATE INDEX ix_imputaciones_proveedor_created ON imputaciones (proveedor_id, created_at DESC);
CREATE INDEX ix_imputaciones_origen            ON imputaciones (origen_tipo, origen_id);
CREATE INDEX ix_imputaciones_destino           ON imputaciones (destino_tipo, destino_id)
    WHERE destino_id IS NOT NULL;
CREATE INDEX ix_imputaciones_reversal          ON imputaciones (origen_id) WHERE es_reversal = TRUE;
```

**DECISIÓN DE DISEÑO (D9)**: la tabla es **estrictamente append-only**. Re-imputación =
  1. Nueva fila `es_reversal=TRUE` con `(origen_tipo=orig, origen_id=orig_id, destino_tipo=destino_original, destino_id=destino_original, monto=monto_original, reimputada_desde_id=imp_original.id)` → contabilmente anula el destino viejo con `debe` en CC.
  2. Nueva fila `es_reversal=FALSE` con el destino nuevo → `haber` en CC del destino nuevo.
  El servicio `imputaciones_service.reimputar()` inserta **ambas** en la misma transacción. Nunca UPDATE, nunca DELETE.

**Combos válidos v1** (constante `COMBOS_VALIDOS_V1` en `imputaciones_service.py`, coherente con state.yaml):

```python
COMBOS_VALIDOS_V1: frozenset[tuple[str, str]] = frozenset({
    ("orden_pago", "pedido_compra"),
    ("orden_pago", "factura_erp"),
    ("orden_pago", "saldo"),
    ("nota_credito_erp", "pedido_compra"),
    ("nota_credito_erp", "factura_erp"),
    ("nota_credito_erp", "saldo"),
})
```

---

### 1.5 `cc_proveedor_movimientos` (NUEVA — libro mayor)

```sql
CREATE TABLE cc_proveedor_movimientos (
    id                    BIGSERIAL PRIMARY KEY,
    proveedor_id          INT           NOT NULL REFERENCES proveedores(id) ON DELETE RESTRICT,
    empresa_id            INT           NOT NULL REFERENCES empresas(id) ON DELETE RESTRICT,
    fecha_movimiento      DATE          NOT NULL,
    tipo                  VARCHAR(8)    NOT NULL CHECK (tipo IN ('debe','haber','ajuste')),
    signo_ajuste          SMALLINT      CHECK (signo_ajuste IN (1, -1)),  -- SOLO si tipo='ajuste'
    monto                 NUMERIC(18,2) NOT NULL CHECK (monto > 0),
    moneda                VARCHAR(3)    NOT NULL CHECK (moneda IN ('ARS','USD')),
    tipo_cambio_a_ars     NUMERIC(18,6),
    origen_tipo           VARCHAR(32)   NOT NULL,  -- 'pedido_compra','orden_pago','factura_erp',
                                                   -- 'nota_credito_erp','imputacion','cancelacion_pedido',
                                                   -- 'reimputacion','ajuste_manual'
    origen_id             BIGINT,
    descripcion           VARCHAR(500),
    creado_por_id         INT                    REFERENCES usuarios(id) ON DELETE SET NULL,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT chk_cc_ajuste_signo
        CHECK ((tipo = 'ajuste' AND signo_ajuste IS NOT NULL)
            OR (tipo <> 'ajuste' AND signo_ajuste IS NULL))
);

CREATE INDEX ix_ccpm_proveedor_fecha     ON cc_proveedor_movimientos (proveedor_id, fecha_movimiento DESC, id DESC);
CREATE INDEX ix_ccpm_origen              ON cc_proveedor_movimientos (origen_tipo, origen_id);
CREATE INDEX ix_ccpm_empresa_proveedor   ON cc_proveedor_movimientos (empresa_id, proveedor_id);
CREATE INDEX ix_ccpm_proveedor_moneda    ON cc_proveedor_movimientos (proveedor_id, moneda);
```

---

### 1.6 `numeracion_contadores` (NUEVA)

```sql
CREATE TABLE numeracion_contadores (
    tipo             VARCHAR(24) NOT NULL,
    empresa_id       INT         NOT NULL REFERENCES empresas(id) ON DELETE RESTRICT,
    anio             INT         NOT NULL CHECK (anio BETWEEN 2020 AND 2100),
    ultimo_numero    INT         NOT NULL DEFAULT 0 CHECK (ultimo_numero >= 0),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tipo, empresa_id, anio)
);
```

**DECISIÓN DE DISEÑO**: uso `anio` (sin tilde) para evitar quilombos de encoding en drivers y herramientas; el nombre de columna en Python se mapea como `anio` también.

---

### 1.7 `tb_sale_document` (NUEVA — catálogo **SEED ESTÁTICO**, sin sync)

> ⚠ **SEED ESTÁTICO — NO hay sync automático**. El catálogo se popula vía **Alembic migration** con los ~43 registros conocidos (ver datos en Engram obs #106: sd_id 1-80 ventas + sd_id 101-500 compras/bancos). La tabla del ERP cambia 1-2 veces por año como máximo (tipos de documento) → no justifica cron ni script de sync. Tipos nuevos en el futuro → **nueva Alembic migration** (decisión usuario post-design, 2026-04-17, Engram obs #121). No hay endpoint admin ABM — postergado a scope futuro.

```sql
CREATE TABLE tb_sale_document (
    sd_id              INT           PRIMARY KEY,  -- viene del ERP, NO autogenerado
    sd_desc            VARCHAR(200)  NOT NULL,
    sd_iscredit        BOOLEAN       NOT NULL DEFAULT FALSE,
    sd_isquotation     BOOLEAN       NOT NULL DEFAULT FALSE,
    sd_isreceipt       BOOLEAN       NOT NULL DEFAULT FALSE,
    sd_istaxable       BOOLEAN       NOT NULL DEFAULT FALSE,
    sd_isinbalance     BOOLEAN       NOT NULL DEFAULT FALSE,
    sd_issales         BOOLEAN       NOT NULL DEFAULT FALSE,
    sd_ispurchase      BOOLEAN       NOT NULL DEFAULT FALSE,
    sd_isbanking       BOOLEAN       NOT NULL DEFAULT FALSE,
    sd_ispackinglist   BOOLEAN       NOT NULL DEFAULT FALSE,
    sd_iscreditnote    BOOLEAN       NOT NULL DEFAULT FALSE,
    sd_isdebitnote     BOOLEAN       NOT NULL DEFAULT FALSE,
    sd_isannulment     BOOLEAN       NOT NULL DEFAULT FALSE,
    sd_plusorminus     SMALLINT      NOT NULL CHECK (sd_plusorminus IN (1, -1)),
    hacc_group         INT
    -- NOTA: columna `synced_at` eliminada (refinement 2026-04-17, Engram obs #121).
    --       Ya no tiene sentido: la tabla es seed estático, no hay sync.
);

CREATE INDEX ix_tb_sale_document_ispurchase ON tb_sale_document (sd_ispurchase) WHERE sd_ispurchase = TRUE;
CREATE INDEX ix_tb_sale_document_isannul    ON tb_sale_document (sd_isannulment) WHERE sd_isannulment = TRUE;
CREATE INDEX ix_tb_sale_document_hacc       ON tb_sale_document (hacc_group) WHERE hacc_group IS NOT NULL;
```

---

### 1.8 `cc_reconciliacion_log` (NUEVA)

```sql
CREATE TABLE cc_reconciliacion_log (
    id                      BIGSERIAL PRIMARY KEY,
    fecha_corrida           DATE          NOT NULL,
    proveedor_id            INT           NOT NULL REFERENCES proveedores(id) ON DELETE RESTRICT,
    moneda                  VARCHAR(3)    NOT NULL CHECK (moneda IN ('ARS','USD')),
    saldo_libro_mayor       NUMERIC(18,2) NOT NULL,
    saldo_snapshot          NUMERIC(18,2) NOT NULL,
    diferencia              NUMERIC(18,2) NOT NULL,  -- libro_mayor - snapshot
    tolerancia_aplicada     NUMERIC(18,2) NOT NULL,
    estado                  VARCHAR(16)   NOT NULL CHECK (estado IN ('ok','divergencia')),
    nota                    VARCHAR(500),  -- llenado manual post-revisión
    alerta_id               INT                    REFERENCES alertas(id) ON DELETE SET NULL,
    notificacion_id         INT                    REFERENCES notificaciones(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT uq_reconciliacion_corrida UNIQUE (fecha_corrida, proveedor_id, moneda)
);

CREATE INDEX ix_reconciliacion_estado_fecha ON cc_reconciliacion_log (estado, fecha_corrida DESC);
CREATE INDEX ix_reconciliacion_proveedor    ON cc_reconciliacion_log (proveedor_id, fecha_corrida DESC);
```

**DECISIÓN DE DISEÑO (D6)**: `alerta_id` / `notificacion_id` nullable, apuntan a las tablas existentes `alertas` (banner global) y `notificaciones` (feed individual). El cron al detectar divergencia genera **una alerta** agregada (resumen de todos los proveedores divergentes del día) y **notificaciones individuales** a los usuarios con permiso `administracion.gestionar_ordenes_compra`. No se crea una tabla nueva.

---

### 1.9 `etiquetas_envio` (MODIFICADA — backward-compatible)

```sql
ALTER TABLE etiquetas_envio
    ADD COLUMN tipo_envio              VARCHAR(24)  NOT NULL DEFAULT 'cliente'
        CHECK (tipo_envio IN ('cliente','retiro_proveedor')),
    ADD COLUMN proveedor_id            INT                   REFERENCES proveedores(id) ON DELETE RESTRICT,
    ADD COLUMN proveedor_direccion_id  INT                   REFERENCES proveedor_direccion(id) ON DELETE RESTRICT,
    ADD COLUMN pedido_compra_id        BIGINT                REFERENCES pedidos_compra(id) ON DELETE RESTRICT;

-- Backfill explícito (aunque el default ya lo cubre, por claridad de auditoría):
UPDATE etiquetas_envio SET tipo_envio = 'cliente' WHERE tipo_envio IS NULL;

-- Check de coherencia:
ALTER TABLE etiquetas_envio
    ADD CONSTRAINT chk_etiqueta_envio_tipo_coherencia
    CHECK (
        (tipo_envio = 'cliente'
            AND proveedor_id IS NULL
            AND proveedor_direccion_id IS NULL
            AND pedido_compra_id IS NULL)
     OR
        (tipo_envio = 'retiro_proveedor'
            AND proveedor_id IS NOT NULL
            AND pedido_compra_id IS NOT NULL
            -- cliente_id puede quedar NULL; hay que verificar si hoy es NOT NULL
        )
    );

CREATE INDEX ix_etiquetas_envio_pedido ON etiquetas_envio (pedido_compra_id) WHERE pedido_compra_id IS NOT NULL;
```

**DECISIÓN DE DISEÑO**: la migración **debe inspeccionar** si `etiquetas_envio.cliente_id` es actualmente `NOT NULL`. Si lo es, se hace `ALTER COLUMN cliente_id DROP NOT NULL` antes de agregar el check. Esto se valida en el paso de tasks con una migration de 2 pasos si hace falta.

---

## 2. Contratos de servicios (Python type hints)

> Todas las signatures usan Python 3.11+ type hints. Los servicios viven en `backend/app/services/`. Las firmas son **los contratos que los tests van a fijar**.

### 2.1 `sale_document_classifier.py`

```python
from enum import Enum
from typing import Optional
from app.models.tb_sale_document import SaleDocument


class ClasificacionDocCompra(str, Enum):
    FACTURA = "FACTURA"
    NC = "NC"
    ND = "ND"
    REMITO = "REMITO"
    ORDEN_PAGO = "ORDEN_PAGO"
    ANULACION = "ANULACION"
    CONTRAPARTE = "CONTRAPARTE"
    AJUSTE_SALDO = "AJUSTE_SALDO"
    PRESUPUESTO = "PRESUPUESTO"
    IGNORAR = "IGNORAR"


def clasificar_documento_compra(sd: SaleDocument) -> ClasificacionDocCompra: ...

def afecta_cc_proveedor(sd: SaleDocument) -> bool: ...

def signo_contable(sd: SaleDocument) -> int:
    """Retorna sd.sd_plusorminus directamente (+1 o -1). No hay lógica derivada."""
    ...

def es_anulacion(sd: SaleDocument) -> bool:
    """True si sd.sd_isannulment."""
    ...

def es_contraparte(sd: SaleDocument, sd_base: SaleDocument) -> bool:
    """
    Heurística: mismo hacc_group Y sd_plusorminus invertido Y sd_id distinto.
    sd_base es el documento "principal" del que sd sería contraparte.
    """
    ...
```

**Orden de evaluación en `clasificar_documento_compra`** (coherente con obs #106):
```
if not sd.sd_ispurchase:            return IGNORAR
if sd.sd_isannulment:                return ANULACION
if sd.sd_isquotation:                return PRESUPUESTO
if sd.sd_ispackinglist:              return REMITO
if sd.sd_iscreditnote:               return NC
if sd.sd_isdebitnote:                return ND
if sd.sd_isreceipt:                  return ORDEN_PAGO
if sd.hacc_group == 20101:           return AJUSTE_SALDO   # bucket contable de ajustes
if sd.sd_isinbalance and sd.sd_istaxable: return FACTURA
return IGNORAR
```

**NO HAY NÚMEROS MÁGICOS DE `sd_id`**. El único literal es `hacc_group == 20101` (bucket ERP documentado, no un sd_id).

---

### 2.2 `imputaciones_service.py`

```python
from decimal import Decimal
from typing import Literal, Optional
from sqlalchemy.orm import Session
from app.models.imputacion import Imputacion


COMBOS_VALIDOS_V1: frozenset[tuple[str, str]] = frozenset({
    ("orden_pago", "pedido_compra"),
    ("orden_pago", "factura_erp"),
    ("orden_pago", "saldo"),
    ("nota_credito_erp", "pedido_compra"),
    ("nota_credito_erp", "factura_erp"),
    ("nota_credito_erp", "saldo"),
})


def crear_imputacion(
    session: Session,
    *,
    origen_tipo: str,
    origen_id: int,
    destino_tipo: str,
    destino_id: Optional[int],
    monto_imputado: Decimal,
    moneda_imputada: Literal["ARS", "USD"],
    proveedor_id: int,
    creado_por_id: int,
    tipo_cambio: Optional[Decimal] = None,
    es_reversal: bool = False,
    reimputada_desde_id: Optional[int] = None,
) -> Imputacion:
    """
    Crea una imputación validando:
    - (origen_tipo, destino_tipo) ∈ COMBOS_VALIDOS_V1
    - proveedor consistente con origen y destino (si destino != 'saldo')
    - moneda consistente origen/destino (D3: cross-moneda prohibido)
    - monto > 0
    En la misma transacción invoca cc_proveedor_service.aplicar_imputacion(imp).
    """
    ...


def distribuir_fifo(
    session: Session,
    *,
    orden_pago_id: int,
    user_id: int,
) -> list[Imputacion]:
    """
    Lista deudas pendientes del proveedor ordenadas por created_at ASC
    (pedidos aprobados/pagado_parcial con saldo + facturas ERP vigentes con saldo).
    Aplica el monto restante de la OP a cada deuda en orden.
    Si sobra, crea imputación (orden_pago, saldo).
    Todo en una transacción.
    """
    ...


def desimputar(
    session: Session,
    *,
    imputacion_id: int,
    user_id: int,
    motivo: str,
) -> Imputacion:
    """
    Append-only (D9): inserta fila nueva con es_reversal=True apuntando
    a imputacion_id original, mismo destino, monto original, moneda original.
    NO modifica ni borra la original.
    Valida que imputacion_id NO sea ya un reversal (no se desimputa un reversal).
    """
    ...


def reimputar(
    session: Session,
    *,
    imputacion_id: int,
    nuevo_destino_tipo: str,
    nuevo_destino_id: Optional[int],
    user_id: int,
) -> tuple[Imputacion, Imputacion]:
    """
    D13: prohíbe reimputar una imputación ya reimputada (reimputada_desde_id IS NULL en la original).
    Inserta DOS filas en la misma transacción:
      (a) reversal de la original  → es_reversal=True, destino = destino original
      (b) nueva imputación          → es_reversal=False, destino = nuevo_*
    Ambas con reimputada_desde_id = imputacion_id.
    Dispara CC: debe contra destino viejo + haber contra destino nuevo (saldo proveedor invariante).
    """
    ...


def _validar_whitelist(origen_tipo: str, destino_tipo: str) -> None:
    """Raise HTTPException(400, 'Combinación origen/destino no soportada en v1') si no válido."""
    ...
```

---

### 2.3 `ordenes_pago_service.py`

```python
from decimal import Decimal
from datetime import date
from typing import Literal, Optional
from sqlalchemy.orm import Session
from app.models.orden_pago import OrdenPago


ImputacionItem = dict  # {"tipo": str, "id": Optional[int], "monto": Decimal}


def crear(
    session: Session,
    *,
    proveedor_id: int,
    empresa_id: int,
    moneda: Literal["ARS", "USD"],
    monto_total: Decimal,
    modo_imputacion: Literal["especifica", "a_cuenta", "mixta"],
    items: list[ImputacionItem],
    observaciones: Optional[str],
    creado_por_id: int,
    confirmar_duplicado: bool = False,
) -> OrdenPago:
    """
    Valida:
    - monto_total > 0
    - modo 'especifica' → sum(items.monto) == monto_total
    - modo 'mixta' → sum(items.monto) < monto_total (remanente → saldo al pagar)
    - modo 'a_cuenta' → items vacío
    - todos los items cumplen COMBOS_VALIDOS_V1 con origen='orden_pago'
    - llama a detectar_duplicado_erp() si hay items con destino='factura_erp'
    - si hay duplicado y confirmar_duplicado=False → HTTPException(409, POSIBLE_DUPLICADO_OP_ERP)
    - si confirmar_duplicado=True → registra evento 'op_creada_con_duplicado_confirmado' en compras_eventos
    Genera numero via numeracion_service.
    NO crea imputaciones todavía — se crean al pagar.
    """
    ...


def ejecutar_pago(
    session: Session,
    *,
    orden_pago_id: int,
    caja_id: int,
    fecha_pago_real: date,
    user_id: int,
) -> OrdenPago:
    """
    Transacción única (REQ-OP-004 + REQ-CAJ-001):
    1. SELECT FOR UPDATE sobre orden_pago → estado='pendiente'
    2. Valida caja.moneda == OP.moneda (D7) — HTTP 422 si no
    3. Valida OP.proveedor_id existe y empresa coincide con caja.empresa_id
    4. Llama caja_service.registrar_movimiento(
          caja_id=caja_id, fecha=fecha_pago_real,
          detalle=f"OP {op.numero} - {proveedor.nombre}",
          tipo='egreso', monto=op.monto_total,
          user_id=user_id, origen='orden_pago',
          observaciones=op.observaciones
       )
    5. Llama caja_service.crear_documento(
          tipo_documento_id=<id del seed 'orden_pago'>,
          numero=op.numero, entidad_tipo='orden_pago', entidad_id=op.id,
          movimiento_ids=[mov.id], user_id=user_id
       )
    6. Crea imputaciones según items → cc_proveedor_service.aplicar_imputacion por cada una
    7. Si modo='mixta' y sobra remanente → crea imputación (orden_pago, saldo, remanente)
    8. Set op.caja_movimiento_id, op.caja_documento_id, op.estado='pagado', paid_at, etc.
    9. Inserta evento 'op_pagada' en compras_eventos
    Rollback total si cualquier paso falla.
    """
    ...


def anular(
    session: Session,
    *,
    orden_pago_id: int,
    motivo: str,
    user_id: int,
) -> OrdenPago:
    """
    Transición pagado → anulado. Crea movimiento de ingreso en misma caja,
    nuevo CajaDocumento tipo='orden_pago_anulada' (D19), reversal de imputaciones
    (es_reversal=True para cada imputación original), re-transiciona pedidos afectados
    de pagado/pagado_parcial hacia aprobado. Inserta evento 'op_anulada'.
    """
    ...


def detectar_duplicado_erp(
    session: Session,
    *,
    proveedor_id: int,
    numeros_factura: list[str],
) -> list[dict]:
    """
    Ejecuta query de detección (§5 Anti-doble-contabilización).
    Retorna [] si no hay match. Si hay, retorna:
    [{"ct_transaction": int, "ct_date": date, "ct_docnumber": str, "ct_total": Decimal}]
    """
    ...
```

---

### 2.4 `cc_proveedor_service.py`

```python
from decimal import Decimal
from datetime import date
from typing import Literal, Optional
from sqlalchemy.orm import Session
from app.models.cc_proveedor_movimiento import CCProveedorMovimiento


def insertar_mov(
    session: Session,
    *,
    proveedor_id: int,
    empresa_id: int,
    fecha_movimiento: date,
    tipo: Literal["debe", "haber", "ajuste"],
    monto: Decimal,
    moneda: Literal["ARS", "USD"],
    origen_tipo: str,
    origen_id: Optional[int],
    descripcion: Optional[str] = None,
    creado_por_id: Optional[int] = None,
    signo_ajuste: Optional[int] = None,
) -> CCProveedorMovimiento:
    """
    Inserción única en cc_proveedor_movimientos.
    Resuelve tipo_cambio_a_ars consultando tabla tipo_cambio con
    `fecha <= fecha_movimiento ORDER BY fecha DESC LIMIT 1` (patrón estándar).
    Si tipo='ajuste', requiere signo_ajuste ∈ {+1, -1}.
    """
    ...


def aplicar_imputacion(
    session: Session,
    *,
    imputacion_id: int,
) -> list[CCProveedorMovimiento]:
    """
    Se llama desde imputaciones_service dentro de la misma transacción.
    Inserta los movimientos de libro mayor correspondientes:
    - Imputación normal (es_reversal=False): 1 haber con origen_tipo='imputacion'
    - Imputación reversal (es_reversal=True):  1 debe con origen_tipo='reimputacion'
    Retorna lista de movimientos creados.
    """
    ...


def calcular_saldo_por_moneda(
    session: Session,
    *,
    proveedor_id: int,
    hasta_fecha: Optional[date] = None,
) -> dict[str, Decimal]:
    """
    SELECT moneda, SUM(CASE WHEN tipo='debe' THEN monto
                            WHEN tipo='haber' THEN -monto
                            WHEN tipo='ajuste' THEN signo_ajuste * monto END)
    GROUP BY moneda
    Retorna: {"ARS": Decimal("15000.00"), "USD": Decimal("320.50")}
    (incluye monedas con saldo 0 si hay movimientos; omite monedas sin movimientos)
    """
    ...


def reconciliar_diario(
    session: Session,
    *,
    fecha_corrida: date,
) -> dict[str, int]:
    """
    Standalone job (D5). Para cada proveedor activo con movimientos
    en últimos 365 días:
    1. Calcula saldo por moneda desde cc_proveedor_movimientos.
    2. Lee saldo snapshot de cuentas_corrientes_proveedores.
    3. Lee tolerancia de tabla `configuracion`, clave 'compras.cc_reconciliacion_tolerancia'.
    4. Compara y crea fila en cc_reconciliacion_log con estado 'ok'|'divergencia'.
    5. Si hay ≥1 divergencia en la corrida: crea 1 Alerta (banner) + N Notificaciones.
    Retorna resumen: {"proveedores_procesados": N, "divergencias": M, "alertas_creadas": K}.
    """
    ...
```

---

### 2.5 `erp_matching_service.py`

```python
from typing import Optional
from sqlalchemy.orm import Session
from app.models.commercial_transaction import CommercialTransaction
from app.models.pedido_compra import PedidoCompra


def match_forward(
    session: Session,
    *,
    pedido_id: int,
) -> Optional[CommercialTransaction]:
    """
    Pedido → Factura.
    Dado un pedido con numero_factura SET, busca en v_facturas_compra_vigentes
    con tupla (comp_id, bra_id, supp_id, ct_docnumber).
    Si hay match único:
      - set pedido.ct_transaction_id = ct.ct_transaction (BIGINT, D1)
      - inserta evento 'matcheado_con_erp'
    Retorna el ct matcheado o None.
    """
    ...


def match_backward(
    session: Session,
    *,
    cts_synced: list[int],  # lista de ct_transaction (BIGINT) agregados/actualizados en la corrida
) -> dict[str, int]:
    """
    Factura → Pedido. Llamado desde el hook inline de
    sync_commercial_transactions_guid.py.
    Pre-check: SELECT COUNT(*) FROM tb_sale_document > 0, sino ABORTA
    con log [ERROR] + alerta admin (REQ-ERP-006).
    Itera cts_synced, filtra los vigentes via v_facturas_compra_vigentes,
    y busca pedidos con numero_factura = ct_docnumber AND
    proveedor → supp_id AND ct_transaction_id IS NULL.
    Asocia y registra evento.
    Retorna: {"pedidos_asociados": N, "cts_procesadas": M, "errores": K}.
    """
    ...
```

---

### 2.6 `numeracion_service.py`

```python
from sqlalchemy.orm import Session
from datetime import datetime
from zoneinfo import ZoneInfo


PREFIX: dict[str, str] = {
    "pedido": "P",
    "orden_pago": "OP",
}

TZ_ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")


def generar_siguiente_numero(
    session: Session,
    *,
    tipo: str,
    empresa_id: int,
    anio: int | None = None,
) -> tuple[str, int]:
    """
    Genera el próximo correlativo dentro de la transacción del caller.
    Si anio es None, se toma datetime.now(TZ_ARGENTINA).year (D18).

    Flujo (REQ-NUM-003):
    1. Valida tipo ∈ PREFIX, raise ValueError si no.
    2. SELECT ultimo_numero FROM numeracion_contadores
         WHERE tipo=:tipo AND empresa_id=:eid AND anio=:anio FOR UPDATE;
    3. Si no hay fila → INSERT con ultimo_numero=1, nuevo=1.
       Si hay fila → UPDATE SET ultimo_numero=ultimo_numero+1, nuevo=ultimo_numero+1.
    4. Formato: f"{PREFIX[tipo]}-{empresa_id:02d}-{anio:04d}-{nuevo:05d}".
    5. Retorna (numero_string, nuevo_int).

    Lock se libera al commit del caller.
    Gaps legítimos en la secuencia son aceptables (D21).
    """
    ...
```

---

## 3. Integración con Cajas (signature real)

### 3.1 Hallazgo: la función es `registrar_movimiento`, NO `crear_movimiento`

Los specs usan `caja_service.crear_movimiento` (herencia de obs #103 que también lo mencionaba así). La realidad del código (`backend/app/services/caja_service.py:129`) es:

```python
class CajaService:
    def registrar_movimiento(
        self,
        caja_id: int,
        fecha: date,
        detalle: str,
        tipo: str,                         # 'ingreso' | 'egreso'
        monto: Decimal,
        user_id: Optional[int] = None,
        categoria_id: Optional[int] = None,
        observaciones: Optional[str] = None,
        origen: str = "manual",            # <-- usamos 'orden_pago'
    ) -> CajaMovimiento:
        # SELECT FOR UPDATE en Caja (lock pesimista)
        # Calcula saldo_posterior
        # Inserta CajaMovimiento + actualiza caja.saldo_actual en misma tx
```

Y la creación del `CajaDocumento` es otra función separada (`caja_service.py:428`):

```python
def crear_documento(
    self,
    tipo_documento_id: int,
    user_id: int,
    numero: Optional[str] = None,
    descripcion: Optional[str] = None,
    fecha_documento: Optional[date] = None,
    monto_documento: Optional[Decimal] = None,
    movimiento_ids: Optional[list[int]] = None,   # crea links CajaDocumentoMovimiento
    entidad_tipo: Optional[str] = None,           # <-- 'orden_pago'
    entidad_id: Optional[int] = None,             # <-- op.id
) -> CajaDocumento:
    ...
```

**DECISIÓN DE DISEÑO (D8)**: `ordenes_pago_service.ejecutar_pago()` invoca **ambas** secuencialmente dentro de su transacción. NO se tocan estas funciones (se respeta el principio "ni pedido, ni pedido, ni pedido" — ni modificamos Cajas).

### 3.2 OP.moneda ≠ Caja.moneda

**DECISIÓN DE DISEÑO (D7 / CAJ-03)**: **bloquear con HTTP 422** en v1. Razón:
- `registrar_movimiento` NO acepta parámetro `moneda` (la moneda es propiedad de la `Caja`).
- Hacer conversión implícita con TC sin que el usuario lo confirme expone la operación a errores sutiles y dificulta la reconciliación.
- El usuario debe elegir explícitamente una caja de la moneda correcta.

Payload del error:

```json
{
  "detail": "La caja seleccionada (id=5, moneda=ARS) no coincide con la moneda de la OP (USD). Elegí una caja en USD o creá una nueva.",
  "codigo": "OP_CAJA_MONEDA_MISMATCH"
}
```

Conversión con TC automática queda **diferida a v2** (requiere: selector de TC en el form de pago, validación de TC vigente, impacto en saldo estimado ARS, política de ajuste por diferencia de cambio post-pago).

---

## 4. Vistas SQL

### 4.1 `v_facturas_compra_vigentes`

**DECISIÓN DE DISEÑO (D4)**: vista normal en v1. Medir tiempo de query en producción con 6 meses de operación. Si p95 > 500ms, considerar `MATERIALIZED VIEW` con `REFRESH CONCURRENTLY` post-sync en v1.5.

```sql
CREATE OR REPLACE VIEW v_facturas_compra_vigentes AS
WITH anuladas AS (
    -- Tuplas (supp_id, ct_docnumber) que tienen al menos una anulación asociada
    SELECT DISTINCT ct.supp_id, ct.ct_docnumber
    FROM tb_commercial_transactions ct
    JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
    WHERE sd.sd_isannulment = TRUE
      AND ct.supp_id IS NOT NULL
      AND ct.ct_docnumber IS NOT NULL
),
base AS (
    -- Documentos principales de compra (no anulaciones, no contrapartes, no remitos, no presupuestos)
    SELECT
        ct.ct_transaction,
        ct.comp_id,
        ct.bra_id,
        ct.supp_id,
        ct.ct_docnumber,
        ct.ct_total,
        ct.curr_id_transaction,
        ct.ct_date,
        ct.sd_id,
        sd.sd_desc,
        sd.hacc_group,
        sd.sd_plusorminus,
        CASE
            WHEN sd.sd_iscreditnote  THEN 'NC'
            WHEN sd.sd_isdebitnote   THEN 'ND'
            WHEN sd.sd_isreceipt     THEN 'ORDEN_PAGO'
            WHEN sd.sd_isinbalance AND sd.sd_istaxable THEN 'FACTURA'
            ELSE 'OTRO'
        END AS clasificacion
    FROM tb_commercial_transactions ct
    JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
    WHERE sd.sd_ispurchase = TRUE
      AND sd.sd_isannulment = FALSE
      AND sd.sd_ispackinglist = FALSE
      AND sd.sd_isquotation = FALSE
      AND COALESCE(ct.ct_kindof, '') <> 'X'   -- remitos obs #104
      AND ct.supp_id IS NOT NULL
      AND ct.ct_docnumber IS NOT NULL
),
contrapartes AS (
    -- Identifica filas de `base` que son contrapartes de otra fila con mismo hacc_group y signo invertido
    SELECT b1.ct_transaction
    FROM base b1
    JOIN base b2
      ON b1.supp_id        = b2.supp_id
     AND b1.ct_docnumber   = b2.ct_docnumber
     AND b1.comp_id        = b2.comp_id
     AND b1.bra_id         = b2.bra_id
     AND b1.hacc_group     = b2.hacc_group
     AND b1.sd_plusorminus = -b2.sd_plusorminus
     AND b1.ct_transaction <> b2.ct_transaction
    WHERE b1.sd_id > b2.sd_id          -- el "mayor" se considera contraparte, el "menor" queda como base
)
SELECT b.*
FROM base b
LEFT JOIN anuladas a
       ON a.supp_id = b.supp_id AND a.ct_docnumber = b.ct_docnumber
WHERE a.supp_id IS NULL                -- excluye tuplas con anulación posterior
  AND b.ct_transaction NOT IN (SELECT ct_transaction FROM contrapartes);
```

**DECISIÓN DE DISEÑO**: la heurística de contraparte "`sd_id` mayor es contraparte del `sd_id` menor" es un **convenio operativo** derivado de obs #106 (ej. 101 es base, 161 es contraparte; 151 es anulación — detectada por flag, no por orden). Documentar explícitamente en la vista y cubrir con fixture de JUKEBOX (`00389000` con 101+151+161 → solo 101 sale).

---

## 5. Hook en `sync_commercial_transactions_guid.py`

**Pseudocódigo al final del script** (antes del exit):

```python
# ... fin de la sincronización existente ...
# cts_synced: list[int] acumulado durante la corrida actual

try:
    from app.services.erp_matching_service import match_backward

    # Validación defensiva (REQ-ERP-006 / D)
    catalogo_count = session.execute(
        text("SELECT COUNT(*) FROM tb_sale_document")
    ).scalar_one()

    if catalogo_count == 0:
        logger.error(
            "[ERROR] run_matching_on_recent_cts abortado: tb_sale_document está vacío. "
            "El clasificador no puede operar sin catálogo. "
            "Verificar que la migración de seed estático (compras_NNNN_seed_tb_sale_document) se haya ejecutado."
        )
        # Alerta admin via Notificacion (existe)
        notificacion_service.crear_notificacion(
            session=session,
            titulo="Catálogo tb_sale_document vacío",
            mensaje="El hook de matching se abortó porque tb_sale_document está vacío. Verificar ejecución del seed Alembic (compras_NNNN_seed_tb_sale_document).",
            severidad="error",
            destinatarios_rol="ADMIN",
        )
        session.commit()
    else:
        resumen = match_backward(session=session, cts_synced=cts_synced)
        logger.info(
            "matching_run: %s pedidos asociados, %s ct procesadas, %s errores",
            resumen["pedidos_asociados"],
            resumen["cts_procesadas"],
            resumen["errores"],
        )
        session.commit()

except Exception as exc:
    # NO hacer fallar el cron de sync
    logger.exception("[ERROR] matching_hook falló: %s", exc)
    session.rollback()

# exit 0
```

Puntos clave:
- **No levanta excepción hacia el cron**: el sync base debe seguir andando aunque el matching se rompa.
- **Cataloga vacío = aborta con alerta, no con exception**: cumple REQ-ERP-006.
- **Alerta vía `Notificacion` existente** (D6): reusamos `notificacion_service.crear_notificacion` con severidad `error`.

---

## 6. State machine de pedidos (diagrama ASCII)

```
                            ┌──────────────────┐
                            │    borrador      │◄────────────┐
                            └──────┬─────┬─────┘             │
               enviar_aprobacion   │     │  cancelar         │ reabrir
                                   ▼     ▼                   │
                      ┌──────────────────────┐       ┌───────┴─────┐
                      │ pendiente_aprobacion │       │  rechazado  │
                      └──────┬──────┬────────┘       └──────┬──────┘
                    aprobar  │      │ rechazar              │
                             │      │ (accion=devolver)     │ cancelar_definitivo
                             ▼      │                       ▼
                      ┌──────────┐  └────────────► (a rechazado)        ┌──────────────┐
              ┌──────►│ aprobado │                                      │  cancelado   │◄────┐
              │       └─┬─┬──┬───┘ cancelar                             │  (terminal)  │     │
   (reverso   │         │ │  └──────────────────────────────────────────┤              │     │
    por OP    │  imp.   │ │                                             └──────────────┘     │
    anulada)  │ parcial │ │ imp. total                                                       │
              │         ▼ │                                                                  │
              │   ┌─────────────┐     imp. completa                                          │
              └───┤pagado_parcial├────────────────┐                                          │
                  └──────┬──────┘                 │                                          │
                         │                        ▼                                          │
                         └──────────────► ┌───────────────┐                                  │
                                          │    pagado     │                                  │
                                          │  (terminal)   │                                  │
                                          └───────────────┘                                  │
                                                                                             │
 Nota: `aprobado → cancelado` dispara reverso en CC (debe → haber por ajuste).───────────────┘
```

### Matriz transición × permiso requerido

| Desde | Hacia | Acción | Permiso mínimo | Tipo |
|-------|-------|--------|----------------|------|
| borrador | pendiente_aprobacion | enviar_aprobacion | `gestionar_ordenes_compra` (156) | manual |
| borrador | cancelado | cancelar | `gestionar_ordenes_compra` (156) | manual |
| pendiente_aprobacion | aprobado | aprobar | `aprobar_ordenes_compra` (NUEVO, crítico) | manual |
| pendiente_aprobacion | rechazado | rechazar(devolver_a_borrador) | `aprobar_ordenes_compra` | manual |
| pendiente_aprobacion | cancelado | rechazar(cancelar_definitivo) | `aprobar_ordenes_compra` | manual |
| rechazado | borrador | reabrir | `gestionar_ordenes_compra` (creador o aprobador) | manual |
| rechazado | cancelado | cancelar_definitivo | `aprobar_ordenes_compra` | manual |
| aprobado | pagado_parcial | — | (automático al crear imputación parcial desde OP pagada) | sistema |
| aprobado | pagado | — | (automático al crear imputación total) | sistema |
| aprobado | cancelado | cancelar_aprobado | `aprobar_ordenes_compra` (crítico) | manual + reverso CC |
| pagado_parcial | pagado | — | (automático al cubrir saldo) | sistema |

Estados terminales (sin salida): `pagado`, `cancelado`.
Saltos prohibidos ejemplo: `borrador → aprobado` = HTTP 400.

---

## 7. Anti-doble-contabilización (R9 / OP-005)

### 7.1 Query exacta de detección

```sql
SELECT
    ct.ct_transaction,
    ct.ct_date,
    ct.ct_total,
    ct.ct_docnumber
FROM tb_commercial_transactions ct
WHERE ct.supp_id = :supp_id
  AND ct.sd_id = 106                              -- "Orden de Pago" ERP
  AND ct.ct_docnumber IN :numeros_factura         -- tuple bind
  AND ct.ct_date >= CURRENT_DATE - INTERVAL '7 days'
  AND COALESCE(ct.ct_iscancelled, FALSE) = FALSE
ORDER BY ct.ct_date DESC
LIMIT 50;
```

**DECISIÓN DE DISEÑO**: el literal `sd_id = 106` es la **única excepción al principio "no números mágicos"** porque es el identificador del ERP para el tipo "Orden de Pago" (obs #106). Se documenta en constante:

```python
# backend/app/core/compras_erp_constants.py
ERP_SD_ID_ORDEN_PAGO: Final[int] = 106  # ERP: tipo documento "Orden de Pago"
```

El clasificador **sigue siendo flag-based** para toda clasificación general; esta constante es **solo para detección de duplicado** porque requiere buscar *específicamente* ese tipo de documento en el ERP.

### 7.2 Payload HTTP 409

```json
{
  "codigo": "POSIBLE_DUPLICADO_OP_ERP",
  "mensaje": "Detectamos en el ERP una OP reciente para este proveedor con los mismos números de factura. Verificá antes de continuar.",
  "duplicados_detectados": [
    {
      "ct_transaction": 768710,
      "ct_date": "2026-04-15",
      "ct_docnumber": "FA-00012345",
      "ct_total": "19420875.00"
    }
  ],
  "flag_confirmacion": "confirmar_duplicado"
}
```

### 7.3 Flujo frontend

```
1. Usuario llena form "Nueva OP" → submit
2. Si banner activo en sessionStorage → visible arriba del form
3. POST /api/administracion/compras/ordenes-pago  (confirmar_duplicado omitido)
4. Backend detecta match → HTTP 409 con payload de 7.2
5. Frontend muestra ModalTesla con:
   - Título: "⚠ Posible duplicado detectado en ERP"
   - Lista de duplicados (ct_transaction, fecha, docnumber, total)
   - Link "Ver en ERP" (si aplicable)
   - Botones: [Cancelar] [Confirmar, es un pago distinto]
6. Si usuario cancela → no se crea OP, form queda abierto con datos
7. Si usuario confirma → POST con body + `confirmar_duplicado: true`
8. Backend crea OP igual + inserta evento 'op_creada_con_duplicado_confirmado' en compras_eventos
   con payload { ct_transaction_duplicada: [...], motivo_usuario: "..." (si se pidió) }
```

### 7.4 Banner sessionStorage

- **Key**: `compras_op_doble_contab_banner_dismissed_${user_id}_${YYYYMMDD}`
- **Almacena**: `"true"` cuando usuario hace click en "Entendido".
- **TTL**: automático al cerrar tab (sessionStorage).
- **Reset diario**: como la key incluye `YYYYMMDD`, al cambiar el día aparece de nuevo aunque la sesión siga abierta.
- **Texto**: "Si este pago ya se registró directamente en el ERP, NO lo cargues aquí. Se contabilizaría dos veces."

---

## 8. Reconciliación diaria CC

### 8.1 Cron standalone

**DECISIÓN DE DISEÑO (D5)**: **NO** es hook post-sync. Cron independiente en `backend/app/scripts/reconciliar_cc_proveedor.py`, ejecución **03:00 AM**.

Justificación:
- Aislamiento: un fallo en el sync de ct no debe romper la reconciliación, y viceversa.
- Cadencia distinta: sync corre cada 10 min, reconciliación 1x/día. Acoplarlos daría una reconciliación sin sentido cada 10 min.
- Re-ejecutable manualmente desde admin con el mismo entrypoint (permite backfill de días perdidos).

### 8.2 Algoritmo

```python
def reconciliar_cc_proveedor(fecha_corrida: date) -> dict:
    tolerancia_ars = leer_configuracion('compras.cc_reconciliacion_tolerancia', default=Decimal('100.00'))
    # v1: misma tolerancia para todas las monedas (simple). v2: claves separadas si hace falta.

    divergencias = []
    proveedores = listar_proveedores_con_movimientos_ultimos_365_dias()

    for prov in proveedores:
        saldos_mayor = cc_proveedor_service.calcular_saldo_por_moneda(
            session, proveedor_id=prov.id
        )
        for moneda, saldo_mayor in saldos_mayor.items():
            saldo_snap = leer_snapshot_cc(prov.id, moneda)  # tabla cuentas_corrientes_proveedores
            if saldo_snap is None:
                continue  # sin snapshot, no hay nada que comparar

            diferencia = abs(saldo_mayor - saldo_snap)
            estado = 'ok' if diferencia <= tolerancia_ars else 'divergencia'

            log = CCReconciliacionLog(
                fecha_corrida=fecha_corrida,
                proveedor_id=prov.id,
                moneda=moneda,
                saldo_libro_mayor=saldo_mayor,
                saldo_snapshot=saldo_snap,
                diferencia=diferencia,
                tolerancia_aplicada=tolerancia_ars,
                estado=estado,
            )
            session.add(log)
            if estado == 'divergencia':
                divergencias.append(log)

    session.flush()

    if divergencias:
        # 1 Alerta banner agregada
        alerta = alertas_service.crear_alerta(
            titulo=f"Reconciliación {fecha_corrida}: {len(divergencias)} divergencias",
            mensaje=f"El libro mayor y el snapshot ERP difieren en {len(divergencias)} casos. "
                    f"Ver /administracion/compras/reconciliacion",
            variant='warning',
            roles_destinatarios=['ADMIN'],
            action_label='Ver detalle',
            action_url='/administracion/compras/reconciliacion',
            activo=True,
        )
        # N notificaciones individuales a usuarios con permiso administracion.gestionar_ordenes_compra
        for div in divergencias:
            notif = notificacion_service.crear_notificacion(
                titulo=f"Divergencia CC: {div.proveedor.nombre} ({div.moneda})",
                mensaje=f"Mayor: {div.saldo_libro_mayor}  |  Snapshot: {div.saldo_snapshot}  |  Diferencia: {div.diferencia}",
                severidad='warning',
                permiso_destinatario='administracion.gestionar_ordenes_compra',
            )
            div.alerta_id = alerta.id
            div.notificacion_id = notif.id

    session.commit()
    return {
        "proveedores_procesados": len(proveedores),
        "divergencias": len(divergencias),
        "alertas_creadas": 1 if divergencias else 0,
    }
```

### 8.3 Reuso de tablas existentes para notificaciones (D6 cierra CC-01)

Hallazgo del grep: existen **ambas** tablas:

- `alertas` (`backend/app/models/alerta.py`): **banners globales** con `roles_destinatarios` JSONB, `variant`, `dismissible`, `persistent`, `fecha_desde/hasta`. **Ideal para la alerta agregada diaria.**
- `notificaciones` (`backend/app/models/notificacion.py`): **feed individual** con `severidad`, `estado`, destinatario por `usuario`. **Ideal para notificar a cada admin gestor con un item por divergencia.**

**NO se crea una tabla nueva.** Se reusa ambas con semántica complementaria:
- 1 Alerta por corrida (si hay ≥1 divergencia).
- N Notificaciones por corrida (una por divergencia).
- `cc_reconciliacion_log.alerta_id` + `notificacion_id` apuntan al vínculo para trazabilidad.

---

## 9. Endpoints REST

Prefijo común: `/api/administracion/compras`. Todos requieren `Depends(get_current_user)` + chequeo de permiso. Todos tienen `response_model`.

### 9.1 Pedidos

| Método | Path | Body | Response | Errores |
|--------|------|------|----------|---------|
| GET | `/pedidos` | query: estado, proveedor_id, empresa_id, desde, hasta, page, page_size | `PedidosCompraPaginated` | 401 |
| GET | `/pedidos/{id}` | — | `PedidoCompraDetalle` (incluye eventos, imputaciones relacionadas, ct asociada) | 404 |
| POST | `/pedidos` | `PedidoCompraCreate` | `PedidoCompraResponse` (201) | 403, 422 |
| PUT | `/pedidos/{id}` | `PedidoCompraUpdate` | `PedidoCompraResponse` | 403, 404, 409 (estado != borrador) |
| POST | `/pedidos/{id}/enviar-aprobacion` | — | `PedidoCompraResponse` | 400 (transición), 403 |
| POST | `/pedidos/{id}/aprobar` | `{fecha_pago_estimada?: date}` | `PedidoCompraResponse` | 403 (crítico), 400 |
| POST | `/pedidos/{id}/rechazar` | `{accion: 'devolver_a_borrador' \| 'cancelar_definitivo', motivo: str}` | `PedidoCompraResponse` | 400 (accion faltante), 403 |
| POST | `/pedidos/{id}/reabrir` | — | `PedidoCompraResponse` | 400, 403 |
| POST | `/pedidos/{id}/cancelar` | `{motivo: str}` | `PedidoCompraResponse` | 400 (transición), 403 |
| POST | `/pedidos/{id}/generar-etiqueta-envio` | `{proveedor_direccion_id?: int}` | `EtiquetaEnvioResponse` | 400, 409 (ya existe) |
| GET | `/pedidos/{id}/eventos` | — | `list[CompraEventoResponse]` | 404 |

### 9.2 Órdenes de Pago

| Método | Path | Body | Response | Errores |
|--------|------|------|----------|---------|
| GET | `/ordenes-pago` | query: estado, proveedor_id, empresa_id, desde, hasta, page | `OrdenPagoPaginated` | 401 |
| GET | `/ordenes-pago/{id}` | — | `OrdenPagoDetalle` (incluye imputaciones) | 404 |
| POST | `/ordenes-pago` | `OrdenPagoCreate` (incluye `items[]`, `confirmar_duplicado?: bool`) | `OrdenPagoResponse` (201) | 400, 403, **409 POSIBLE_DUPLICADO_OP_ERP** |
| POST | `/ordenes-pago/{id}/pagar` | `{caja_id: int, fecha_pago_real: date}` | `OrdenPagoResponse` | 403 (crítico `ejecutar_pagos`), **422 OP_CAJA_MONEDA_MISMATCH**, 400 |
| POST | `/ordenes-pago/{id}/anular` | `{motivo: str}` | `OrdenPagoResponse` | 403, 400 |
| POST | `/ordenes-pago/{id}/distribuir-automatico` | — | `list[ImputacionResponse]` | 400, 403 |

### 9.3 Imputaciones

| Método | Path | Body | Response | Errores |
|--------|------|------|----------|---------|
| GET | `/imputaciones` | query: proveedor_id, origen_tipo, destino_tipo, desde, hasta | `ImputacionPaginated` | 401 |
| POST | `/imputaciones/{id}/desimputar` | `{motivo: str}` | `ImputacionResponse` (la compensatoria) | 403, 400 |
| POST | `/imputaciones/{id}/reimputar` | `{destino_tipo: str, destino_id?: int}` | `list[ImputacionResponse]` (2 filas: reversal + nueva) | 400 (combo inválido, cadena), 403 |

### 9.4 CC Proveedor

| Método | Path | Body | Response | Errores |
|--------|------|------|----------|---------|
| GET | `/cc-proveedor/{proveedor_id}` | query: empresa_id?, hasta_fecha? | `CCProveedorDetalle` (saldos por moneda + movimientos + consolidado estimado) | 404 |
| GET | `/cc-proveedor/{proveedor_id}/por-pedido` | — | `list[CCAgrupadoPorPedido]` | 404 |
| GET | `/reconciliacion` | query: fecha_desde?, fecha_hasta?, estado? | `list[CCReconciliacionLogResponse]` | 401 |
| POST | `/reconciliacion/forzar` | `{fecha?: date}` | `{proveedores_procesados, divergencias, alertas_creadas}` | 403 (admin) |
| GET | `/reconciliacion/metricas` | — | `{dias_consecutivos_sin_divergencia, cobertura_porcentaje, criterio_deprecacion}` | 401 |

### 9.5 Sale Document Catalog

| Método | Path | Body | Response | Errores |
|--------|------|------|----------|---------|
| GET | `/sale-documents` | — | `list[SaleDocumentResponse]` (con `clasificacion` derivada) | 401 |
| POST | `/sale-documents/sync` | — | `{upserts, sin_cambios, duracion_ms}` | 403 (admin) |
| GET | `/sale-documents/faltantes` | — | `list[{sd_id, count, primera_aparicion}]` (sd_id en ct recientes no catalogados) | 401 |

---

## 10. Open questions resueltas (tracking de cierre)

| OQ | Spec | Cierre | Decisión D# |
|----|------|--------|-------------|
| PED-01 | adjuntos en v1 | v2 (queda fuera de scope) | — |
| PED-02 | reasignar creado_por_id | no; mantener histórico | — |
| OP-01 | tabla de eventos OP | **polimórfica** `compras_eventos` | D2 |
| OP-02 | cross-moneda OP ↔ destino | **prohibido v1** (HTTP 400) | D3 |
| IMP-01 | `destino_id` tipo para factura_erp | **BIGINT** = `ct_transaction` del ERP | D1 |
| IMP-02 | reimputación en cadena | **prohibida** (valida `reimputada_desde_id IS NULL`) | D13 |
| CC-01 | notificaciones admin | **reuso** `alertas` + `notificaciones` | D6 |
| CC-02 | cron reconciliación | **standalone** diario | D5 |
| ERP-01 | `ct_transaction_id` tipo | **BIGINT** | D1 |
| ERP-02 | mapeo empresa_id ↔ comp_id | hardcoded 1↔1 v1 | D14 |
| ERP-03 | vista materialized | **normal** v1 | D4 |
| SDC-01 | nombre tabla ERP | query al ERP antes de apply (no bloqueante para design) | D12 |
| SDC-02 | sd_id=125 categoría | `AJUSTE_SALDO` | D15 |
| SDC-03 | ERP API vs DB | **DB directa** (reusa config worker) | D22 |
| LOG-01 | generación auto al aprobar | **explícita** (endpoint separado) | — |
| LOG-02 | flag "retiro" en dirección | reuso `es_principal` + `etiqueta='retiro'` opcional | D17 |
| LOG-03 | regenerar etiqueta | HTTP 409; anular vieja + crear nueva | D16 |
| CAJ-01 | CajaDocumento en anulación | nuevo tipo `'orden_pago_anulada'` | D19 |
| CAJ-02 | saldo insuficiente | permitido (alerta, no bloqueo) | D20 |
| CAJ-03 | conversión TC cross-moneda | **bloqueado HTTP 422** v1 | D7 |
| NUM-01 | zona horaria año | **Argentina UTC-3** | D18 |
| NUM-02 | reserva de bloques | **no** en v1, todo vía servicio | — |
| NUM-03 | gaps por rollback | **aceptables** y documentados | D21 |

**Total**: 23 OPEN_QUESTIONS cerradas (21 originales + 2 agregadas durante design: D8 signature real caja_service, D10 tolerancia configuracion).

---

## 11. Riesgos emergentes (post-design)

> **Refinement 2026-04-17** (Engram obs #121): `tb_sale_document` es **seed estático Alembic**, NO hay sync. Se reescribió R1 en consecuencia y se eliminaron menciones al cron de sync.

| # | Riesgo | Severidad | Mitigación |
|---|--------|-----------|------------|
| R1 | **Si GBP agrega un `sd_id` nuevo en el ERP sin notificarnos**, aparece en `tb_commercial_transactions` sin estar en nuestro catálogo local `tb_sale_document` → el clasificador lo marca como `UNKNOWN` → matching lo ignora y se puede perder una factura. | medio | (a) Panel admin read-only (§9.5) lista `sd_id` no catalogados detectados en los últimos 30 días; (b) revisión mensual de ese listado por el equipo admin; (c) si aparece un `sd_id` nuevo → **nueva Alembic migration** que hace INSERT de la fila (no hay sync automático por diseño). Log WARNING server-side si la query de detección retorna filas. |
| RD1 | Al migrar `etiquetas_envio`, si `cliente_id` hoy es NOT NULL, el check constraint falla en las filas legacy si queda mal planteado. | medio | Migration en 2 pasos: (a) `DROP NOT NULL` de `cliente_id`; (b) add check constraint. Validar pre-migration con query `SELECT is_nullable FROM information_schema.columns`. |
| RD2 | La vista `v_facturas_compra_vigentes` con CTE de contrapartes podría ser lenta bajo millones de filas. | medio | Monitorear query time. Plan B: materialized view con REFRESH CONCURRENTLY. Escalar a D4 rev. |
| RD3 | La heurística de contraparte "sd_id mayor = contraparte" es un convenio operativo frágil; un cambio en el ERP (ej. nuevo sd_id de contraparte con valor menor) la rompe silenciosamente. | medio | Test de regresión sobre fixture JUKEBOX **Y** alerta diaria si aparece `sd_id` con `hacc_group` inverso no previsto. El clasificador expone `es_contraparte(sd, sd_base)` para validación puntual. Combinado con R1: cualquier `sd_id` nuevo pasa primero por revisión humana antes de entrar al catálogo vía migration. |
| RD4 | Reusar `alertas` para divergencias CC puede "spammear" el banner si los usuarios ignoran las divergencias día tras día. | bajo | La alerta diaria sobrescribe a la anterior (misma key día). Auto-expira a las 24h con `fecha_hasta`. |
| RD5 | `compras_eventos` polimórfica sin FK física al pedido/OP puede quedar huérfana si se borra la entidad. | bajo | Solo se permite `cancelar`, jamás `DELETE` de entidades. Opcional: trigger de validación. |
| RD6 | El cron de reconciliación a las 03:00 AM asume que el sync ERP ya terminó de procesar el día. Si el sync se atrasa, reconciliación compara contra snapshot parcial. | medio | Agregar pre-check: si `MAX(ct_date) < CURRENT_DATE - 1` alertar y continuar (no abortar). |
| RD7 | `OP.moneda ≠ caja.moneda` bloqueado en v1 puede frustrar a usuarios si nunca crearon caja USD. | bajo | Seed inicial: asegurarse de crear al menos 1 caja USD por empresa al deploy. Mensaje de error sugiere el camino. |
| RD8 | Numeración `SELECT FOR UPDATE` serializa a todos los aprobadores simultáneos de una misma empresa/año. | bajo | Volumen real esperado: <100 pedidos/día. Mantener transacción corta (lock solo durante INSERT de la entidad). Si escala, mover a `UPDATE ... RETURNING` atómico. |
| RD9 | Banner anti-doble-contab por sessionStorage no protege contra usuarios que abren múltiples tabs (en cada tab vuelve a aparecer y dismiss). | bajo | Aceptable: mejor un banner repetido que silenciado. |
| RD10 | Hook de matching falla silencioso si el log no llega a observability (stderr del cron). | bajo | Integrar con el sistema de logs existente (verificar en apply) + notificacion en caso de `errores > 0`. |

---

## 12. Referencias cruzadas

- Proposal: `openspec/changes/modulo-compras/proposal.md`
- Specs: `openspec/changes/modulo-compras/specs/*.md` (9 archivos)
- State: `openspec/changes/modulo-compras/state.yaml` (actualizado a `phase=design`)
- Engram obs relevantes: #102 (decisiones originales), #103 (explore), #104 (erp mapping), #106 (catálogo), #116 (cierre pre-design)
- Código real consultado:
  - `backend/app/services/caja_service.py:129,428` — signature `registrar_movimiento` y `crear_documento`
  - `backend/app/models/commercial_transaction.py:21` — `ct_transaction BigInteger`
  - `backend/app/models/alerta.py` — tabla `alertas` reusable
  - `backend/app/models/notificacion.py` — tabla `notificaciones` reusable
  - `backend/app/scripts/sync_commercial_transactions_guid.py` — hook target

---

## 13. Next

`sdd-tasks` — traducir estas decisiones a checklist accionable ordenado por dependencia:

1. Migrations (schemas nuevas + `etiquetas_envio` modified + seeds) — incluye **seed estático de `tb_sale_document`** (~43 registros en Alembic migration, NO hay sync)
2. Modelos SQLAlchemy + schemas Pydantic
3. Servicios base (`numeracion_service`, `sale_document_classifier`, `cc_proveedor_service`)
4. Servicios de flujo (`imputaciones_service`, `ordenes_pago_service`, `erp_matching_service`)
5. Vista SQL `v_facturas_compra_vigentes`
6. Hook en `sync_commercial_transactions_guid.py`
7. Cron `reconciliar_cc_proveedor.py`
8. Routers/endpoints
9. Frontend `AdministracionCompras.jsx` + componentes (panel Sale Documents read-only)
10. Tests (unitarios clasificador + integración matching + concurrencia numeración + state machine + combos imputaciones)
12. Seeds permisos nuevos + seed caja_tipo_documentos 'orden_pago' y 'orden_pago_anulada' + seed `configuracion.compras.cc_reconciliacion_tolerancia`

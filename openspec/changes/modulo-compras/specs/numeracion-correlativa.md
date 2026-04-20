# Spec Delta — Numeración Correlativa

**Change:** modulo-compras
**Capability:** numeracion-correlativa
**Status:** draft

## Purpose

Asignar números correlativos únicos y secuenciales a entidades de negocio (pedidos, órdenes de pago) agrupados por `(tipo, empresa, año)`, con formato legible `{tipo}-{empresa:02d}-{año:04d}-{correlativo:05d}` y protección contra duplicados bajo concurrencia mediante `SELECT FOR UPDATE`.

## ADDED Requirements

### Requirement: REQ-NUM-001 — Modelo `numeracion_contadores`

**Priority:** must
**Type:** functional

El sistema MUST implementar el modelo `numeracion_contadores` con los siguientes campos:

- `tipo` (VARCHAR NOT NULL — `pedido` | `orden_pago` en v1, extensible a `factura_proveedor`, `remito_proveedor`, etc. en v2)
- `empresa_id` (INT NOT NULL)
- `año` (INT NOT NULL)
- `ultimo_numero` (INT NOT NULL DEFAULT 0)
- `updated_at` (TIMESTAMP)

Clave primaria compuesta: `(tipo, empresa_id, año)`.

Índice implícito por la PK. NO SHALL existir otros registros: la tabla contiene **exactamente un registro por combinación (tipo, empresa, año)** donde `ultimo_numero` se incrementa en 1 cada vez que se asigna un correlativo.

#### Scenario: Inserción idempotente on first use

- GIVEN no existe fila para `(pedido, 1, 2026)` al momento del primer pedido del año
- WHEN el servicio de numeración solicita el siguiente correlativo
- THEN SHALL insertar `(pedido, 1, 2026, ultimo_numero=1)` y retornar `1`
- AND la siguiente solicitud SHALL actualizar a `ultimo_numero=2` y retornar `2`

### Requirement: REQ-NUM-002 — Formato del número generado

**Priority:** must
**Type:** functional

El sistema MUST generar el número concatenando con el formato **exacto**:

```
{tipo_prefix}-{empresa:02d}-{año:04d}-{correlativo:05d}
```

Donde:
- `tipo_prefix`: `P` para `pedido`, `OP` para `orden_pago`. Extensible en v2 (`NC`, `RM`, etc.).
- `empresa:02d`: empresa_id con padding a 2 dígitos (ej. `01`, `02`).
- `año:04d`: año completo de 4 dígitos (ej. `2026`).
- `correlativo:05d`: contador con padding a 5 dígitos (ej. `00001`, `00042`, `12345`).

Ejemplos válidos:
- `P-01-2026-00001`
- `OP-01-2026-00042`
- `P-02-2027-12345`

El número SHALL persistirse como **VARCHAR** en la columna `numero` de la entidad correspondiente, NO como columnas separadas.

#### Scenario: Primer pedido del año en empresa 1

- GIVEN estado inicial sin contadores para 2026
- WHEN se crea el primer pedido de empresa 1 en 2026
- THEN `pedidos_compra.numero` SHALL ser `'P-01-2026-00001'`

#### Scenario: Correlativo superando 9999

- GIVEN `numeracion_contadores.ultimo_numero=9999` para `(pedido, 1, 2026)`
- WHEN se crea el siguiente pedido
- THEN `ultimo_numero` pasa a `10000`
- AND el número generado SHALL ser `'P-01-2026-10000'` (5 dígitos aún suficientes hasta 99999)

### Requirement: REQ-NUM-003 — Lock pesimista con `SELECT FOR UPDATE`

**Priority:** must
**Type:** functional

El servicio de numeración (`backend/app/services/numeracion_service.py`) MUST ejecutar el siguiente flujo dentro de **la misma transacción** que el INSERT de la entidad numerada:

```python
def siguiente_numero(session, tipo: str, empresa_id: int, año: int) -> tuple[str, int]:
    # 1. SELECT FOR UPDATE sobre numeracion_contadores
    row = session.execute(
        """
        SELECT ultimo_numero FROM numeracion_contadores
        WHERE tipo = :tipo AND empresa_id = :eid AND año = :año
        FOR UPDATE
        """,
        {"tipo": tipo, "eid": empresa_id, "año": año}
    ).first()

    # 2. Si no existe, insertar con ultimo_numero=1
    if row is None:
        session.execute("INSERT INTO numeracion_contadores (...) VALUES (:tipo, :eid, :año, 1)")
        nuevo = 1
    else:
        nuevo = row.ultimo_numero + 1
        session.execute("UPDATE numeracion_contadores SET ultimo_numero = :n WHERE ... ", {"n": nuevo, ...})

    # 3. Construir string
    formato = f"{PREFIX[tipo]}-{empresa_id:02d}-{año:04d}-{nuevo:05d}"
    return formato, nuevo
```

La función SHALL ser invocada DESDE la transacción del caller (no abre una nueva). El caller mantiene el lock durante el INSERT de la entidad; al commit, se libera. Esto garantiza que dos transacciones concurrentes NO pueden leer el mismo `ultimo_numero`.

#### Scenario: Invocación correcta

- GIVEN el caller `pedidos_service.crear_pedido` dentro de una transacción
- WHEN invoca `numeracion_service.siguiente_numero(session, 'pedido', 1, 2026)`
- THEN el servicio toma lock sobre la fila del contador
- AND el lock SHALL liberarse cuando el caller haga commit (o rollback)

### Requirement: REQ-NUM-004 — Concurrencia: 2 requests simultáneos no duplican

**Priority:** must
**Type:** non-functional

El sistema MUST garantizar que bajo carga concurrente (N requests simultáneos creando pedidos en la misma `(tipo, empresa, año)`) NO se generen números duplicados. El mecanismo de `SELECT FOR UPDATE` serializa las transacciones.

Este requirement MUST tener un test de integración que simule concurrencia:

```python
# backend/tests/integration/test_numeracion_concurrencia.py
def test_dos_requests_simultaneos_no_generan_duplicados(db_session_factory):
    results = []
    def crear_pedido(i):
        with db_session_factory() as s:
            numero, _ = numeracion_service.siguiente_numero(s, 'pedido', 1, 2026)
            results.append(numero)
            s.commit()

    threads = [threading.Thread(target=crear_pedido, args=(i,)) for i in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert len(results) == 10
    assert len(set(results)) == 10  # todos únicos
    assert sorted(results) == [f"P-01-2026-{i:05d}" for i in range(1, 11)]
```

#### Scenario: 10 requests simultáneos producen 10 números únicos y secuenciales

- GIVEN 10 hilos creando pedidos concurrentemente en `(pedido, 1, 2026)` partiendo de `ultimo_numero=0`
- WHEN todos commitean
- THEN los 10 números resultantes MUST ser únicos
- AND el conjunto SHALL ser exactamente `{P-01-2026-00001, ..., P-01-2026-00010}` (sin gaps)
- AND `numeracion_contadores.ultimo_numero` MUST terminar en `10`

### Requirement: REQ-NUM-005 — Tipos soportados v1

**Priority:** must
**Type:** functional

En v1, los tipos válidos MUST ser exclusivamente:
- `pedido` (prefix `P`)
- `orden_pago` (prefix `OP`)

Cualquier llamada a `numeracion_service.siguiente_numero()` con un `tipo` fuera de esta lista SHALL responder `ValueError` (o HTTP 500 si llega desde un endpoint mal configurado). La constante `PREFIX` SHALL vivir en `numeracion_service.py`:

```python
PREFIX = {
    'pedido': 'P',
    'orden_pago': 'OP',
}
```

Extensión v2 (facturas locales, NCs locales, remitos) agrega entries sin cambiar schema.

#### Scenario: Tipo desconocido rechazado

- GIVEN una llamada con `tipo='factura_proveedor_local'` en v1
- WHEN se invoca el servicio
- THEN MUST raise `ValueError("Tipo de numeración no soportado en v1: factura_proveedor_local")`

### Requirement: REQ-NUM-006 — Año se toma de la fecha del servidor

**Priority:** must
**Type:** functional

El parámetro `año` que recibe el servicio MUST ser determinado por el servidor en el momento del INSERT (no por el cliente). Típicamente `año = date.today().year`, con la zona horaria del servidor (Argentina, UTC-3).

Esto evita que un cliente desconectado con reloj incorrecto asigne números a años errados, y simplifica el rollover: a las 00:00:00 del 1 de enero, el contador `(pedido, 1, 2026)` se archiva naturalmente y se crea `(pedido, 1, 2027)`.

#### Scenario: Rollover de año

- GIVEN el último pedido de 2026 fue `P-01-2026-01234`
- WHEN se crea el primer pedido el 1 de enero de 2027 a las 00:05 AM (hora Argentina)
- THEN el servicio detecta `año=2027`
- AND crea el contador `(pedido, 1, 2027, ultimo_numero=1)` (nuevo row)
- AND el número generado SHALL ser `P-01-2027-00001`

## OPEN QUESTIONS

- OPEN_QUESTION-NUM-01: ¿El año se toma de la zona horaria del servidor (Argentina UTC-3) o UTC? Importa para el rollover a fin de año. Recomendación: Argentina, consistente con el resto del sistema que trabaja en hora local.
- OPEN_QUESTION-NUM-02: ¿Se permite "reservar" un bloque de correlativos (ej. para import masivo) saltándose el contador? v1 = NO; todo pasa por el servicio. Documentar la restricción.
- OPEN_QUESTION-NUM-03: ¿Qué pasa si una transacción hace rollback después de asignar el número? El `ultimo_numero` queda incrementado pero no hay entidad. Resultado esperado: **gap legítimo** en la secuencia (ej. falta `P-01-2026-00013`). Esto es aceptable y estándar en sistemas contables; documentarlo en la guía de usuario.

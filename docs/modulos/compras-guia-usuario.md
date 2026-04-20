# Módulo de Compras — Guía de usuario final

> **Audiencia:** Product Managers (compradores), aprobadores, tesorería,
> operadores de logística.
> **Nivel:** operativo. No requiere conocimiento técnico de la base de datos
> ni del ERP.

---

## 1. ¿Qué es el módulo de compras?

Es el sistema interno para gestionar **pedidos a proveedores** desde el
armado del pedido hasta el pago, integrado con:

- **Caja** (efectivo/divisa) — cada pago ejecutado egresa de una caja.
- **Cuenta corriente de proveedores** (libro mayor propio) — cada pedido
  aprobado deja un DEBE; cada pago deja un HABER.
- **ERP** — la app no reemplaza al ERP, sino que **refleja** lo que pasa
  allá y permite trabajar ordenadamente mientras esa data se sincroniza.
- **TabEnviosFlex** — si el pedido incluye retiro del proveedor por nuestra
  logística, se genera una etiqueta automáticamente.

Acceso: `https://pricing.miempresa.com/administracion/compras`.

---

## 2. Roles y permisos necesarios

| Permiso                                        | ¿Quién debe tenerlo?                             |
| ---------------------------------------------- | ------------------------------------------------ |
| `administracion.ver_ordenes_compra`            | Cualquier usuario que precise ver pedidos/OPs.   |
| `administracion.gestionar_ordenes_compra`      | PMs / compradores (crear y editar pedidos/OPs).  |
| `administracion.aprobar_ordenes_compra`        | **CRÍTICO** — sólo aprobadores (gerentes).       |
| `administracion.ejecutar_pagos`                | **CRÍTICO** — sólo tesorería.                    |
| `administracion.ver_cuentas_corrientes`        | Contadores, gerentes, admin.                     |
| `administracion.gestionar_cuentas_corrientes`  | Admin (para forzar reconciliación, ajustes).     |

**Regla de oro (control interno):** no asignar `aprobar_ordenes_compra` +
`ejecutar_pagos` al mismo usuario. El sistema NO lo bloquea técnicamente,
pero sí audita quién hizo cada paso.

Si al entrar al módulo no ves algún tab, pedile al admin que revise los
permisos. Los tabs se ocultan dinámicamente según los permisos del usuario.

---

## 3. Flujo de trabajo estándar

```
┌──────────┐       ┌────────────────┐       ┌──────────┐       ┌─────────┐
│ BORRADOR │──────▶│ PEND_APROBACION│──────▶│ APROBADO │──────▶│ PAGADO  │
└──────────┘       └────────────────┘       └──────────┘       └─────────┘
     │                    │                       │
     │ cancelar           │ rechazar              │ cancelar_aprobado (reverso CC)
     ▼                    ▼                       ▼
┌──────────┐       ┌──────────┐          ┌──────────┐
│CANCELADO │       │ BORRADOR │          │CANCELADO │
└──────────┘       └──────────┘          └──────────┘
```

### 3.1 El PM crea un pedido (borrador)

1. Tab **Pedidos de compra** → botón **Nuevo pedido**.
2. Completar:
   - **Empresa** (la que factura — define numeración y empresa_id de caja).
   - **Proveedor** (autocomplete contra `/administracion/proveedores`).
   - **Moneda** (ARS o USD).
   - **Monto estimado**, **descripción breve**, **notas** opcionales.
   - **¿Requiere envío por nuestra logística?** Si sí, marcar el flag
     `requiere_envio=true` y seleccionar la dirección de retiro del proveedor.
3. Guardar → el pedido queda en estado **BORRADOR** con número
   `P-{empresa}-{año}-{correlativo}` (ej. `P-01-2026-00001`).

> Los pedidos en borrador se pueden editar libremente. No impactan CC
> hasta que se aprueben.

### 3.2 El PM envía el pedido a aprobación

Desde el detalle del pedido → botón **Enviar a aprobación**. El pedido
pasa a **PENDIENTE_APROBACION** y aparece en la bandeja de los aprobadores.

### 3.3 El aprobador aprueba (o rechaza)

Solo usuarios con `aprobar_ordenes_compra` ven estos botones.

- **Aprobar:** el pedido pasa a **APROBADO** + se inserta un DEBE en la CC
  del proveedor (moneda y monto del pedido).
- **Rechazar:** el aprobador debe escribir un motivo. El pedido vuelve a
  **BORRADOR** (el PM puede editar y re-enviar) o directamente queda
  **CANCELADO** según la elección en el modal.

### 3.4 Momento del pago — crear OP

Cuando llega el momento de pagarle al proveedor, el PM (o tesorería) crea
una **Orden de Pago (OP)**:

1. Tab **Órdenes de Pago** → **Nueva OP**.
2. Completar:
   - Empresa y proveedor.
   - Moneda (debe coincidir con la de los pedidos a imputar).
   - Monto total.
   - **Modo de imputación:**
     - **Específica:** cargar manualmente una línea por cada pedido/factura
       a pagar, con su monto.
     - **A cuenta:** dejar sin items; luego se puede usar "Distribuir
       automáticamente" FIFO para aplicar contra las facturas pendientes
       más antiguas.
     - **Mixta:** combinar items específicos + remanente como saldo.
3. La OP queda en estado **CREADA** (no pagada todavía).

> **⚠ Anti-doble-contabilización:** un banner rojo arriba del form recuerda
> que **NO se debe cargar la OP en la app si ya se registró directamente
> en el ERP**. Se contabilizaría dos veces. El banner se oculta por el día
> al cerrarlo, y vuelve a aparecer al día siguiente.

### 3.5 Tesorería ejecuta el pago

Solo usuarios con `ejecutar_pagos` ven el botón **Pagar**.

1. Abrir la OP → botón **Pagar**.
2. Elegir la caja origen (solo cajas con **la misma moneda y empresa** de
   la OP se ven en el dropdown — evita el error `OP_CAJA_MONEDA_MISMATCH`).
3. Confirmar.

En un solo tick transaccional, el sistema crea:

- 1 `CajaMovimiento` tipo **egreso** por el monto total.
- 1 `CajaDocumento` con `entidad_tipo='orden_pago'` + `entidad_id={op_id}`.
- 1 o N movimientos HABER en la CC del proveedor (uno por pedido imputado
  o uno a cuenta).
- 1 o N imputaciones en la tabla `imputaciones` (append-only).
- La OP cambia a **PAGADA**.
- Los pedidos imputados cambian a **PAGADO** si la imputación cubrió el
  monto total, o quedan en **APROBADO** con saldo pendiente si fue parcial.

---

## 4. Casos especiales

### 4.1 Pago a cuenta (sin imputar)

Cuando te pagan un anticipo o hay un saldo suelto:

1. Crear OP sin items.
2. Pagar normalmente → queda como HABER a cuenta en la CC del proveedor.
3. En cualquier momento posterior, ir a la OP → **Distribuir
   automáticamente** → FIFO aplica contra facturas pendientes más antiguas
   hasta agotar el saldo.

### 4.2 Re-imputación de pagos

Si una imputación quedó mal aplicada (ej. se pagó el pedido equivocado):

1. Tab OPs → sub-tab **Imputaciones** → filtrar por OP/proveedor.
2. Fila de la imputación errada → botón **Desimputar** (motivo obligatorio).
3. Aparece una nueva fila reversal (imputación compensatoria). El saldo
   vuelve a cuenta.
4. Crear una nueva imputación manual contra el destino correcto.

> **Append-only:** las imputaciones NUNCA se editan ni borran. Se agregan
> reversals y nuevas imputaciones. Esto preserva el rastro de auditoría.

### 4.3 Anulación de OP

Si una OP pagada tiene que revertirse (ej. error grosero, devolución total):

1. Abrir la OP pagada → botón **Anular** (requiere permiso
   `ejecutar_pagos`).
2. Motivo obligatorio.
3. El sistema genera:
   - 1 `CajaMovimiento` tipo **ingreso** (reintegra el egreso).
   - 1 `CajaDocumento` con `entidad_tipo='orden_pago_anulada'`.
   - Reversals en CC del proveedor (DEBE por el HABER previo).
   - Desimputación automática de todas las imputaciones de la OP.
   - La OP pasa a **ANULADA**; los pedidos afectados vuelven a **APROBADO**.

### 4.4 Alerta de posible duplicado con ERP

Al crear una OP, el backend busca automáticamente en
`tb_commercial_transactions` si hay una factura (sd_id=106 = Orden de Pago)
reciente del mismo proveedor con el mismo `ct_docnumber` en los últimos 7
días. Si encuentra algo:

- Respuesta HTTP 409 con código `POSIBLE_DUPLICADO_OP_ERP`.
- El frontend abre un modal: "Detectamos N posibles duplicados en el ERP:
  [listado]. ¿Confirmás que es una OP distinta?"
- Si cancelás: el form queda como estaba, podés corregir.
- Si confirmás: se reenvía con `confirmar_duplicado=true` y se registra el
  evento `op_creada_con_duplicado_confirmado` para auditoría.

---

## 5. Reconciliación CC

### 5.1 ¿Qué es?

Un proceso automático que corre **diario a las 03:00 AM** (Argentina) y
compara, por cada (proveedor, moneda):

- **Libro mayor propio:** saldo calculado desde `cc_proveedor_movimientos`
  (lo que generan los flujos propios de aprobaciones + pagos).
- **Snapshot ERP:** saldo de la tabla legacy `cuentas_corrientes_proveedores`
  sincronizada desde el ERP.

Si la diferencia supera la tolerancia configurada por moneda
(default: 100 ARS / 1 USD), se genera:

- 1 fila `divergencia` en `cc_reconciliacion_log`.
- 1 alerta banner.
- N notificaciones a usuarios con `ver_cuentas_corrientes`.

### 5.2 ¿Cómo interpretarla?

Tab **Reconciliación** muestra:

- Las corridas recientes (fecha, total proveedores evaluados, divergencias
  encontradas).
- Saldo en el libro propio vs. saldo en ERP, con el delta.
- Métricas de deprecación del snapshot (ver sección 5.4).

### 5.3 ¿Qué hacer con divergencias?

1. Abrir la fila de la divergencia → ver detalle.
2. Casos típicos:
   - **Nuestro libro atrasado:** falta aprobar un pedido o registrar una
     OP. Corregir en la app.
   - **ERP atrasado:** el ERP todavía no tiene la factura que nosotros
     sí. Esperar al próximo sync (cada 10 min) o contactar al área que
     carga el ERP.
   - **Divergencia real:** error de carga en un lado. Revisar movimientos
     recientes y ajustar manualmente (admin con `gestionar_cuentas_corrientes`).
3. Forzar re-reconciliación (botón en el tab) y validar que la divergencia
   desaparece.

### 5.4 Deprecación del snapshot (post-v1)

El snapshot `cuentas_corrientes_proveedores` es un vestigio del ERP que
queremos eliminar cuando se cumplan los 3 criterios:

- [ ] 30 días consecutivos sin divergencias en reconciliación diaria.
- [ ] Cobertura ≥ 80% de proveedores activos (≥ 1 mov. en últimos 90 días).
- [ ] Aprobación explícita de usuarios clave tras revisar ambas fuentes.

El tab **Reconciliación** muestra los 3 flags. Cuando los 3 estén en ✅,
abrir un change nuevo de deprecación.

---

## 6. Logística de retiro del proveedor

### 6.1 ¿Cuándo usarlo?

Cuando tu logística va a pasar a retirar la mercadería por la dirección
del proveedor (en vez de esperar a que él envíe por transporte propio).

### 6.2 Cómo se integra con TabEnviosFlex

1. Al crear el pedido, marcar `requiere_envio=true` y seleccionar una
   **dirección del proveedor** (se cargan desde el master de proveedores).
2. Tras la aprobación, desde el detalle del pedido → botón **Generar
   etiqueta de retiro**.
3. El sistema crea una fila en `etiquetas_envio` con:
   - `tipo_envio='retiro_proveedor'`
   - `proveedor_id`, `proveedor_direccion_id`, `pedido_compra_id`
   - `cliente_id=NULL` (es un retiro, no una entrega).
4. La etiqueta aparece en `/envios-flex` con un **badge azul "Retiro
   proveedor"** para diferenciarla de las etiquetas de venta.
5. El operador de logística la procesa igual que una etiqueta normal:
   asigna logística, imprime, pistonea al retirar.

### 6.3 ¿Cuándo NO usarlo?

- El proveedor envía la mercadería por su cuenta → no marcar el flag.
- La compra es un servicio (no hay mercadería física) → no marcar el flag.

---

## 7. Preguntas frecuentes

### ¿Qué pasa si cancelo un pedido aprobado?

- El pedido pasa a **CANCELADO**.
- Se inserta un movimiento de reverso (HABER tipo ajuste) en CC para
  cancelar el DEBE del aprobado original.
- Motivo de cancelación es **obligatorio** y queda auditado en `compras_eventos`.

### ¿Puedo pagar una OP USD con una caja ARS?

No. El sistema bloquea con HTTP 422 `OP_CAJA_MONEDA_MISMATCH` — la moneda
de la OP y la de la caja tienen que coincidir. Si necesitás convertir,
hacelo manualmente: un ingreso/egreso en cada caja con detalle explicativo.

### ¿Por qué hay gaps en la numeración de pedidos?

La numeración es correlativa pero acepta gaps legítimos cuando se rollbackea
una transacción (ej. crear pedido falla mid-way). Los gaps son **aceptables
en v1** y no indican un problema. La correlatividad estricta queda para v2.

### ¿Puedo editar un pedido aprobado?

No. Una vez aprobado, el pedido es inmutable (salvo cancelación). Si hay
un error, cancelar y crear uno nuevo.

### ¿Dónde veo el historial de cambios de un pedido?

En el modal de detalle del pedido → sección **Timeline**. Se listan todos
los eventos (creación, edición, envío a aprobación, aprobación, pago, etc.)
con usuario, fecha y metadata.

---

## 8. Glosario

| Término                     | Significado                                              |
| --------------------------- | -------------------------------------------------------- |
| **Pedido de compra**        | Intención formal de comprar a un proveedor.              |
| **OP (Orden de Pago)**      | Documento que materializa el pago al proveedor.          |
| **Imputación**              | Vínculo entre un origen (OP) y un destino (pedido / factura / saldo). |
| **CC proveedor**            | Cuenta corriente: libro mayor de DEBE/HABER por proveedor. |
| **Snapshot ERP**            | Copia sincronizada de la CC del ERP (legacy, deprecable). |
| **Libro mayor propio**      | CC calculada desde los movimientos generados por esta app. |
| **Reconciliación**          | Comparación diaria libro mayor propio vs. snapshot ERP.  |
| **Distribución FIFO**       | Aplicar un saldo a cuenta a las facturas más antiguas.   |
| **Retiro proveedor**        | Modalidad de envío donde nuestra logística va a buscar. |

---

## 9. Contacto / soporte

- **Dueño técnico del módulo:** equipo Backend.
- **Ante errores del módulo:** abrir ticket con categoría "Admin / Compras".
- **Ante divergencias de CC persistentes:** escalar al área de Administración
  contable antes de ajustar manualmente.

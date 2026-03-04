# CONTEXTO: Claims de MercadoLibre para el sistema RMA

Sistema de consulta y cache local de reclamos (claims) de MercadoLibre.
Datos se obtienen vía webhook proxy y se cachean en nuestra DB para consulta instantánea.

---

## ARQUITECTURA DE DATOS

### Fuentes de datos (en orden de prioridad)

| # | Fuente | DB | Velocidad | Descripción |
|---|--------|-----|-----------|-------------|
| 1 | `rma_claims_ml` | Pricing App (nuestra) | Instantáneo | Cache local con datos de 7+ endpoints ML combinados |
| 2 | `ml_previews` (enriched) | mlwebhook | Rápido | Webhook DB con `extra_data` enriquecido por el servicio webhook |
| 3 | `ml_previews` (raw) + HTTP | mlwebhook + API | ~3-5s | Webhook DB sin data completa → se enriquece vía HTTP y se guarda en cache |
| 4 | ML API search + HTTP | API | ~5-8s | Búsqueda por `order_id` para claims que nunca llegaron como webhook |

### Cache local (nuestra DB — pricing-app)

**`rma_claims_ml`** — Cache de claims enriquecidos:

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `id` | serial PK | ID interno |
| `claim_id` | bigint UNIQUE | ID del claim en ML |
| `resource_id` | bigint | `order_id` de ML (para buscar por pedido) |
| `claim_type` | varchar(50) | `mediations`, `return`, `fulfillment`, etc. |
| `claim_stage` | varchar(50) | `claim`, `dispute`, `recontact`, `stale` |
| `status` | varchar(50) | `opened`, `closed` |
| `reason_id` | varchar(50) | Código ML: `PDD9549`, `PNR3430`, etc. |
| `reason_category` | varchar(10) | Prefijo: `PDD`, `PNR`, `CS` |
| `reason_detail` | text | Texto legible del motivo |
| `reason_name` | varchar(255) | Nombre interno de la reason |
| `triage_tags` | jsonb | `["defective", "repentant"]` |
| `expected_resolutions` | jsonb | `["return_product", "refund"]` |
| `detail_title` | text | Título legible (de `/claims/{id}/detail`) |
| `detail_description` | text | Descripción larga del estado actual |
| `detail_problem` | text | Problema reportado por el comprador |
| `fulfilled` | boolean | `true` = producto entregado |
| `quantity_type` | varchar(20) | `total`, `partial` |
| `claimed_quantity` | integer | Cantidad reclamada |
| `seller_actions` | jsonb | `["refund", "allow_return", ...]` |
| `mandatory_actions` | jsonb | Acciones con `mandatory=true` |
| `nearest_due_date` | varchar(50) | ISO date de la acción más urgente |
| `action_responsible` | varchar(20) | `seller`, `buyer`, `mediator` |
| `resolution_reason` | varchar(100) | `payment_refunded`, `item_returned`, etc. |
| `resolution_closed_by` | varchar(20) | `seller`, `buyer`, `mediator` |
| `resolution_coverage` | boolean | Si ML aplicó cobertura |
| `related_entities` | jsonb | `["return", "change", "reviews"]` |
| `expected_resolutions_detail` | jsonb | Array de resoluciones esperadas con roles y status |
| `return_data` | jsonb | Objeto completo de devolución (de `/v2/claims/{id}/returns`) |
| `change_data` | jsonb | Objeto completo de cambio (de `/v1/claims/{id}/changes`) |
| `messages_total` | integer | Total de mensajes en el reclamo |
| `affects_reputation` | boolean | Si afecta la reputación del vendedor |
| `has_incentive` | boolean | Incentivo de 48hs para resolver |
| `ml_date_created` | varchar(50) | Fecha de creación del claim en ML |
| `ml_last_updated` | varchar(50) | Última actualización en ML |
| `raw_claim` | jsonb | JSON completo de `/claims/{id}` (backup) |
| `raw_detail` | jsonb | JSON completo de `/claims/{id}/detail` (backup) |
| `raw_reason` | jsonb | JSON completo de `/claims/reasons/{reason_id}` (backup) |
| `created_at` | timestamptz | Cuándo se creó el registro local |
| `updated_at` | timestamptz | Cuándo se actualizó el registro local |

**Índices:** `claim_id` (unique), `resource_id`, `status`, `reason_category`

**`rma_claims_ml_messages`** — Mensajes de la conversación del reclamo:

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `id` | serial PK | ID interno |
| `claim_id` | bigint | ID del claim en ML (no FK, es el ID de ML) |
| `sender_role` | varchar(30) | `complainant`, `respondent`, `mediator` |
| `receiver_role` | varchar(30) | `complainant`, `respondent`, `mediator` |
| `message` | text | Contenido del mensaje |
| `status` | varchar(30) | `available`, `moderated`, `rejected` |
| `stage` | varchar(30) | `claim`, `dispute` |
| `attachments` | jsonb | `[{filename, original_filename, type}]` |
| `message_moderation` | jsonb | Datos de moderación si fue moderado |
| `date_read` | varchar(50) | Fecha de lectura |
| `ml_date_created` | varchar(50) | Fecha de creación en ML |
| `created_at` | timestamptz | Cuándo se guardó localmente |

**Índices:** `claim_id`, `sender_role`

### Invalidación de cache (webhook-driven)

La invalidación NO es por tiempo — es por comparación de timestamps con `ml_previews`:

- **Si `ml_previews.last_updated > rma_claims_ml.updated_at`:** Hubo un webhook nuevo → re-fetch via HTTP (7+ endpoints) y actualizar cache.
- **Si `ml_previews.last_updated <= rma_claims_ml.updated_at`:** Cache es actual → usar directo, cero HTTP.
- **Claims cerrados (`status = 'closed'`):** NUNCA se re-fetchean. Son inmutables.
- **Fallback (webhook DB no disponible):** Si la DB de webhooks no está accesible, se usa un fallback por tiempo de 24 horas (`_CACHE_STALE_HOURS_FALLBACK = 24`) solo para claims abiertos.

**Lógica:** Si ML notifica un cambio en el claim → el webhook service actualiza `ml_previews.last_updated` → la próxima consulta de traza detecta que el cache es viejo → re-enriquece.

---

## WEBHOOK DB (ml_previews — solo lectura)

Conexión: `ML_WEBHOOK_DB_URL` en `.env` (variable de entorno del backend)

**`ml_previews`** — Preview enriquecido con datos del webhook:

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `resource` | text PK | Path del recurso (ej: `/post-purchase/v1/claims/5281510459`) |
| `title` | text | Texto legible del motivo (de reasons API) |
| `status` | text | `opened` o `closed` |
| `extra_data` | jsonb | Datos enriquecidos (ver sección "ESTRUCTURA DE extra_data") |
| `last_updated` | timestamptz | Última actualización |

---

## ML API — TODOS LOS ENDPOINTS

### Proxy de acceso

Todas las llamadas a la API de ML se hacen a través del webhook proxy, que maneja la autenticación OAuth:

```
GET https://ml-webhook.gaussonline.com.ar/api/ml/render?resource={path}&format=json
POST https://ml-webhook.gaussonline.com.ar/api/ml/render?resource={path}&format=json
```

El parámetro `resource` es el path completo de la API de ML (sin el dominio).

---

### ENDPOINTS DE LECTURA (implementados)

#### 1. Claim base — `/post-purchase/v1/claims/{claim_id}`

Datos principales del reclamo. **Requerido** — si este falla, se aborta.

```jsonc
{
  "id": 5281510459,
  "type": "mediations",          // mediations | return | fulfillment | ml_case | cancel_sale | change | service
  "stage": "claim",              // claim | dispute | recontact | stale | none
  "status": "opened",            // opened | closed
  "reason_id": "PDD9939",
  "resource_id": 2000007819609432,  // order_id
  "resource_type": "order",
  "fulfilled": true,
  "quantity_type": "total",
  "claimed_quantity": 1,
  "date_created": "2026-03-04T08:28:44.000-04:00",
  "last_updated": "2026-03-04T14:30:00.000-04:00",
  "site_id": "MLA",
  "players": [
    {
      "role": "complainant",        // comprador
      "type": "buyer",
      "user_id": 1325224382,
      "available_actions": []
    },
    {
      "role": "respondent",         // vendedor (nosotros)
      "type": "seller",
      "user_id": 1330467461,
      "available_actions": [
        {
          "action": "refund",
          "mandatory": true,
          "due_date": "2026-03-06T14:30:00.000-03:00"
        },
        {
          "action": "allow_return",
          "mandatory": false
        },
        {
          "action": "send_message_to_complainant",
          "mandatory": false
        },
        {
          "action": "open_dispute",
          "mandatory": false
        }
      ]
    }
  ],
  "related_entities": [
    { "entity_type": "return", "entity_id": 12345 },
    { "entity_type": "change", "entity_id": 67890 }
  ],
  "resolution": {                    // solo cuando status = "closed"
    "reason": "payment_refunded",
    "closed_by": "seller",
    "applied_coverage": false,
    "benefited": ["complainant"],
    "date": "2026-03-05T10:00:00.000-03:00"
  }
}
```

**Acciones disponibles del vendedor (`players[role=respondent].available_actions`):**

| Acción | Descripción |
|--------|-------------|
| `refund` | Reembolso total |
| `allow_return` | Autorizar devolución (genera etiqueta) |
| `allow_return_label` | Generar etiqueta de devolución |
| `allow_partial_refund` | Reembolso parcial |
| `open_dispute` | Escalar a mediación de ML |
| `send_message_to_complainant` | Enviar mensaje al comprador |
| `send_message_to_mediator` | Enviar mensaje al mediador (solo en dispute) |
| `send_potential_shipping` | Promesa de envío |
| `add_shipping_evidence` | Subir evidencia de envío |
| `send_tracking_number` | Enviar número de tracking |
| `send_attachments` | Enviar adjuntos |
| `return_review` | Revisar devolución recibida |

**Motivos de resolución (`resolution.reason`):**

| Valor | Descripción |
|-------|-------------|
| `payment_refunded` | Pago devuelto |
| `item_returned` | Producto devuelto |
| `prefered_to_keep_product` | Comprador prefirió quedarse el producto |
| `partial_refunded` | Reembolso parcial |
| `opened_claim_by_mistake` | Reclamo por error |
| `worked_out_with_seller` | Arreglado con el vendedor |
| `seller_sent_product` | Vendedor envió el producto |
| `seller_explained_functions` | Vendedor explicó funcionamiento |
| `respondent_timeout` | Vendedor no respondió a tiempo |
| `coverage_decision` | Decisión de cobertura de ML |
| `item_changed` | Producto cambiado |
| `change_expired` | Cambio expirado |
| `low_cost` | Bajo costo (envío > producto) |
| `already_shipped` | Ya fue enviado |
| `not_delivered` | No entregado |
| `return_expired` | Devolución vencida |
| `return_canceled` | Devolución cancelada |

---

#### 2. Detalle legible — `/post-purchase/v1/claims/{claim_id}/detail`

Texto human-readable del estado actual del claim. Cambia según el estado y la etapa.

```jsonc
{
  "title": "El comprador quiere devolver el producto",
  "description": "Tenés hasta el viernes 6 de marzo para responder. Si no respondés, se reembolsará automáticamente.",
  "problem": "Nos dijeron que el producto llegó en buenas condiciones pero no lo quieren",
  "action_responsible": "seller",    // seller | buyer | mediator
  "due_date": "2026-03-06T22:33:00.000-04:00"
}
```

---

#### 3. Motivo (reason) — `/post-purchase/v1/claims/reasons/{reason_id}`

Detalles del motivo del reclamo, incluyendo tags de clasificación y resoluciones esperadas.

```jsonc
{
  "id": "PDD9939",
  "name": "repentant_buyer",
  "detail": "Llegó lo que compré en buenas condiciones pero no lo quiero",
  "settings": {
    "rules_engine_triage": ["repentant"],               // Tags: defective, repentant, not_working, different, incomplete
    "expected_resolutions": ["change_product", "return_product"]  // Qué espera el comprador
  }
}
```

**Triage tags posibles:**

| Tag | Significado | RMA sugerido |
|-----|-------------|--------------|
| `defective` | Defectuoso / problema de fábrica | Garantía |
| `not_working` | No funciona | No funciona |
| `different` | Producto diferente al publicado | Producto equivocado |
| `incomplete` | Incompleto / faltan piezas | Incompleto |
| `repentant` | Arrepentimiento (producto OK) | Sin defecto |

---

#### 4. Resoluciones esperadas — `/post-purchase/v1/claims/{claim_id}/expected-resolutions`

Propuestas de resolución de cada parte (comprador, vendedor, mediador).

```jsonc
[
  {
    "player_role": "complainant",              // comprador
    "expected_resolution": "return_product",   // return_product | change_product | refund | partial_refund
    "status": "pending",                       // pending | accepted | rejected
    "details": [
      { "key": "percentage", "value": "100" },
      { "key": "seller_amount", "value": "15000.00" }
    ],
    "date_created": "2026-03-04T08:28:44.000-04:00",
    "last_updated": "2026-03-04T14:30:00.000-04:00"
  },
  {
    "player_role": "respondent",               // vendedor
    "expected_resolution": "refund",
    "status": "accepted",
    "details": [],
    "date_created": "2026-03-04T09:00:00.000-04:00",
    "last_updated": "2026-03-04T09:00:00.000-04:00"
  }
]
```

---

#### 5. Devolución — `/post-purchase/v2/claims/{claim_id}/returns`

Solo se llama si `related_entities` contiene `"return"`.

```jsonc
{
  "id": 12345678,
  "status": "shipped",          // pending | label_generated | ready_to_ship | shipped | delivered | expired | cancelled | not_returned | waiting_for_return
  "subtype": "return_total",    // low_cost | return_partial | return_total
  "status_money": "retained",   // retained | refunded | available | pending
  "refund_at": "delivered",      // shipped | delivered | n/a — en qué momento se reembolsa
  "date_created": "2026-03-04T10:00:00.000-04:00",
  "date_closed": null,
  "shipments": [
    {
      "id": 44557766,
      "status": "shipped",                // pending | ready_to_ship | shipped | delivered | cancelled | not_delivered
      "tracking_number": "AR123456789",
      "type": "return",                   // return | return_from_triage
      "destination": {
        "name": "seller_address"          // seller_address | warehouse
      }
    }
  ]
}
```

**Estados de devolución (`status`):**

| Estado | Descripción |
|--------|-------------|
| `pending` | Devolución pendiente, etiqueta no generada |
| `label_generated` | Etiqueta de envío generada, esperando despacho |
| `ready_to_ship` | Listo para enviar |
| `shipped` | Paquete en tránsito |
| `delivered` | Paquete entregado al vendedor |
| `expired` | Devolución vencida (comprador no envió a tiempo) |
| `cancelled` | Devolución cancelada |
| `not_returned` | Producto no devuelto |
| `waiting_for_return` | Esperando que el comprador envíe |

**Estado del dinero (`status_money`):**

| Estado | Descripción |
|--------|-------------|
| `retained` | Dinero retenido por ML |
| `refunded` | Dinero reembolsado al comprador |
| `available` | Dinero disponible para el vendedor |
| `pending` | Estado del dinero pendiente |

---

#### 6. Cambio/reemplazo — `/post-purchase/v1/claims/{claim_id}/changes`

Solo se llama si `related_entities` contiene `"change"`.

```jsonc
{
  "change_type": "change",     // change | replace
  "status": "processing",     // pending | processing | completed | cancelled | expired
  "status_detail": "waiting_for_seller",
  "new_items": [
    {
      "order_id": 2000008123456789,
      "item_id": "MLA1234567890"
    }
  ],
  "date_created": "2026-03-04T10:00:00.000-04:00",
  "last_updated": "2026-03-04T14:30:00.000-04:00"
}
```

---

#### 7. Mensajes — `/post-purchase/v1/claims/{claim_id}/messages`

Conversación entre comprador, vendedor y mediador. En el fetch automático solo se pide `?limit=1` para obtener el count total. Los mensajes completos se guardan en `rma_claims_ml_messages` cuando están disponibles.

```jsonc
{
  "paging": {
    "total": 5,
    "offset": 0,
    "limit": 1
  },
  "data": [
    {
      "sender_role": "complainant",       // complainant | respondent | mediator
      "receiver_role": "respondent",
      "message": "Hola, el producto llegó pero no funciona correctamente...",
      "status": "available",              // available | moderated | rejected
      "stage": "claim",                   // claim | dispute
      "attachments": [
        {
          "filename": "foto1.jpg",
          "original_filename": "IMG_20260304.jpg",
          "type": "image/jpeg"
        }
      ],
      "message_moderation": null,
      "date_created": "2026-03-04T08:30:00.000-04:00",
      "date_read": "2026-03-04T09:00:00.000-04:00"
    }
  ]
}
```

---

#### 8. Afecta reputación — `/post-purchase/v1/claims/{claim_id}/affects-reputation`

```jsonc
{
  "affects_reputation": true,
  "has_incentive": true          // incentivo de 48hs para resolver sin impacto en reputación
}
```

---

#### 9. Búsqueda por order — `/post-purchase/v1/claims/search?order_id={order_id}`

Busca claims asociados a un `order_id`. Útil para encontrar claims que no llegaron como webhook.

```jsonc
{
  "paging": { "total": 1, "offset": 0, "limit": 50 },
  "data": [
    {
      "id": 5281510459,
      "type": "mediations",
      "stage": "claim",
      "status": "opened",
      "reason_id": "PDD9939",
      "resource_id": 2000007819609432,
      "date_created": "2026-03-04T08:28:44.000-04:00"
      // ... misma estructura que /claims/{id} pero resumida
    }
  ]
}
```

---

### ENDPOINTS DE ESCRITURA (para implementar a futuro)

Todos estos se invocan como POST a través del proxy:

```
POST https://ml-webhook.gaussonline.com.ar/api/ml/render?resource={path}&format=json
Content-Type: application/json
Body: { ...datos... }
```

#### A. Enviar mensaje al comprador

```
POST /post-purchase/v1/claims/{claim_id}/messages
```
```json
{
  "receiver_role": "complainant",
  "message": "Hola, lamentamos el inconveniente. Vamos a gestionar la devolución..."
}
```

#### B. Enviar mensaje al mediador (solo en etapa `dispute`)

```
POST /post-purchase/v1/claims/{claim_id}/messages
```
```json
{
  "receiver_role": "mediator",
  "message": "Queremos informar que el producto fue enviado correctamente..."
}
```

#### C. Ofrecer reembolso total

```
POST /post-purchase/v1/claims/{claim_id}/fulfillments
```
```json
{
  "fulfillment_type": "refund"
}
```

#### D. Ofrecer reembolso parcial

```
POST /post-purchase/v1/claims/{claim_id}/fulfillments
```
```json
{
  "fulfillment_type": "partial_refund",
  "amount": 5000.00
}
```

#### E. Autorizar devolución (genera etiqueta de envío)

```
POST /post-purchase/v1/claims/{claim_id}/fulfillments
```
```json
{
  "fulfillment_type": "return"
}
```

#### F. Ofrecer cambio/reemplazo

```
POST /post-purchase/v1/claims/{claim_id}/fulfillments
```
```json
{
  "fulfillment_type": "change",
  "new_item_id": "MLA1234567890"
}
```

#### G. Escalar a mediación (abrir disputa)

```
POST /post-purchase/v1/claims/{claim_id}/fulfillments
```
```json
{
  "fulfillment_type": "open_dispute"
}
```

#### H. Enviar evidencia de envío

```
POST /post-purchase/v1/claims/{claim_id}/evidences
```
```json
{
  "evidence_type": "shipping",
  "tracking_number": "AR123456789",
  "carrier": "correo_argentino"
}
```

#### I. Subir adjunto (foto, documento)

```
POST /post-purchase/v1/claims/{claim_id}/attachments
Content-Type: multipart/form-data
```

**Nota:** Los endpoints de escritura NO están implementados aún. El proxy soporta POST pero no se ha probado el flujo completo. Cuando se implementen, será necesario:
1. Validar que el claim acepta la acción (verificar `available_actions`)
2. Invalidar el cache local después de cada acción
3. Guardar un log de acciones realizadas

---

## ESTRUCTURA DE `extra_data` (webhook DB — ml_previews)

Datos enriquecidos por el servicio webhook. Son 3 llamadas a la API de ML combinadas (claim base + detail + reason):

```jsonc
{
  // === IDENTIFICACIÓN ===
  "claim_id": 5281510459,
  "claim_type": "mediations",
  "claim_stage": "claim",
  "claim_version": 2.0,
  "resource_type": "order",
  "resource_id": 2000007819609432,

  // === MOTIVO ===
  "reason_id": "PDD9939",
  "reason_category": "Producto Diferente o Defectuoso",
  "reason_detail": "Llegó lo que compré en buenas condiciones pero no lo quiero",
  "reason_name": "repentant_buyer",
  "reason_label": "Llegó lo que compré en buenas condiciones pero no lo quiero",

  // === CLASIFICACIÓN ===
  "triage_tags": ["repentant"],
  "expected_resolutions": ["change_product", "return_product"],

  // === ENTREGA ===
  "fulfilled": true,
  "quantity_type": "total",
  "claimed_quantity": 1,

  // === PLAYERS ===
  "complainant_user_id": 1325224382,
  "complainant_type": "buyer",
  "respondent_user_id": 1330467461,
  "respondent_type": "seller",

  // === ACCIONES ===
  "seller_actions": ["refund", "send_message_to_complainant", "open_dispute", "allow_return"],
  "mandatory_actions": ["refund"],
  "nearest_due_date": "2026-03-06T14:30:00.000-03:00",

  // === DETAIL ===
  "detail_title": "El comprador quiere devolver el producto",
  "detail_description": "Tenés hasta el viernes 6 de marzo para responder.",
  "detail_problem": "Nos dijeron que el producto llegó en buenas condiciones pero no lo quieren",
  "action_responsible": "seller",
  "detail_due_date": "2026-03-06T22:33:00.000-04:00",

  // === RESOLUCIÓN (solo si closed) ===
  "resolution_reason": "payment_refunded",
  "resolution_date": "2026-03-05T10:00:00.000-03:00",
  "resolution_benefited": ["complainant"],
  "resolution_closed_by": "seller",
  "resolution_coverage": false,

  // === FECHAS ===
  "date_created": "2026-03-04T08:28:44.000-04:00",
  "last_updated": "2026-03-04T14:30:00.000-04:00",
  "site_id": "MLA"
}
```

---

## LÓGICA DE CLASIFICACIÓN PARA RMA

### 1. `triage_tags` — Lo más específico

| Tag | Tipo RMA sugerido |
|-----|-------------------|
| `defective` | Garantia / Defecto de fabrica |
| `not_working` | No funciona |
| `different` | Producto equivocado |
| `incomplete` | Incompleto / Faltan piezas |
| `repentant` | Arrepentimiento (sin defecto) |

### 2. `expected_resolutions` — Accion esperada

| Resolucion | Accion RMA |
|------------|------------|
| `return_product` | Gestionar devolucion fisica |
| `change_product` | Gestionar cambio de producto |
| `refund` | Gestionar reembolso |

### 3. `reason_category` — Fallback general

| Categoria | Requiere RMA? |
|-----------|---------------|
| PDD (Producto Diferente o Defectuoso) | Si |
| PNR (Producto No Recibido) | No — es logistico |
| CS (Compra Cancelada) | No aplica |

### 4. `fulfilled` — Contexto de entrega

- `true` → Producto fue entregado, puede haber producto fisico que gestionar
- `false` → Producto NO entregado, no hay RMA fisico

### 5. `mandatory_actions` + `nearest_due_date` — Urgencia

- Si hay acciones obligatorias con fecha limite → el RMA es URGENTE
- `action_responsible = "seller"` → nosotros tenemos que actuar

---

## FLUJO DE DATOS (implementado)

```
buscarTraza(serial o ml_id)
  │
  ├─ traza_serial() o traza_ml()
  │   └─ Busca pedidos → extrae order_ids (ml_id)
  │
  └─ _fetch_claims_by_order_ids(order_ids)
      │
      ├─ Step 1: SELECT FROM rma_claims_ml WHERE resource_id IN (order_ids)
      │   └─ Carga cache local indexado por claim_id (no devuelve aún)
      │
      ├─ Step 2: SELECT FROM ml_previews WHERE extra_data->>'resource_id' IN (order_ids)
      │   Para cada claim encontrado en ml_previews:
      │   ├─ En cache + ml_previews.last_updated <= cache.updated_at → usar cache (0 HTTP)
      │   ├─ En cache + ml_previews.last_updated > cache.updated_at → RE-ENRICH vía HTTP
      │   ├─ NO en cache + extra_data enriched → _build_claim_from_enriched_extra() → save cache
      │   └─ NO en cache + extra_data raw → _enrich_claim_via_http() → save cache
      │
      ├─ Step 3: Claims en cache NO vistos en ml_previews
      │   ├─ Cerrados → usar cache directo
      │   └─ Abiertos (fallback 24h si webhook DB no disponible) → re-enrich o usar cache
      │
      └─ Step 4: _search_claims_via_api(order_ids)
          └─ GET /claims/search?order_id={id} → _enrich_claim_via_http() → save cache

_enrich_claim_via_http(claim_id)
  │
  ├─ GET /claims/{id}                        (requerido)
  ├─ GET /claims/{id}/detail                 (opcional)
  ├─ GET /claims/reasons/{reason_id}         (opcional, si reason_id existe)
  ├─ GET /claims/{id}/expected-resolutions   (opcional)
  ├─ GET /v2/claims/{id}/returns             (condicional: si related_entities tiene "return")
  ├─ GET /v1/claims/{id}/changes             (condicional: si related_entities tiene "change")
  ├─ GET /claims/{id}/messages?limit=1       (opcional, para count total)
  ├─ GET /claims/{id}/affects-reputation     (opcional)
  │
  ├─ _build_claim_from_ml_api() → ClaimML
  ├─ _save_claim_to_cache() → INSERT/UPDATE rma_claims_ml
  └─ _save_messages_to_cache() → INSERT rma_claims_ml_messages (si hay mensajes)
```

---

## ARCHIVOS RELEVANTES

| Archivo | Descripción |
|---------|-------------|
| `backend/app/routers/seriales.py` | Router principal. Schemas (ClaimML, ClaimReturn, etc.), SQL queries, helpers de claims, endpoints traza |
| `backend/app/models/rma_claim_ml.py` | Modelo SQLAlchemy para `rma_claims_ml` |
| `backend/app/models/rma_claim_ml_message.py` | Modelo SQLAlchemy para `rma_claims_ml_messages` |
| `backend/alembic/versions/20260304_rma_claims_ml_y_messages.py` | Migracion que crea las tablas |
| `frontend/src/components/ModalRma.jsx` | Modal RMA. Traducciones, rendering de claims con return/change/negociacion |
| `frontend/src/components/ModalRma.module.css` | Estilos del modal y las cards de claims |
| `backend/app/core/database.py` | `get_db()` (nuestra DB), `get_mlwebhook_engine()` (webhook DB) |

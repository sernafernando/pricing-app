# Bug: Alertas de Envio Gratis traen items duplicados (MLA# y MLA#/price_to_win)

## Problema

Las Alertas de Envio Gratis estan trayendo resultados duplicados. Para un mismo item aparecen DOS entradas:

- `MLA2564351464` (el item normal)
- `MLA2564351464/price_to_win` (el item con sufijo)

**IMPORTANTE:** No todos los items vienen duplicados. Algunos solo traen la version `/price_to_win`. No se deben bloquear los `/price_to_win` directamente porque hay casos donde es la unica entrada.

## Lo que se necesita

Que cada item aparezca UNA SOLA VEZ en las alertas de envio gratis. La logica debe ser:

1. Si existe tanto `MLA#` como `MLA#/price_to_win` para el mismo item -> quedarse con UNO solo (el `MLA#` sin sufijo, descartando el `/price_to_win`).
2. Si solo existe `MLA#/price_to_win` (sin la version limpia) -> mantenerlo, pero idealmente limpiar el sufijo `/price_to_win` del identificador mostrado.

## Contexto tecnico (de la investigacion de la DB)

### Estructura de datos relevante

La DB tiene una tabla `ml_catalog_status` con esta estructura:

```sql
CREATE TABLE public.ml_catalog_status (
    id integer NOT NULL,
    mla character varying(20) NOT NULL,
    catalog_product_id character varying(50),
    status character varying(50),          -- 'winning', 'competing', 'not_listed'
    current_price numeric(18,2),
    price_to_win numeric(18,2),            -- precio numerico, NO un sufijo de URL
    visit_share character varying(20),
    consistent boolean,
    competitors_sharing_first_place integer,
    winner_mla character varying(20),
    winner_price numeric(18,2),
    fecha_consulta timestamp without time zone,
    created_at timestamp without time zone
);
```

Y una vista `v_ml_catalog_status_latest` que trae el ultimo status por MLA:

```sql
CREATE VIEW public.v_ml_catalog_status_latest AS
 SELECT DISTINCT ON (mla) mla, catalog_product_id, status, current_price,
    price_to_win, visit_share, consistent, competitors_sharing_first_place,
    winner_mla, winner_price, fecha_consulta
   FROM public.ml_catalog_status
  ORDER BY mla, fecha_consulta DESC;
```

### Datos de envio gratis en la tabla de items publicados

```sql
-- En tb_mercadolibre_items_publicados:
mlp_price4freeshipping numeric(18,6),          -- umbral de precio para envio gratis
mlp_free_shipping boolean DEFAULT false,
mlp_free_method character varying(50),
mlp_free_shippingmshops boolean DEFAULT false,
mlp_free_shippingmshops_coeficient numeric(10,4),
```

### Tabla de notificaciones

```sql
CREATE TABLE public.notificaciones (
    id integer NOT NULL,
    tipo character varying(50) NOT NULL,       -- ej: 'markup_bajo'
    item_id integer,
    id_operacion bigint,
    codigo_producto character varying(100),
    descripcion_producto character varying(500),
    mensaje text NOT NULL,
    severidad severidadnotificacion DEFAULT 'INFO',
    estado estadonotificacion DEFAULT 'PENDIENTE',
    user_id integer,
    ml_id character varying(50),
    -- ... mas campos de markup/costos
);
```

### Conclusion clave

- La cadena `/price_to_win` como sufijo de un MLA **NO existe en la base de datos**.
- `price_to_win` es una columna numerica (el precio necesario para ganar el catalogo).
- La concatenacion `MLA#/price_to_win` se genera en el **codigo de la aplicacion** (backend).
- NO hay stored procedures ni triggers que generen notificaciones. Toda la logica esta en el backend.

## Donde buscar

Busca en el codigo del backend (probablemente NestJS/Node) la logica que:

1. Consulta la API de MercadoLibre o la tabla `ml_catalog_status` para datos de envio gratis.
2. Arma la lista de items para las alertas de envio gratis.
3. Concatena el MLA ID con `/price_to_win` — ahi esta el bug.

Es probable que haya un servicio o modulo que haga fetch a endpoints de ML tipo `/items/{MLA_ID}` y `/items/{MLA_ID}/price_to_win` y trate ambas respuestas como items separados en vez de mergear la info en un solo registro.

## Fix esperado

Deduplicar la lista de alertas de envio gratis. Cuando se procesen los items:

- Extraer el MLA base (sin `/price_to_win`) de cada entrada.
- Agrupar por MLA base.
- Quedarse con una sola entrada por MLA, priorizando la que tiene datos mas completos.
- Mostrar siempre el MLA limpio (sin sufijo).

# Control de reparación: vista de corridas del job de envío/SKU

Área: Reportes

## Resumen ejecutivo

Nueva pantalla **Control de reparación** (menú **Reportes → Control reparación**, con la etiqueta *Nuevo*) para que veas qué hizo el job de reparación de publicaciones (envío y SKU), corrida por corrida y MLA por MLA. Solo lectura: no escribe en Mercado Libre ni en las tablas de reparación.

Qué tenés que saber:

- **Filtros arriba**: tipo (Envío/SKU), estado, desde/hasta y un buscador "Buscar MLA".
- **Tabla de corridas**: inicio, duración, tipo, estado (pill de color), revisados, cambiados, omitidos, errores y el mensaje de error fatal.
- **Detalle de una corrida**: al hacer clic se abre un panel con el desglose por motivo (chips con conteo, clic para filtrar) y la tabla de eventos (MLA, acción, motivo, antes → después, hora).
- **Búsqueda por MLA**: la misma tabla de eventos a través de todas las corridas para ese MLA, más las escrituras confirmadas en ML (acción, payload, hora).

## Cómo se usa

1. Abrí **Reportes → Control reparación**.
2. Filtrá por tipo/estado/fechas o buscá un MLA.
3. Hacé clic en una corrida para ver su detalle.

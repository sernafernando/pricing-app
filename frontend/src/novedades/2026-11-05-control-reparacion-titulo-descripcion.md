# Control de reparación: título ML y descripción ERP en eventos

Área: Reportes

## Resumen ejecutivo

En **Control de reparación**, al abrir una corrida (o buscar un MLA), la tabla de eventos muestra **Título ML** y **Descripción ERP** junto al MLA. Se leen en vivo de la publicación y del producto ERP, para chequear si el cambio tiene sentido sin ir a otra pantalla.

Además, cuando el job de SKU corrige un `seller_sku`, el motivo del evento queda como `seller_sku` (antes aparecía vacío / “sin motivo”).

## Cómo se usa

1. Abrí **Reportes → Control reparación**.
2. Tocá una corrida o buscá un MLA.
3. En la tabla de eventos mirá **Título ML** y **Descripción ERP** junto al motivo y al antes → después.

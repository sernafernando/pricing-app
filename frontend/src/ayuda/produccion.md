# Producción

Área: Operaciones
Ruta: Operaciones → Producción
Permiso: Pedile a un administrador acceso a Producción.

## Para qué sirve

Muestra, en vista producción (EAN con guion + notebooks/PC armada/AIO), los productos a producir, con sus componentes. Sirve para ver qué hay que armar y desplegar los componentes de cada producto.

## Cómo se usa

Arriba dice **Producción**. Los botones son **Actualizar**, **Sincronizar ERP** y, si hay datos, **Desplegar todos / Colapsar todos**. Debajo están los filtros: vista lista/cards, tipo de envío y búsqueda por código o descripción. La vista producción está siempre activa (filtra EAN con guion + Notebooks, NB, PC ARMADA, AIO).

La tabla lista los productos con cantidad, paquetes y tipo de envío. Cada fila se expande para ver los componentes (con indicación si alguno se reemplaza). En vista cards se muestra la misma información en tarjetas.

Si falla la sincronización aparece un aviso con el error.

## Filtros y columnas

Filtro por tipo de envío y búsqueda. Columnas: Producto, Cantidad, Paquetes, Tipo Envío.

## Botones y acciones

- **Actualizar**: recarga.
- **Sincronizar ERP**: sincroniza con el ERP.
- **Desplegar todos / Colapsar todos**: expande o cierra todos los componentes.
- Expandir/colapsar componentes de una fila.

## Preguntas frecuentes

**¿Qué diferencia tiene con Preparación?**
Producción muestra siempre la vista producción (EAN con guion + notebooks/PC armada/AIO) y no incluye las otras pestañas.

**¿Qué significa "se reemplaza" en un componente?**
El componente tiene cantidad negativa y se reemplaza del producto original.

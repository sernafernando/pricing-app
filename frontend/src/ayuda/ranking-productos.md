# Ranking productos

Área: Reportes
Ruta: Reportes → Ranking productos
Permiso: Acceso al ranking completo (consultas.ver_ranking) o al ranking propio (consultas.ver_mi_ranking).

## Para qué sirve

Muestra el ranking de productos con stock, días sin venta, capital y valor potencial de venta. Sirve para detectar stock muerto y valorizar el inventario. Tiene dos vistas: **Detalle** y **Resumen**.

## Cómo se usa

Arriba dice **Ranking de Productos** con la cantidad de productos. Hay un selector **Detalle / Resumen**.

En **Detalle**, la tabla muestra Código, Descripción, Marca, Categoría, PM, Días sin venta, Ageing ERP, Última compra, Stock, Valor costo (USD/ARS) y Valor venta. Se puede ordenar por columnas.

En **Resumen**, se agrupa por Marca o PM, mostrando cantidad de productos, stock total, valor costo y valor venta.

La barra de herramientas permite filtrar por marca, categoría, PM (oculto para usuarios acotados), depósitos, sin stock, combos, solo stock muerto y búsqueda por texto. Las tarjetas KPI muestran Capital holdeado, Stock muerto (% del capital), SKUs con stock y Valor potencial venta.

El botón **Actualizar stock** sincroniza el stock desde el ERP (mientras trabaja dice **Actualizando…**). Debajo se muestra la última fecha de actualización del stock.

## Filtros y columnas

Filtros: marca, categoría, PM, depósitos, sin stock, combos, solo stock muerto, búsqueda.

Columnas Detalle: Código, Descripción, Marca, Categoría, PM, Días sin venta, Ageing ERP, Última compra, Stock, Valor costo, Valor venta.

Columnas Resumen: Marca/PM, PM (si agrupa por marca), # Productos, Stock total, Valor costo, Valor venta.

## Botones y acciones

- **Actualizar stock**: sincroniza stock desde el ERP.
- **Detalle / Resumen**: cambia la vista.
- **Marca / PM**: agrupa el resumen.
- Paginación con primera/anterior/siguiente/última página.

## Preguntas frecuentes

**¿Qué es "stock muerto"?**
Productos sin venta por mucho tiempo; se marca en rojo cuando es >= 30% del capital.

**¿Por qué no veo el filtro de PM?**
Los usuarios con ranking propio (no completo) solo ven sus asignaciones y no tienen filtro de PM.

# Prearmado

Área: Operaciones
Ruta: Operaciones → Prearmado
Permiso: Pedile a un administrador el permiso para prearmar combos.

## Para qué sirve

Sirve para gestionar los prearmados de combos: ver el estado de cada uno (pendiente, en proceso, armado, consumido, anulado), cargar y validar seriales, agregar notas y cambiar de estado.

## Cómo se usa

Arriba ves el título **Prearmado de Combos** y, si hay prearmados activos, un resumen por combo con totales por estado. Debajo están los botones **Nuevo prearmado**, **Re-matchear** y **Actualizar**, y los filtros por **estado** y búsqueda por **código**.

La tabla lista los prearmados con código, combo, estado, seriales validados/total, Windows, consumido en y creado. Al tocar una fila se abre el detalle.

En el detalle podés cambiar el estado (según los estados posibles), anular (con motivo), guardar notas, editar/borrar seriales y forzar guardado si el serial no valida.

## Filtros y columnas

Filtro por estado (Todos los estados, Pendiente, En proceso, Armado, Consumido, Anulado) y búsqueda por código.

Columnas: Código, Combo, Estado, Seriales, Windows, Consumido en, Creado, Acciones.

## Botones y acciones

- **Nuevo prearmado**: crea un prearmado.
- **Re-matchear**: vuelve a matchear consumos.
- **Actualizar**: recarga.
- Cambiar estado (botones por fila): avanzar/retroceder estado.
- **Anular**: anula (terminal).
- Ver detalle: abre seriales, notas y acciones.

## Preguntas frecuentes

**¿Qué estados puede tener un prearmado?**
Pendiente, En proceso, Armado, Consumido y Anulado.

**¿Qué pasa si un serial no valida?**
Podés marcar **Forzar** para guardarlo igual, indicando el motivo (no existe en ERP, otro item, ya en pedido, ya facturado, no disponible).

# Sell in / Sell out: permiso para ver los grupos y borrar varios a la vez

Área: Productos

**Resumen ejecutivo:** la pestaña **Grupos** de **Sell in / Sell out** tiene su propio permiso de lectura, y los grupos se pueden borrar de a varios con **Borrar seleccionados**.

## Qué cambia

- Un permiso nuevo, **Ver grupos de productos** (grupos.ver), muestra la pestaña **Grupos**. Lo tiene el rol administrador; a otra persona se le da desde su usuario.
- Con ese permiso solo, la pestaña es de lectura: se ven los grupos, sus filtros, cuántos productos alcanzan y qué campañas los usan, pero no aparecen **Nuevo grupo**, **Editar** ni las casillas.
- Crear, editar y borrar grupos sigue pidiendo el permiso de edición de constantes (config.editar_constantes).
- Con ese permiso, cada grupo tiene una casilla, y la del encabezado marca todos. **Borrar seleccionados** pide confirmar y borra los grupos que se pueden borrar. Los demás se quedan, cada uno con su motivo: los mismos casos que **Eliminar grupo** (lo usa una campaña activa, lo usan campañas anuladas, lo usa un offset o tiene consumo de offsets registrado).

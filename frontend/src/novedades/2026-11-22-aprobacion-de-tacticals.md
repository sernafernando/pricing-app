# Aprobación de tacticals

Área: Sell in / Sell out

## Resumen ejecutivo

Los tacticals ya no aplican apenas se cargan. Todo tactical nuevo queda **Pendiente de aprobación** y no baja costos ni suma a la ganancia hasta que alguien con el permiso **Aprobar tacticals** lo revisa y lo aprueba. Si a un tactical aprobado le cambiás montos, topes, fechas o alcance, vuelve a quedar pendiente. Los tacticals que ya existían siguen aprobados.

## Cómo se usa

1. Cargá el tactical como siempre desde **Nuevo tactical**. Al crearlo, el aviso dice que queda pendiente de aprobación.
2. En **Sell in / Sell out → Tacticals**, en **Estado**, elegí **Pendientes de aprobación** para ver los que esperan revisión. La columna **Estado** dice «Pendiente de aprobación».
3. Quien tiene el permiso abre el botón de acciones (⋮) de la fila y elige **Aprobar**. Después de confirmar, el tactical y todas sus líneas empiezan a aplicar, también a lo ya vendido dentro de sus fechas.
4. Un tactical aprobado dice debajo del estado «Aprobado por … el dd/mm/aaaa».
5. Arriba de la lista, **N pendientes de aprobación** dice cuántas cargas esperan revisión; tocalo para ir directo al filtro. Los montos de **Pendientes** y **Cobrados** ya no cuentan lo que está pendiente de aprobación.
6. Con el filtro **Pendientes de aprobación**, debajo de los tacticals aparece **Cargas sueltas pendientes de aprobación**: los bonos, compras, campañas y offsets de ganancia cargados fuera de un tactical. **Aprobar** abre su panel para aprobarlos ahí (un offset se aprueba desde la misma fila).

## A tener en cuenta

- El permiso **Aprobar tacticals** no viene con ningún rol, ni siquiera con el de superadmin: se da por usuario desde la gestión de permisos.
- Quien cargó el tactical también lo puede aprobar, si tiene el permiso.
- Editar un tactical aprobado y cambiar montos, porcentajes, topes, fechas, alcance o base lo vuelve a pendiente, y deja de aplicar hasta que lo aprueben de nuevo. Al editarlo, la pantalla te lo avisa. Cambiar solo el nombre, la nota o la cobranza no lo saca de aprobado.
- Los bonos, compras y campañas cargados sueltos siguen la misma regla: su panel dice «Pendiente de aprobación» y, con el permiso, tiene **Aprobar**.
- Lo que la migración de offsets pase a campañas o bonos de ahora en más también queda pendiente de aprobación. Lo que ya se había migrado no cambia. Si un offset ya está cargado a mano como bono, aunque ese bono esté pendiente, la migración no crea un segundo bono.
- Los offsets de ganancia nuevos también quedan pendientes: no suman a la rentabilidad ni registran consumo de topes hasta que los aprueben. Aparecen en **Cargas sueltas pendientes de aprobación** como **Offset de ganancia**, y **Aprobar** pide confirmación ahí mismo. Cambiarle a un offset aprobado el monto, el porcentaje, las fechas, los topes, los canales o el alcance lo vuelve a pendiente. Los offsets que ya existían siguen aplicando.

# Métricas ML: acceso solo a TP-Link

Área: Métricas ML

## Resumen ejecutivo

El permiso **Acceso solo TP-Link**, que ya funcionaba en **Ventas ML**, ahora también se aplica en **Métricas ML**. El usuario que lo tiene ve el tablero solo con la tienda **TP-Link**, siempre calculado con el **costo TP** (lista 8).

- **Solo la tienda TP-Link, siempre con costo TP:** no aparece el interruptor **Costos TP**, porque está siempre aplicado.
- **Total TP y Markup TP:** se muestran la tarjeta y la columna **Total TP**, y el markup se llama **Markup TP**.
- **Sin Total Gauss:** el **Total Gauss** no aparece en ningún lado: ni en las tarjetas, ni en la tabla, ni en el orden, ni en el selector de columnas, ni en el CSV.
- **Ordenar por Total TP:** la columna **Total TP** se puede ordenar. Si la tabla estaba ordenada por **Total Gauss**, pasa a ordenarse por **Total TP**.
- **También con Costos TP:** los demás usuarios pueden ordenar por **Total TP** cuando tienen encendido **Costos TP**. Si lo apagan con la tabla ordenada por **Total TP**, la tabla vuelve a ordenarse por **Facturado**, de mayor a menor.
- **Vistas disponibles:** **Producto**, **Publicación** y **Agrupado**, este último solo por **Tienda**.
- **Sin filtro de PM.**
- **Publicidad:** el control de **Publicidad** sigue disponible, y sus textos explican cómo afecta al **Total TP** y al markup.
- **Ventas sin costo TP:** si falta el costo TP de algunas ventas, aparece un aviso con la cantidad ("sin costo TP" en la tarjeta) y el **Total TP** muestra lo que se pudo calcular. Si falta en todas, se muestra **—** con la palabra **incompleto**. Una venta sin costo TP nunca se cuenta como 0.
- **Permisos necesarios:** además de **Acceso solo TP-Link**, el usuario necesita el permiso habitual para ver **Métricas ML**. Ve el Total TP y el Markup TP aunque no tenga el permiso de ver ganancia.

## Cómo se usa

1. Asignar el permiso **Acceso solo TP-Link** desde **Gestión → Admin → Usuarios**, en la vista **Por permiso**, como en Ventas ML.
2. Verificar que el usuario también tenga el permiso para ver **Métricas ML**.
3. Con ese usuario, abrir **Métricas ML**: el tablero se muestra solo con la tienda TP-Link y con costo TP.

> El cambio de permisos se ve al recargar la página.

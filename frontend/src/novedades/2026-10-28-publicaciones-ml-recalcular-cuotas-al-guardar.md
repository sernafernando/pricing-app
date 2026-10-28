# Publicaciones ML: guardar la configuración de cuotas recalcula las cuotas

Área: Publicaciones ML

## Resumen ejecutivo

En la vista **Producto** de **Publicaciones ML**, al guardar la **Configuración de cuotas** de un producto ahora se recalculan sus cuotas desde el precio clásica, como hace **Productos**. Antes la configuración se guardaba, pero las cuotas recién cambiaban la próxima vez que se recalculaban.

- **Qué listas:** se recalculan las cuotas **Web** y **PVP** del producto, solo las de la lista que tiene precio. Si no tiene precio Web ni PVP, no se recalcula nada y el panel lo avisa.
- **Después de recalcular:** los precios del panel y la lista se vuelven a leer, así que muestran las cuotas nuevas.
- **Si una lista no se puede recalcular:** la configuración queda guardada igual y el panel indica cuál lista falló y por qué.

## Cómo se usa

1. Abrir **Publicaciones ML** en la vista **Producto** y elegir un producto.
2. En la pestaña **Precios**, en **Configuración de cuotas**, tocar **Editar cuotas**, cambiar lo necesario y **Guardar**.
3. El mensaje confirma qué cuotas se recalcularon desde la clásica.

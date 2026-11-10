# Tacticals de sell out: monto total repartido entre los productos

Área: Sell out

## Resumen ejecutivo

Ahora una línea de un tactical de sell out puede ser un **monto total** (por ejemplo, USD 1.200 para varios modelos de notebook) que se reparte solo entre los productos de la línea en las fechas del tactical. Ya no hace falta pasarlo a un monto por unidad ni cargar cada producto a mano.

- Se elige cómo repartirlo: **Partes iguales por modelo**, **Según unidades vendidas** o **Proporcional al costo**.
- **Según unidades vendidas** sigue las ventas y las devoluciones de esas fechas, sin pasar nunca el total.
- Una campaña de monto total ya creada se puede volver a repartir con un criterio, viendo antes cómo queda. El reparto a mano sigue funcionando como siempre.
- El reparto por criterio es para quien gestiona campañas (`sell_out.gestionar`) o un administrador. Un PM con `sell_out.repartir` sigue repartiendo a mano los productos de sus marcas.

## Cómo se usa

1. En **Nuevo tactical**, elegir **Sell out** y cargar la línea con sus productos, una marca o una categoría.
2. En el monto de la línea, tocar **monto total** y escribir el importe en la moneda del tactical.
3. Debajo de lo que incluye la línea, elegir cómo repartirlo. La línea no lleva topes: el total es el tope.
4. Tocar **Crear tactical**.

Para volver a repartir una campaña de monto total:

- Abrir la campaña con **Ver campaña** y bajar a **Reparto del monto total**. **Criterio** dice cómo está repartida hoy (**Manual** si se cargó a mano).
- Elegir el criterio en **Repartir según** y tocar **Ver reparto**: se ve cada producto con sus unidades y su monto, y lo sin asignar.
- Tocar **Aplicar reparto** para guardarlo, o **Cancelar** para dejarlo como estaba.

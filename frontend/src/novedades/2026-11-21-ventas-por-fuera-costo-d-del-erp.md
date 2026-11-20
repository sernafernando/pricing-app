# Ventas por Fuera: el Costo D sale de la lista de costos del ERP

Área: Reportes

## Resumen ejecutivo

El **Costo D** de las ventas por fuera ahora se calcula igual que en **Ventas por Fuera (anterior)**: costo de la lista del ERP × dólar del día × 1,065. Antes se tomaba el "Precio Costo" del PDF, que ya venía con un recargo, y el margen quedaba más bajo de lo real (en algunos casos, negativo). Vale para **Operaciones por Fuera** y para **Métricas** con el canal **Por fuera**.

## Cómo se usa

No hay que hacer nada: cada PDF que se sube toma el costo del ERP. Las correcciones manuales de costo siguen mandando.

## A tener en cuenta

- El "Precio Costo" del PDF queda solo como referencia.
- Una línea sin producto, o con un producto sin costo en el ERP, queda sin costo y fuera del markup. Asignale el producto o cargale el costo a mano.
- El dólar es el de la app para el día de la venta; si falta ese día, se usa el último anterior.

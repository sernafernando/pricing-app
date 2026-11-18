# Operaciones por Fuera: la lista de ventas de los PDF, con correcciones

Área: Reportes

## Resumen ejecutivo

Nueva pantalla **Reportes → Operaciones por Fuera**: las ventas cargadas desde los PDF de GBP, comprobante por comprobante, como en **Ventas ML**. Muestra por qué hay líneas **Sin producto** y deja corregir cada línea: asignar el producto real (y recordarlo para las próximas cargas) o poner el costo a mano, con la misma ventana de costo de la pantalla anterior. Las correcciones **no se pierden** cuando se vuelve a subir el PDF.

## Cómo se usa

1. Abrí **Reportes → Operaciones por Fuera** y elegí el período.
2. Filtrá por empresa, vendedor, tipo de comprobante, **Sin producto** o **Revisar**, o buscá por cliente, artículo, código o número.
3. Tocá un comprobante para ver sus líneas al costado.
4. En una línea, tocá **Costo** para cargar el costo a mano o **Producto** para asignar el producto. Dejá tildado **Recordar para próximas cargas** si querés que ese código se resuelva solo de ahora en adelante.

## A tener en cuenta

- Corregir líneas pide el permiso ventas_fuera.subir_pdf. Ver el Total Gauss y el markup pide ventas_fuera.ver_ganancia.
- El recuadro **Por qué hay líneas sin producto** cuenta las líneas de cada causa: artículos manuales, líneas sin código y códigos que no están en el catálogo.
- Si volvés a subir un PDF y una línea corregida cambió (otro artículo, cantidad o precio), la corrección no se aplica sola: la línea queda marcada **Revisar** para que la confirmes o la quites.
- Las correcciones actualizan las métricas, los offsets y el sell in / sell out de esas líneas.

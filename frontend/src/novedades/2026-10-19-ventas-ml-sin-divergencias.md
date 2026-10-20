# Ventas ML: las ventas que fallan al ingresar se reintentan solas

Área: Ventas

## Resumen ejecutivo

Se quitó la pantalla **Divergencias ML Ventas** y el aviso **"N ventas no pudieron ingresar — el total de esta lista está incompleto"** de **Ventas ML**. Reemplaza lo que contaba la entrada **Ventas ML: la nueva pantalla de ventas de Mercado Libre** sobre esa franja y esa pantalla.

- **Reintento automático:** si una venta de Mercado Libre no puede guardarse (por ejemplo, por un corte momentáneo de la base de datos), el sistema la vuelve a intentar solo, cada vez más espaciado, hasta que entra.
- **Nada que revisar a mano:** esos casos ya no se listan para un operador; la venta aparece en **Ventas ML** apenas ingresa.
- **Menú:** la opción **Divergencias ML Ventas** ya no está en **Reportes**.

## Cómo se usa

No hace falta hacer nada. Abrir **Ventas ML** como siempre: el aviso rojo de ventas que no pudieron ingresar ya no aparece, y las ventas demoradas se suman a la lista cuando el reintento termina.

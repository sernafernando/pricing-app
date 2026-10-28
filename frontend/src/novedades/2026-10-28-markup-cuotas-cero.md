# Productos y Tienda: un markup de cuotas en 0 se guarda como 0

Área: Productos

## Resumen ejecutivo

Si a un producto le ponés **0** de markup adicional de cuotas, ahora queda en **0**. Antes ese 0 se perdía: la pantalla lo mostraba vacío, como si el producto usara el markup **global** de cuotas.

- **Dónde cambia:** en **Productos** y en **Tienda**, en los dos markups adicionales de cuotas de cada producto (**Web** y **PVP**), y en el detalle del producto.
- **Los demás valores no cambian:** un markup distinto de 0 se guardaba bien y sigue igual. Un campo vacío sigue queriendo decir "usar el global".

## Cómo se usa

1. Abrir **Productos** y editar la configuración de cuotas de un producto.
2. Poner **0** en el markup adicional de cuotas **Web** o **PVP** y guardar.
3. Volver a abrirlo: el campo muestra **0**, no vacío.

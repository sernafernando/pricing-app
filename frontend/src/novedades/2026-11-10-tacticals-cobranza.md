# Tacticals: chequeo de cobranza

Área: Sell in / Sell out

## Resumen ejecutivo

- Cada tactical dice si está **Pendiente** o **Cobrado** (con la fecha de cobro), en la nueva columna **Cobranza**.
- **Cargar cobro** abre un cuadro debajo de la fila: fecha de cobro (obligatoria), medio (Nota de crédito con su número, Fondo en distribuidor con el distribuidor, u Otro con un detalle) y observaciones.
- Nuevo filtro **Cobranza** (Todos, Pendientes, Cobrados) y, arriba de la lista, cuántos tacticals hay pendientes y cobrados con su monto por moneda: lo generado **de** su tope (por ejemplo `ARS 4.380.250 de 6.000.000`) y cuántos no tienen tope.

## Cómo se usa

1. Entrá a **Sell in / Sell out**, pestaña **Tacticals**.
2. En la columna **Cobranza** de un tactical, tocá **Cargar cobro**.
3. Cargá la **Fecha de cobro**. Si querés, elegí el **Medio**: con **Nota de crédito** escribí el **Número de NC**, con **Fondo en distribuidor** el **Distribuidor**, con **Otro** un **Detalle**. Sumá **Observaciones** si hace falta.
4. Tocá **Guardar**: la fila pasa a «Cobrado» con la fecha. Para corregirlo, **Editar cobro**; para volverlo a pendiente, **Deshacer cobro**.
5. Usá el filtro **Cobranza** para ver solo los **Pendientes** o los **Cobrados**. Los recuadros **Pendientes** y **Cobrados** cuentan todos los tacticals de los otros filtros, con el monto que generaron sus líneas de su tope de monto (en una línea de Monto total, el total es su tope). **N sin tope** cuenta los tacticals sin tope de monto en ninguna línea.

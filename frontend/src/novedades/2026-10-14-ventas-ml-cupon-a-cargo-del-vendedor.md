# Ventas ML: el cupón a cargo del vendedor ya cierra el desglose de IVA

Área: Ventas ML

## Resumen ejecutivo

Desde el **10/10**, cerca de la mitad de las ventas mostraban **"Este desglose de IVA no reconcilia."**. La causa fue un cargo nuevo que Mercado Libre empezó a descontar: el **costo del cupón que paga el vendedor** cuando el comprador usa un cupón (en general, igual al descuento del cupón). Ahora ese cargo se muestra en su propia línea y esas ventas vuelven a cerrar.

Qué tenés que saber:

- **Línea nueva: "Cupón a cargo del vendedor".** Aparece en el detalle de la venta con el monto del cupón. No lleva IVA (alícuota 0%), así que no genera crédito fiscal.
- **La venta se sigue declarando a precio completo**, sin descontar el cupón, como pide Mercado Libre para facturar. El IVA débito y la base de IIBB se calculan sobre el precio completo.
- **El desglose vuelve a cerrar.** Esas ventas dejan de figurar como "no reconcilia".
- **El Total Gauss y el neto ahora se calculan** en esas ventas (antes quedaban sin resolver). El cupón los reduce por su monto completo, porque no tiene IVA.
- **Ventas devueltas con cupón: neto 0.** Antes mostraban un neto negativo igual al cupón (por ejemplo, **-20.000**) aunque Mercado Libre había devuelto todo. Ahora muestran neto **0**, como cualquier devolución completa, y siguen marcadas como **venta con devolución**.
- **Las ventas anteriores se recalculan solas**, dentro de la hora siguiente a la actualización. Mientras tanto, alguna puede seguir mostrando el aviso.

## Cómo se usa

1. Abrí una venta con cupón en **Reportes → Ventas ML** (clic en la fila, se abre el panel al costado).
2. En la tarjeta **De dónde sale el neto** vas a ver la línea **Cupón a cargo del vendedor** con su monto.
3. En **IVA por alícuota** el cupón aparece como un componente más, al **0%**.
4. En la tarjeta **Total Gauss** ya ves el número calculado, con el cupón descontado.

> Si una venta con cupón sigue diciendo "no reconcilia" después de una hora de la actualización, avisá: puede ser otro caso distinto.

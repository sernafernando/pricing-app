# Métricas ML: por qué no coincide con Métricas ML (anterior)

Área: Métricas ML

## Resumen ejecutivo

**Métricas ML** y **Métricas ML (anterior)** pueden dar números distintos para el mismo período y los mismos filtros. No es un error: el tablero nuevo usa las mismas reglas que **Ventas ML**, y en tres puntos esas reglas son otras que las del tablero anterior.

## Qué cambia

1. **El día de la venta.** El anterior cuenta cada venta en su fecha de venta. El nuevo la cuenta en el día en que se acreditó el pago (en un pack, el último pago acreditado). Una venta hecha a fin de mes y acreditada al día siguiente cae en meses distintos en cada tablero.
2. **La ganancia.** El anterior muestra la **Ganancia Neta** y calcula el markup como ganancia sobre costo. El nuevo muestra el **Total Gauss**, el mismo de Ventas ML, y el markup se calcula sobre el costo de la mercadería, contando un pack solo cuando todas sus órdenes tienen Total Gauss y costo. Para el mismo período, Ganancia Neta y Total Gauss no son la misma cifra.
3. **Las cancelaciones.** El anterior deja afuera todas las ventas canceladas. El nuevo cuenta las canceladas que Mercado Libre cubrió, porque esa plata se cobra; las canceladas sin cobertura siguen afuera.

## Cómo se usa

Para comparar con **Ventas ML**, usar **Métricas ML**: las dos pantallas siguen las mismas reglas. No comparar cifra por cifra contra **Métricas ML (anterior)**.

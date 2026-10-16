# Métricas ML: restá la publicidad del Total Gauss y del markup

Área: Reportes

## Resumen ejecutivo

En **Métricas ML** ahora podés descontar la publicidad de Mercado Libre del **Total Gauss** y del **markup**, para ver cuánto dejan de verdad las ventas una vez pagados los Ads. Por defecto todo sigue como antes: la publicidad no se resta hasta que vos lo pedís.

Qué tenés que saber:

- **Control "Publicidad" con tres posiciones.** **Sin publicidad** no resta nada. **Restar Ads de publicaciones** resta, de cada publicación, la inversión en Ads que se le atribuye. **Restar toda la publicidad** resta además el gasto que no pertenece a ninguna publicación (Display, Brand Ads y Ads sin producto).
- **Se nota cuando está aplicado.** Aparece un aviso con el monto de publicidad restada y la fórmula del markup. Las tarjetas **Total Gauss** y **Markup promedio** se marcan como **Ajustado**, y en Total Gauss ves el valor original tachado.
- **Columna "Publicidad (inversión)".** Cada fila muestra lo que se le restó, sin IVA. Podés ordenar por esa columna.
- **Bloque "Publicidad (ML Ads)".** Con la publicidad restada, debajo de las tarjetas ves la inversión, las ventas por publicidad (directas e indirectas), **ACOS**, **ROAS**, **TACOS**, **CPC**, **CTR**, impresiones y clics. Un aviso indica hasta qué día hay datos de Ads y cuántos días faltan: un día faltante no es gasto cero.
- **Publicidad sin producto.** Sin filtros, un panel aparte lista Display, Brand Ads y los Ads sin producto, y marca cuáles se restaron. Nunca se reparten entre productos.
- **Filas solo de publicidad.** Los productos con inversión pero sin ventas aparecen en la tabla con la marca **SOLO ADS**, y los Ads sin producto en una fila **SIN PRODUCTO**.
- **Con filtros, solo se restan los Ads de publicaciones.** Si elegís "Restar toda la publicidad" y tenés filtros o un PM aplicado, el gasto de cuenta no se puede repartir entre productos. Entonces se resta solo lo de las publicaciones, y la pantalla te lo avisa con la marca **Aplicado**.
- **Permisos.** El control solo aparece si tenés el permiso de ver ganancia.
- **El CSV sigue a la pantalla.** Con publicidad restada, **Exportar CSV** suma la columna **Publicidad (inversión)** al lado de Total Gauss, y el Total Gauss y el markup salen ajustados, igual que en la tabla. Con **Sin publicidad** el archivo queda como siempre.
- **Sin cambios por ahora:** los gráficos chicos de las tarjetas siguen mostrando las cifras sin restar publicidad.

## Cómo se usa

1. Abrí **Reportes → Métricas ML**.
2. En el bloque de filtros, buscá **Publicidad** y elegí una de las tres posiciones.
3. Mirá el aviso azul: dice cuánto se restó. Las tarjetas **Total Gauss** y **Markup promedio** pasan a mostrar el valor ajustado, y aparece el bloque **Publicidad (ML Ads)**.
4. En la tabla, la columna **Publicidad (inversión)** muestra lo que se le restó a cada fila.
5. Para volver a lo de antes, elegí **Sin publicidad**.

> Si aparece el aviso amarillo "Con filtros solo se restan los Ads de publicaciones", sacá los filtros para restar también Display, Brand Ads y Ads sin producto.

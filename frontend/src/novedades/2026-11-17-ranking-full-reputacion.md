# Ver competencia: Full y reputación en el ranking

**Fecha:** 2026-11-17

**Resumen ejecutivo:** en **Publicaciones ML → Promos → Ver competencia**, cada fila del ranking muestra si el competidor es **Full** y la **reputación** del vendedor (power seller / nivel), además del nombre, precio y markup.

## Qué cambia

1. **Full** sale del snapshot de catálogo (`shipping_badges`), sin scrape.
2. La **reputación** se consulta a Mercado Libre por vendedor único del batch (no una vez por publicación); en el **Actualizar** manual el catálogo vuelve ya, y la reputación puede completar un momento después.
3. Stock residual e internacional de competidores siguen sin dato (MeLi no los expone en ese payload).

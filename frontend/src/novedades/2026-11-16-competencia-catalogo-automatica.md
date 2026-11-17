# Publicaciones ML: la competencia de catálogo se actualiza sola

Área: Publicaciones ML

## Resumen ejecutivo

La **Competencia del catálogo** de una publicación se vuelve a consultar automáticamente cada vez que Mercado Libre avisa que la publicación cambió, sin tocar **Actualizar**.

## Qué cambia

- Cuando cambia una publicación de catálogo activa (la publicación, sus precios o su competencia por el catálogo), la competencia se consulta de nuevo unos 2 minutos después.
- Si la última consulta tiene menos de 30 minutos, se espera al próximo cambio.
- Las publicaciones de catálogo que nunca se habían consultado se van consultando de a una después del deploy.
- **Actualizar** sigue funcionando igual para forzar una consulta en el momento.

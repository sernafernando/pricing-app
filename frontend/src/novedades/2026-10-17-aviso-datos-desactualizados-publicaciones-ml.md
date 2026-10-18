# Publicaciones ML: aviso de datos desactualizados más preciso

Área: Publicaciones

## Resumen ejecutivo

El aviso amarillo de datos desactualizados de **Publicaciones ML** ahora dice cuántas publicaciones están desactualizadas de verdad, y aparece mucho menos.

- **Texto corregido:** antes decía "la mayoría se actualizó hace más de 7 días", pero eso no era cierto: el aviso aparece cuando el 5% de publicaciones con la actualización más antigua supera los 7 días. Ahora dice el porcentaje real, por ejemplo: "Parte de los datos está desactualizada: el 7% de las publicaciones se actualizó hace más de 7 días."
- **Cuando no se conoce el porcentaje:** el aviso dice "el 5% más antiguo" en lugar de un número.
- **Actualización antes de tiempo:** el escaneo diario ahora vuelve a consultar en Mercado Libre las publicaciones sin cambios a partir de los 5 días, antes de llegar a los 7. Así el aviso deja de aparecer y desaparecer solo.

## Cómo se usa

1. Abrir **Reportes → Publicaciones ML**.
2. Si aparece el aviso amarillo, leer qué porcentaje de publicaciones está desactualizado.

> No hay que hacer nada para que se actualicen: el escaneo diario las vuelve a consultar solo.

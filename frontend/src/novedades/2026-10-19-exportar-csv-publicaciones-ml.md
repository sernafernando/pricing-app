# Publicaciones ML: exportar el listado a CSV

Área: Publicaciones

## Resumen ejecutivo

En **Publicaciones ML**, las vistas **Publicación** y **Producto** tienen un botón **Exportar CSV** que descarga todas las filas del listado en pantalla, con sus filtros y su orden.

- **Todo el listado, no solo la página:** se descargan todas las filas que cumplen los filtros, hasta 10.000.
- **Mismos filtros y mismo orden:** el archivo trae lo mismo que se ve en el listado.
- **Si no se puede exportar:** cuando el listado supera las 10.000 filas o la consulta tarda demasiado, la página muestra el motivo, para acotar los filtros y volver a intentar.
- **Permisos:** las cifras de ventas y de margen salen en el archivo solo para quien tiene permiso para verlas, igual que en el listado.
- **Vista Agrupado:** todavía no tiene exportación, así que el botón no aparece en esa vista.

## Cómo se usa

1. Abrir **Reportes → Publicaciones ML**.
2. Elegir la vista **Publicación** o **Producto**.
3. Aplicar los filtros y el orden que se necesiten.
4. Hacer clic en **Exportar CSV**. Mientras se prepara, el botón dice **Exportando…**.
5. Abrir el archivo descargado, que se llama, por ejemplo, `publicaciones-ml-producto-2026-10-19.csv`.

> Si aparece un motivo en lugar de la descarga, acotar los filtros, por ejemplo por marca, y volver a exportar.

# Exportar a Google Sheets

Área: Reportes

## Resumen ejecutivo

En **Métricas ML** y en **Publicaciones ML**, al lado de **Exportar CSV**, aparece el botón **Exportar a Sheets**. Crea una hoja de Google en el Drive de cada usuario con las mismas columnas y filas que el CSV, y la abre en una pestaña nueva.

- **Mismos datos que el CSV:** respeta los filtros, el orden y la vista que están en pantalla, con los mismos límites (hasta 10.000 filas).
- **Lista para leer:** el encabezado queda resaltado y fijo, con filtros en cada columna y filas alternadas. Los importes y cantidades quedan como números, los markups con dos decimales y el signo %, las fechas como dd/mm/aaaa (con la hora cuando la tienen) y los códigos conservan los ceros a la izquierda.
- **Avisos:** si el archivo trae un aviso (por ejemplo, que el markup no descuenta la publicidad), queda en gris debajo de los datos. Si la exportación quedó incompleta, no se crea ninguna hoja y se muestra el error.
- **Privacidad:** la aplicación solo accede a las hojas que ella misma crea. No ve el resto del Drive.

## Cómo se usa

1. Abrir **Métricas ML** o **Publicaciones ML** y dejar los filtros como se quieren exportar.
2. Hacer clic en **Exportar a Sheets**.
3. La primera vez, Google pide elegir la cuenta y dar permiso para crear hojas. Las siguientes veces la ventana de Google puede aparecer un momento para confirmar la cuenta.
4. La hoja se abre en una pestaña nueva. Si el navegador bloquea la pestaña, aparece el enlace **Abrir la hoja en Google Sheets**.

> Si se cierra la ventana de Google sin dar permiso, aparece **Exportación cancelada** y no se crea nada. La hoja queda guardada en **Mi unidad** con el mismo nombre que tendría el archivo CSV.

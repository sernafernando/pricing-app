# Clientes

Área: Operaciones
Ruta: Operaciones → Clientes
Permiso: Pedile a un administrador acceso a Clientes.

## Para qué sirve

Sirve para buscar y consultar los clientes de la empresa, ver sus datos completos, editar la información de contacto y la dirección, y exportar el listado a una planilla de Excel.

Esta pantalla no oculta botones según permisos: quien tiene acceso ve todas las acciones.

## Cómo se usa

Al entrar ves el título **Clientes** y, si hay resultados, un contador con el total de clientes.

1. Buscá por nombre, CUIT, email, ciudad o número de cliente en el buscador Buscar por nombre, CUIT, email, ciudad o N° cliente....
2. Afiná con los filtros de **Provincia**, Cond. Fiscal, **Sucursal** y **Vendedor**.
3. Si necesitás más opciones, abrí **Avanzados**.
4. Hacé clic sobre el nombre de un cliente para abrir su ficha completa.
5. Para descargar el listado, usá **Exportar**.

Mientras carga, la tabla dice Cargando clientes.... Si algo falla, aparece **Error al cargar clientes** con una cruz para cerrar el aviso.

## Filtros y columnas

En la barra principal tenés el buscador y los selectores **Provincia**, Cond. Fiscal, **Sucursal** y **Vendedor**. El botón **Avanzados** abre un panel con:

- Casilla **Solo activos** (viene tildada).
- **MercadoLibre**: **Con ML** o **Sin ML**.
- **Email**: **Con Email** o **Sin Email**.
- **Teléfono**: **Con Tel** o **Sin Tel**.
- **ID desde:** con el campo **Min**.
- **ID hasta:** con el campo **Max**.

Cuando hay filtros aplicados, el botón dice **Avanzados \*** y aparecen etiquetas con cada filtro activo. Podés quitar uno con la cruz de su etiqueta o limpiar todo con **Limpiar**.

La tabla muestra las columnas **ID**, **Nombre**, **CUIT/DNI**, **Email**, **Teléfono**, **Ciudad**, **Provincia**, Cond. Fiscal, **Vendedor**, **ML** y **Estado**.

- En **Nombre** podés hacer clic para ver el detalle (el cursor lo indica con **Click para ver detalle**).
- En **ML** aparece una marca **ML** cuando el cliente tiene cuenta de MercadoLibre; si pasás el mouse por encima ves su usuario.
- En **Estado** dice **Activo** o **Inactivo**.

Si no hay coincidencias, la tabla muestra **No se encontraron clientes**.

Abajo está la paginación: a la izquierda ves el rango y el total (por ejemplo, **1–50 de 120**), en el medio los botones de primera página, anterior, siguiente y última, y a la derecha **Por página:** con las opciones **25**, **50**, **100** y **200**. Si no hay resultados, dice **Sin resultados**.

## Botones y acciones

### Exportar

El botón **Exportar** abre la ventana **Exportar Clientes**. Ahí se explica: Seleccioná los campos a incluir. Se exportarán N clientes con los filtros aplicados. Podés usar **Seleccionar todos** o **Deseleccionar todos**, y tildar los campos que quieras incluir.

- **Cancelar** cierra la ventana.
- **Exportar XLSX** descarga la planilla. Mientras trabaja dice Exportando... y queda deshabilitado si no hay ningún campo tildado.
- Si falla, aparece **Error al exportar clientes**.

### Ver y editar un cliente

Al hacer clic en el nombre se abre la ficha **Cliente #N** con estas secciones:

- **Datos Principales**: ID Cliente, Nombre Comercial, Razón Social, CUIT/DNI, Email y Estado.
- **Contacto**: Teléfono y Celular.
- **Dirección**: Dirección, Ciudad, Código Postal y Provincia.
- **Información Fiscal y Comercial**: Condición Fiscal, Sucursal y Vendedor.
- **MercadoLibre**: ID ML y Usuario ML, solo si el cliente tiene cuenta vinculada.
- **Auditoría**: Fecha de Alta y Última Actualización.

El botón **Editar** habilita para modificar **Nombre Comercial**, **Email**, **Teléfono**, **Celular**, **Dirección**, **Ciudad** y **Código Postal**. Mientras editás aparecen **Guardar** y **Cancelar**. Al guardar bien muestra **Cliente actualizado correctamente**; si falla, **Error al actualizar cliente**. Para salir de la ficha usá **Cerrar** o la cruz de arriba.

## Preguntas frecuentes

**¿El cambio se guarda apenas escribo?**
No. Primero tenés que entrar en **Editar**, modificar los campos y después usar **Guardar**.

**¿Qué pasa si cancelo la edición?**
Se descartan los cambios y los campos vuelven a los valores que tenía el cliente.

**¿La exportación incluye todos los clientes o solo los que veo?**
Incluye los clientes que coinciden con la búsqueda y los filtros que tengas aplicados en ese momento.

**¿Cómo veo también los clientes inactivos?**
Por defecto está tildado **Solo activos**. Destildalo en el panel **Avanzados** para que aparezcan también los inactivos.

**¿Qué significa que el botón diga Avanzados \*?**
Que tenés al menos un filtro avanzado aplicado.

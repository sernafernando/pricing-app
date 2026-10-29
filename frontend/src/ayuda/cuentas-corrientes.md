# Cuentas Corrientes

Área: Reportes
Ruta: Reportes → Cuentas Corrientes
Permiso: Pedile a un administrador acceso a Cuentas Corrientes (reportes.ver_cuentas_corrientes).

## Para qué sirve

Muestra las cuentas corrientes (saldos) de proveedores y clientes, con la posibilidad de sincronizarlas con el ERP y exportarlas.

## Cómo se usa

Arriba hay dos pestañas: **Proveedores** y **Clientes**. Cada una muestra una tabla con el saldo de cada proveedor/cliente.

Hay un filtro por sucursal y por saldo (todos/positivos/negativos). El buscador permite buscar por nombre. El botón **Sincronizar** actualiza los datos desde el ERP (mientras trabaja dice **Sincronizando...**). El botón **Exportar** descarga a Excel.

Si falla la carga aparece un error.

## Filtros y columnas

Filtros: sucursal, saldo (todos/positivos/negativos), búsqueda por nombre.

Columnas: ID, Nombre (proveedor/cliente), Saldo, y posiblemente más según el ERP.

## Botones y acciones

- **Sincronizar**: actualiza desde el ERP.
- **Exportar**: descarga a Excel.

## Preguntas frecuentes

**¿Qué diferencia hay entre Proveedores y Clientes?**
Proveedores muestra lo que debemos a proveedores; Clientes muestra lo que nos deben los clientes.

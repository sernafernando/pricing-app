# Proveedores

Área: Administración
Ruta: Administración → Proveedores
Permiso: Pedile a un administrador acceso a Proveedores (administracion.ver_proveedores).

## Para qué sirve

Gestiona los proveedores de la empresa y sincroniza la lista desde el ERP.

## Cómo se usa

Arriba dice **Proveedores** con un buscador y un botón **Sincronizar** (que actualiza la lista desde el ERP). La tabla lista los proveedores con sus datos; se puede buscar por nombre.

El botón **Sincronizar** lanza el sync y muestra el progreso (con un timeout de 90 s). Al terminar se actualiza la lista.

## Filtros y columnas

Filtro: búsqueda por nombre, solo activos.

Columnas: datos del proveedor (razón social, CUIT, etc.).

## Botones y acciones

- **Sincronizar**: actualiza proveedores desde el ERP.

## Preguntas frecuentes

**¿De dónde salen los proveedores?**
Se sincronizan desde el ERP.

**¿Cuánto tarda la sincronización?**
Hasta 90 segundos.

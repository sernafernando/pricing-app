# Preparación

Área: Operaciones
Ruta: Operaciones → Preparación
Permiso: Pedile a un administrador acceso a Preparación (cada pestaña pide su propio permiso).

## Para qué sirve

Sirve para organizar la preparación de pedidos: ver los productos a preparar, imprimir pedidos pendientes, gestionar códigos postales, envíos Flex, checkeo de colecta y pistoleado. También permite marcar productos como pre-armados y banearlos de la vista de producción.

## Cómo se usa

Arriba dice **Envíos Pendientes** y, si tenés permiso, el botón **Corregir ^LH**. Debajo están las pestañas (según permisos): **Preparación**, **Pedidos Pendientes**, **Códigos Postales**, **Envíos Flex**, **Checkeo Colecta** y **Pistoleado**.

En **Preparación** ves tarjetas con estadísticas (items distintos, unidades total, paquetes total y por tipo de envío), la última actualización y los filtros: **Vista Produccion**, vista lista/cards, tipo de envío y búsqueda. La tabla lista los productos con código, descripción, cantidad, paquetes, tipo de envío y acciones. Podés marcar un producto como pre-armado (**🔧 Pre-armar**) y, en vista producción y con permiso, banearlo (🚫).

Los botones **Actualizar** y **Sincronizar ERP** recargan los datos. **🚫 Banlist** abre la lista de productos baneados. **+ Pre-armado** agrega un pre-armado manual.

Las pestañas **Envíos Flex** y **Pistoleado** piden identificación del operador con PIN.

## Filtros y columnas

Preparación: tipo de envío y búsqueda por código/descripción. Vista lista o cards. Vista producción filtra EAN con guion y notebooks/PC armada.

Columnas: Producto, Cantidad, Paquetes, Tipo Envío, Acciones.

## Botones y acciones

- **Actualizar**: recarga.
- **Sincronizar ERP**: sincroniza con el ERP.
- **🚫 Banlist**: gestiona productos baneados.
- **+ Pre-armado**: agrega un pre-armado manual.
- **🔧 Pre-armar**: marca unidades pre-armadas.
- **🚫**: banea de la vista de producción (con motivo).
- **Envíos Flex → Asignar** (logística, con etiquetas seleccionadas): si alguna ya tiene otra logística, pregunta antes: **Sobrescribir todas** o **Solo las sin logística** (cambia las vacías y las que están en «A designar», y dice cuántas salteó).
- **Envíos Flex → Deshacer último cambio** (con etiquetas seleccionadas): cada una vuelve a la logística que tenía antes de su último cambio; al final dice cuántas volvieron y por qué no volvieron las demás.
- **Envíos Flex → Masivas**: lista las últimas asignaciones masivas de logística (quién, cuándo, a qué logística, cuántas etiquetas) y **Deshacer** revierte una entera.

## Preguntas frecuentes

**¿Por qué no veo todas las pestañas?**
Cada pestaña pide un permiso propio.

**¿Qué pide PIN?**
Las pestañas Envíos Flex y Pistoleado piden que el operador se identifique con PIN.

**Asigné una logística masiva por error, ¿cómo la vuelvo atrás?**
En Envíos Flex, **Masivas**, buscá la asignación y hacé clic en **Deshacer**. Las etiquetas que alguien cambió después de esa asignación no se tocan: se informan aparte. Necesitás el mismo permiso que para asignar logística.

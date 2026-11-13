# Admin

Área: Gestión
Ruta: Gestión → Admin
Permiso: Pedile a un administrador acceso al panel de administración (admin.ver_panel).

## Para qué sirve

Panel de administración con pestañas: General, Empresas, Comisiones, Subcategorías, Constantes Pricing, Tiendas Oficiales, Marcas sin stock, Usuarios (permisos) y Roles.

## Cómo se usa

Arriba hay nueve pestañas: **General**, **Empresas**, **Comisiones**, **Subcategorías**, **Constantes Pricing**, **Tiendas Oficiales**, **Marcas sin stock**, **Usuarios** y **Roles**.

En **General** se puede sincronizar todo (tipo de cambio, productos ERP, etc.) y hay limpieza masiva de rebate/web transferencia (con confirmación por palabra). En las demás pestañas se gestionan empresas, comisiones, subcategorías, constantes de pricing, tiendas oficiales, permisos de usuarios y roles.

### Marcas sin stock

Una marca sin ningún producto en stock no aparece en los filtros ni en los selectores de marca de ninguna pantalla. Sus productos, ventas e historial se siguen viendo; solo deja de ofrecerse como opción. Si un filtro guardado o un link ya la tiene elegida, el filtro sigue funcionando y la marca se ve tildada.

En esta pestaña está la lista de marcas que se siguen mostrando aunque se queden sin stock:

- **Agregar una marca**: escribí parte del nombre; la búsqueda incluye todas las marcas, también las ocultas, y cada una dice si hoy tiene stock (**con stock** / **sin stock**). Tocá **Agregar**.
- La tabla muestra cada marca de la lista, si hoy tiene stock, quién la agregó y cuándo. El tacho la quita: si no tiene stock, se vuelve a ocultar.

En **Métricas ML**, **Métricas** y **Ventas ML** una marca sin stock también se muestra si vendió en el período y con los filtros que estás viendo.

Se necesita el permiso **Administrar marcas sin stock visibles** (admin.marcas_visibles).

## Filtros y columnas

Varían por pestaña.

## Botones y acciones

- **Sincronizar todo**: sincroniza tipo de cambio y productos ERP.
- Limpieza masiva de rebate/web transferencia (con confirmación por palabra).
- CRUD de empresas, comisiones, subcategorías, constantes, tiendas, usuarios y roles.
- **Marcas sin stock**: agregar o quitar marcas de la lista de marcas que se muestran aunque no tengan stock.

## Preguntas frecuentes

**¿Quién puede acceder al panel?**
Quien tenga el permiso admin.ver_panel.

**¿Por qué no aparece una marca en un filtro?**
Porque ninguno de sus productos tiene stock. Agregala en **Admin → Marcas sin stock** para que se siga mostrando.

**¿Qué es la limpieza masiva?**
Borra todos los rebates o web transferencias (con confirmación por palabra).

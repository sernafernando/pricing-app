# Cargar aportes de marcas en campañas de Ads ML

Área: Métricas ML

## Resumen ejecutivo

En **Reportes → Aportes de marcas (Ads ML)** ahora se pueden cargar los aportes de las marcas a cada campaña de Product Ads. Lo que se carga acá es lo que Métricas ML deja de descontar del Total Gauss.

- **Porcentaje o monto fijo:** un aporte puede ser un % del costo de la campaña o un monto fijo, sobre un rango de fechas que cargan ustedes.
- **Monto fijo:** al cargarlo hay que elegir qué pasa si la campaña gasta menos que el monto:
  - **Se recibe todo:** la marca paga el monto completo aunque la campaña haya gastado menos; el excedente suma.
  - **Se devuelve la diferencia:** el aporte cuenta solo hasta lo que gastó la campaña en ese rango.
- **Varios aportes por campaña:** se permiten, siempre que sus rangos de fechas no se superpongan.
- **Permisos:** cargar aportes requiere el permiso **Gestionar aportes de marcas a campañas de Ads** (por defecto, solo administradores). Sin ese permiso la pantalla se ve igual, pero sin el botón **Agregar aporte**.

## Cómo se usa

1. Abrir **Reportes → Aportes de marcas (Ads ML)**.
2. En la fila de la campaña, tocar **Agregar aporte**.
3. Elegir el **Tipo** (Porcentaje o Monto fijo), cargar el **Valor** y las fechas **Desde** y **Hasta**.
4. Si es monto fijo, elegir **Se recibe todo** o **Se devuelve la diferencia**.
5. Opcional: cargar la **Marca** y una **Nota**, y tocar **Guardar aporte**.

> Si el rango se superpone con otro aporte de la misma campaña, el sistema no lo guarda y muestra el motivo en el formulario.

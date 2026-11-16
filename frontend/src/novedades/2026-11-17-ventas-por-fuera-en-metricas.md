# Ventas por fuera en Métricas, cargadas desde los PDF de GBP

Área: Reportes

## Resumen ejecutivo

Las ventas por fuera de Mercado Libre ahora están en **Métricas**, al lado de las de Mercado Libre. Salen de los reportes PDF de GBP que se suben a la aplicación, ya no del sync de GBP. Con el selector **Canal** se ven solo las de ML, solo las de por fuera o las dos sumadas. El menú **Ventas por Fuera** abre Métricas con **Por fuera** elegido.

## Qué cambia

- Nuevo selector **Canal**: **ML**, **Por fuera** y **Todo**. En **Todo**, cada venta usa su regla (ML descuenta comisión y envío, por fuera no) y después se suman. Las tarjetas separan ML de Por fuera y **Ventas por día** apila los dos canales.
- **Costo por fuera**: **Costo D** (Precio Costo × 1,065, por defecto) o **Costo**. El markup lo calculamos nosotros, no se usa el del PDF.
- Filtros **Empresa** y **Vendedor** para las ventas por fuera.
- Columna **Canal** en **Todo**, y alerta **Sin producto** para los artículos que no están en el catálogo.
- **Subir PDF de ventas**: se sube el Reporte de Ventas Detalladas (y, si querés, el Reporte de Ventas para controlar los totales). Antes de importar se eligen los vendedores. Los de la lista de excluidos vienen sin tildar.
- **Cargas de PDF**: el historial de cargas, con quién subió cada una, qué reemplazó, el control con el resumen y qué reportes faltan subir.
- La pantalla vieja de Ventas por Fuera ya no está: sus links llevan a Métricas con **Por fuera**. La lista de **Vendedores excluidos** sigue en su propia pantalla.

## Cómo se usa

1. Entrá a **Reportes → Ventas por Fuera** (o a **Métricas ML** y elegí **Por fuera** en **Canal**).
2. Tocá **Subir PDF de ventas** y elegí el Reporte de Ventas Detalladas de GBP (exportado con "Con Impuestos: No"). Si querés, agregá el Reporte de Ventas.
3. Revisá los vendedores que encontró el PDF, tildá los que querés importar y tocá **Importar**.
4. Mirá el resultado: comprobantes, líneas, qué se reemplazó, líneas sin producto y el control con el resumen. Tocá **Ver métricas** para ver lo cargado.

> Subir el mismo período otra vez no duplica nada: el último PDF reemplaza lo cargado de esos vendedores en su rango de fechas.

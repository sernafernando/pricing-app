/** The cards this viewer sees right now, in the strip's order, for the "Indicadores" picker: Total Gauss and
 * markup only when the backend sent them. */
export function publicationKpiOptions(kpis) {
  return [
    { id: 'units', label: 'Unidades vendidas' },
    { id: 'gross', label: 'Facturado bruto' },
    kpis?.total_gauss && { id: 'total_gauss', label: 'Total Gauss' },
    kpis?.markup && { id: 'markup', label: 'Markup promedio' },
    { id: 'rows_with_sales', label: 'Publicaciones con ventas' },
    { id: 'ageing', label: 'Ageing promedio' },
  ].filter(Boolean);
}

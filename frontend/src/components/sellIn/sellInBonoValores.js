/** Form values of a brand bonus and the API body built from them (`SellInBonoIn`). */

export const BONO_VACIO = { marca: '', montoUnit: '', moneda: 'USD', fechaDesde: '', fechaHasta: '', descripcion: '' };

/** The form values of a bonus as the API answered it. */
export const valoresDeBono = (bono) => ({
  marca: bono.marca,
  montoUnit: String(Number(bono.monto_unit)),
  moneda: bono.moneda,
  fechaDesde: bono.fecha_desde,
  fechaHasta: bono.fecha_hasta,
  descripcion: bono.descripcion ?? '',
});

/** The create/edit body (`SellInBonoIn`): a full replace on edit. */
export const bodyDeBono = (valores) => ({
  marca: valores.marca,
  monto_unit: valores.montoUnit,
  moneda: valores.moneda,
  fecha_desde: valores.fechaDesde,
  fecha_hasta: valores.fechaHasta,
  descripcion: valores.descripcion.trim() || null,
});

/**
 * Test fixtures for the sell-in screen, shaped exactly like the backend's
 * Pydantic responses (`backend/app/schemas/sell_in.py`: `SellInCompraOut`,
 * `SellInCompraListOut`, `SellInCompraResumenOut`, `SellInPreviewOut`,
 * `SellInPrefillOut`).
 * Decimals travel as strings, as Pydantic serialises them.
 *
 * The values come from the backend's own tests
 * (`backend/tests/routers/test_sell_in_compras.py`): products 4512 SW-8 and
 * 4513 SW-16 at cost 100 and 300, a 1000 ARS proportional split (250 / 750,
 * 25 %), the 4514 AP-1 USD product, and the resumen of `tres_compras` plus
 * one USD purchase.
 */

export const COMPRA_ARS = {
  id: 1,
  proveedor_id: 7,
  pedido_compra_id: null,
  pedido_compra_ids: [],
  fecha_compra: '2026-10-01',
  fecha_ingreso: null,
  cuenta_desde: 'compra',
  moneda: 'ARS',
  monto_total: '1000.00',
  tipo_cambio: null,
  formula: 'proporcional',
  estado: 'activa',
  descripcion: 'Bonificación Q4 switches',
  usuario_id: 1,
  created_at: '2026-10-01T12:00:00',
  updated_at: '2026-10-01T12:00:00',
  proveedor_nombre: 'TP-Link',
  aplica: true,
  unidades_total: 20,
  unidades_consumidas: 0,
  unidades_restantes: 20,
  items: [
    {
      id: 11,
      item_id: 4512,
      codigo: 'SW-8',
      descripcion: 'Switch 8 bocas',
      cantidad: 10,
      costo_base_unit: '100',
      monto_asignado: '250.00',
      descuento_unit: '25',
      costo_con_sell_in_unit: '75',
      porcentaje: '25.00',
      unidades_consumidas: 0,
      unidades_restantes: 10,
    },
    {
      id: 12,
      item_id: 4513,
      codigo: 'SW-16',
      descripcion: 'Switch 16 bocas',
      cantidad: 10,
      costo_base_unit: '300',
      monto_asignado: '750.00',
      descuento_unit: '75',
      costo_con_sell_in_unit: '225',
      porcentaje: '25.00',
      unidades_consumidas: 0,
      unidades_restantes: 10,
    },
  ],
};

export const COMPRA_USD_ANULADA = {
  ...COMPRA_ARS,
  id: 2,
  proveedor_id: null,
  proveedor_nombre: null,
  fecha_compra: '2026-09-15',
  moneda: 'USD',
  monto_total: '2.00',
  tipo_cambio: '1250.5',
  estado: 'anulada',
  descripcion: 'Descuento access points',
  aplica: false,
  unidades_total: 2,
  unidades_restantes: 2,
  items: [
    {
      id: 21,
      item_id: 4514,
      codigo: 'AP-1',
      descripcion: 'Access point',
      cantidad: 2,
      costo_base_unit: '10',
      monto_asignado: '2.00',
      descuento_unit: '1',
      costo_con_sell_in_unit: '9',
      porcentaje: '10.00',
      unidades_consumidas: 0,
      unidades_restantes: 2,
    },
  ],
};

export const LISTA = { items: [COMPRA_ARS, COMPRA_USD_ANULADA], total: 2, page: 1, page_size: 50 };

export const RESUMEN = {
  conteo: { si: 3, no: 1, todas: 4 },
  monto_total: { ARS: '3000.00', USD: '5.50' },
  unidades_total: 32,
};

export const PREVIEW = {
  moneda: 'ARS',
  formula: 'proporcional',
  monto_total: '1000.00',
  // `SellInPreviewLinea`: a purchase line without its id and consumption counts.
  lineas: COMPRA_ARS.items.map((item) => {
    const linea = { ...item };
    delete linea.id;
    delete linea.unidades_consumidas;
    delete linea.unidades_restantes;
    return linea;
  }),
  totales: {
    cantidad: 20,
    costo_base_total: '4000',
    monto_asignado_total: '1000.00',
    costo_con_sell_in_total: '3000',
    porcentaje: '25.00',
  },
};

/** `GET /productos` rows (`ProductoResponse`), the fields the picker reads. */
export const PRODUCTOS = [
  { item_id: 4512, codigo: 'SW-8', descripcion: 'Switch 8 bocas', marca: 'TP-Link', moneda_costo: 'ARS', costo: 100 },
  { item_id: 4513, codigo: 'SW-16', descripcion: 'Switch 16 bocas', marca: 'Mercusys', moneda_costo: 'ARS', costo: 300 },
];

/** A purchase linked to two Compras operations (`pedido_compra_id` mirrors the first one). */
export const COMPRA_CON_OPERACIONES = { ...COMPRA_ARS, id: 4, pedido_compra_id: 15, pedido_compra_ids: [15, 16] };

/** `GET /sell-in/compras/prefill` (`SellInPrefillOut`) for operations 15 and 16 of supplier 7. */
export const PREFILL = {
  pedido_compra_ids: [15, 16],
  proveedor_id: 7,
  proveedor_nombre: 'TP-Link',
  moneda: 'USD',
  fecha_ingreso: '2026-10-05',
  items: [
    { item_id: 4512, codigo: 'SW-8', descripcion: 'Switch 8 bocas', cantidad: 12 },
    { item_id: 4513, codigo: 'SW-16', descripcion: 'Switch 16 bocas', cantidad: 4 },
  ],
};

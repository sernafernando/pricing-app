// Shape of GET /productos/{item_id} (ProductoResponse), as the endpoint returns
// it in backend/tests/integration/test_producto_detail_cuota_markups.py.
export const PRODUCTO = {
  item_id: 4101,
  codigo: 'ARCHER-AX55',
  descripcion: 'Router Archer AX55',
  marca: 'TP-LINK',
  categoria: 'ROUTERS',
  subcategoria_id: 55,
  moneda_costo: 'ARS',
  costo: 64000,
  costo_ars: 64000,
  iva: 21,
  stock: 7,
  precio_lista_ml: 98500.5,
  markup: 18.4,
  tiene_precio: true,
  precio_3_cuotas: 101200,
  precio_6_cuotas: 104800.25,
  precio_9_cuotas: null,
  precio_12_cuotas: 110900,
  markup_3_cuotas: 20.1,
  markup_6_cuotas: 22.35,
  markup_9_cuotas: null,
  markup_12_cuotas: -2,
  precio_pvp: 99000,
  precio_pvp_3_cuotas: 102000,
  precio_pvp_6_cuotas: null,
  precio_pvp_9_cuotas: null,
  precio_pvp_12_cuotas: null,
  markup_pvp: 19.5,
  markup_pvp_3_cuotas: 21,
  markup_pvp_6_cuotas: null,
  markup_pvp_9_cuotas: null,
  markup_pvp_12_cuotas: null,
  recalcular_cuotas_auto: null,
};

// The rebate, best offer and web transferencia fields of the same response,
// for a product that has all three (GET /productos/{item_id} computes them as
// the Productos listing does).
export const PRODUCTO_CON_REBATE_Y_OFERTA = {
  ...PRODUCTO,
  participa_rebate: true,
  porcentaje_rebate: 3.8,
  precio_rebate: 102391.37,
  markup_rebate: 21.3,
  out_of_cards: false,
  mejor_oferta_precio: 92000,
  mejor_oferta_monto_rebate: 4000,
  mejor_oferta_pvp_seller: 96000,
  mejor_oferta_markup: 0.1234,
  mejor_oferta_porcentaje_rebate: 4.17,
  mejor_oferta_fecha_hasta: '2099-12-31',
  participa_web_transferencia: true,
  porcentaje_markup_web: 6,
  precio_web_transferencia: 95000,
  markup_web_real: 24.4,
  preservar_porcentaje_web: false,
};

// The `sell_in_out` block of the same response (sell-in-sell-out T9,
// backend/app/schemas/sell_in_out_producto.py): a purchase lot with a 4.000
// discount per unit (12 units left) and a campaign crediting 1.500 per unit.
// Markups are keyed like the PPP ones; rows without a price have no key.
export const SELL_IN_OUT = {
  sell_in: { compra_item_id: 901, descuento_unit: 4000, costo: 60000, unidades_restantes: 12 },
  sell_out: { monto_unit: 1500, campana_ids: [3] },
  markups_sell_in: { clasica: 26.3, cuota_clasica_3: 28.1, cuota_clasica_6: 30.4, cuota_clasica_12: 4.5, pvp_clasica: 27.5, pvp_cuota_3: 29.1 },
  markups_sell_in_out: { clasica: 28.8, cuota_clasica_3: 30.6, cuota_clasica_6: 32.9, cuota_clasica_12: 7, pvp_clasica: 30, pvp_cuota_3: 31.6 },
};

export const PRODUCTO_CON_SELL_IN_OUT = { ...PRODUCTO, sell_in_out: SELL_IN_OUT };

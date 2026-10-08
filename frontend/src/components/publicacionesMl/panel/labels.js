/** Spanish names for the codes the detail carries; a code not listed keeps its own name. */

export const PRICE_SOURCE_LABELS = {
  sale_price: 'Precio de oferta',
  item_price: 'Precio de la publicación',
  productos_fallback: 'Precio de Productos',
  productos: 'Precio de Productos',
};

export const LISTING_TYPE_LABELS = { gold_special: 'Clásica', gold_pro: 'Premium' };

export const CONDITION_LABELS = { new: 'Nueva', used: 'Usada', not_specified: 'No especificada' };

// Only the modes whose Mercado Libre name is unambiguous are translated.
export const LOGISTIC_TYPE_LABELS = { fulfillment: 'Full', self_service: 'Flex', cross_docking: 'Colecta' };

export const STOCK_LOCATION_LABELS = {
  meli_facility: 'Depósito de Mercado Libre',
  selling_address: 'Dirección del vendedor',
  seller_warehouse: 'Depósito del vendedor',
};

export const SHIPPING_SOURCE_LABELS = { real: 'Real', erp: 'ERP', grupo_promedio: 'Promedio del grupo' };

export const LINK_STATE_LABELS = {
  auto: 'Automático',
  manual: 'Manual',
  sin_producto: 'Sin producto',
  conflicto: 'Conflicto',
  no_evaluado: 'Sin evaluar',
};

export const label = (labels, code) => (code == null ? null : (labels[code] ?? code));

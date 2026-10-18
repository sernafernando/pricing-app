// The kinds of a row's `sku_divergence` (backend `links.sku_divergence`): the seller SKU names another product than
// the linked one, or no single product (it matches nothing, or several).
export const SKU_DIVERGENCE_KINDS = {
  otro_producto: { label: 'Otro producto', tone: 'danger' },
  sin_coincidencia: { label: 'SKU sin coincidencia', tone: 'warning' },
};

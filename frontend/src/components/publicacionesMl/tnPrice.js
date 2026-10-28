/**
 * The Tienda Nube price Productos shows for a product (S3): the promotional one while a promotion is on, else the
 * regular one; null when it has none. One rule for the column (whether to draw the line) and TnPriceLine (what).
 */
const positive = (value) => (Number(value) > 0 ? value : null);
// By value, not truthiness: the API may send a price as text, and "0" is no price.
export const tnShownPrice = (product) => (product.tn_has_promotion && positive(product.tn_promotional_price)) || positive(product.tn_price);

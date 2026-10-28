/**
 * The Tienda Nube price Productos shows for a product (S3): the promotional one while a promotion is on, else the
 * regular one; null when it has none. One rule for the column (whether to draw the line) and TnPriceLine (what).
 */
export const tnShownPrice = (product) => (product.tn_has_promotion && product.tn_promotional_price) || product.tn_price || null;

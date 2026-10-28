import ListPriceCell from './ListPriceCell';

/**
 * Productos' price columns (S11), one set per mode like Productos' Normal / Cuotas / PVP, with Productos' headers.
 * A cell is the price of the row's product from `useListPrices` (`prices.byId`), and its markup only with
 * `canSeeMargin` (`ml_metricas.ver_ganancia`, as every markup of this screen). Like Productos, the rebate and the web
 * transfer read only when the product takes part. No product, no price or a request on its way never read 0.
 */
const GROUP = 'Precios de Productos';

const list = (key, header, price, markup, takesPart, markupScale = 1) => ({ key, header, price, markup, takesPart, markupScale });
const CLASICA = list('lista_clasica', 'Precio Clásica', 'precio_lista_ml', 'markup');
const CUOTAS = [3, 6, 9, 12];

const MODES = {
  normal: [
    CLASICA,
    list('lista_rebate', 'Precio Rebate', 'precio_rebate', 'markup_rebate', 'participa_rebate'),
    // The listing sends the best offer's markup as a fraction (every other one as a percentage); Productos scales it.
    list('lista_oferta', 'Mejor Oferta', 'mejor_oferta_precio', 'mejor_oferta_markup', undefined, 100),
    list('lista_web', 'Web Transf.', 'precio_web_transferencia', 'markup_web_real', 'participa_web_transferencia'),
  ],
  cuotas: [CLASICA, ...CUOTAS.map((n) => list(`lista_${n}_cuotas`, `${n} Cuotas`, `precio_${n}_cuotas`, `markup_${n}_cuotas`))],
  pvp: [
    list('lista_pvp', 'Precio PVP', 'precio_pvp', 'markup_pvp'),
    ...CUOTAS.map((n) => list(`lista_pvp_${n}_cuotas`, `PVP ${n} Cuotas`, `precio_pvp_${n}_cuotas`, `markup_pvp_${n}_cuotas`)),
  ],
};

/**
 * The columns of `mode` ('normal' | 'cuotas' | 'pvp'). `render(item)` draws a publication with its linked product;
 * `renderProduct(productId)` draws a product row (the Producto view).
 */
export function priceColumns(mode, { prices, canSeeMargin = false }) {
  return (MODES[mode] ?? MODES.normal).map((column) => {
    const renderProduct = (productId) => (
      <ListPriceCell
        product={productId == null ? null : prices.byId.get(productId)}
        column={column}
        loading={productId != null && prices.loading}
        canSeeMargin={canSeeMargin}
      />
    );
    return {
      key: column.key,
      group: GROUP,
      header: column.header,
      width: 130,
      align: 'right',
      render: (item) => renderProduct(item.link?.producto_item_id ?? null),
      renderProduct,
    };
  });
}

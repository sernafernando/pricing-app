import { Calculator } from 'lucide-react';
import { offerDetails } from '../pricing/offerDetails';
import { LISTS } from '../pricing/priceWrites';
import ListPriceCell from './ListPriceCell';
import PriceEditCell from './PriceEditCell';
import TnPriceLine from './TnPriceLine';
import { tnShownPrice } from './tnPrice';
import ToggleEditCell from './ToggleEditCell';
import styles from './cells.module.css';

/**
 * Productos' price columns (S11), one set per mode like Productos' Normal / Cuotas / PVP, with Productos' headers.
 * A cell is the price of the row's product from `useListPrices` (`prices.byId`), and its markup only with
 * `canSeeMargin` (`ml_metricas.ver_ganancia`, as every markup of this screen). Like Productos, the rebate and the web
 * transfer read only when the product takes part. No product, no price or a request on its way never read 0.
 *
 * A column with a `list` (the id of its row in `LISTS`, how Productos writes that price) is edited in place (S11c)
 * when `edit.permissions` allows that row's `perm`. The rebate and the web transfer (`toggles`) open Productos' editor
 * of that flag and its % instead (S1), with `productos.toggle_rebate` / `productos.toggle_web_transf`; the best offer
 * is not edited.
 */
const GROUP = 'Precios de Productos';

const LIST_ROWS = new Map(LISTS.flatMap((group) => group.rows).map((row) => [row.id, row]));

const list = (key, header, price, markup, { takesPart, markupScale = 1, edits, toggles, details, showTnPrice = false } = {}) => ({
  key,
  header,
  price,
  markup,
  takesPart,
  markupScale,
  list: edits,
  toggles,
  details,
  showTnPrice,
});
// The permission of each flag's editor (`pricePermissions`).
const TOGGLE_PERMS = { rebate: 'canToggleRebate', web: 'canToggleWebTransf' };
const CLASICA = list('lista_clasica', 'Precio Clásica', 'precio_lista_ml', 'markup', { edits: 'ml-clasica' });
const CUOTAS = [3, 6, 9, 12];

const MODES = {
  normal: [
    CLASICA,
    list('lista_rebate', 'Precio Rebate', 'precio_rebate', 'markup_rebate', { takesPart: 'participa_rebate', toggles: 'rebate' }),
    // The listing sends the best offer's markup as a fraction (every other one as a percentage); Productos scales it.
    // Under its price, its details as in Productos (S2).
    list('lista_oferta', 'Mejor Oferta', 'mejor_oferta_precio', 'mejor_oferta_markup', { markupScale: 100, details: offerDetails }),
    // Over it, the Tienda Nube price with its transfer price, as Productos (S3).
    list('lista_web', 'Web Transf.', 'precio_web_transferencia', 'markup_web_real', { takesPart: 'participa_web_transferencia', toggles: 'web', showTnPrice: true }),
  ],
  cuotas: [CLASICA, ...CUOTAS.map((n) => list(`lista_${n}_cuotas`, `${n} Cuotas`, `precio_${n}_cuotas`, `markup_${n}_cuotas`, { edits: `ml-${n}` }))],
  pvp: [
    list('lista_pvp', 'Precio PVP', 'precio_pvp', 'markup_pvp', { edits: 'pvp-clasica' }),
    ...CUOTAS.map((n) => list(`lista_pvp_${n}_cuotas`, `PVP ${n} Cuotas`, `precio_pvp_${n}_cuotas`, `markup_pvp_${n}_cuotas`, { edits: `pvp-${n}` })),
  ],
};

/**
 * The columns of `mode` ('normal' | 'cuotas' | 'pvp'). `render(item)` draws a publication with its linked product;
 * `renderProduct(productId)` draws a product row (the Producto view). `edit` (`{ permissions, onSave, saving }`, from
 * `pricePermissions` and `useInlinePriceEdit`) makes the list prices editable: `onSave(listRow, product, text)`; and
 * the rebate and web transfer: `onToggle(kind, product, draft)`, resolving true when saved.
 * `onCalculate(product)` (P3c, for whoever may edit prices) closes the group with Productos' Calcular button, which
 * opens its pricing modal on the row's product. `tnCardPercent` (`useTnCardPercent`) is the Tienda Nube card surcharge
 * the Web Transf. column takes off its TN price for the transfer hint.
 */
export function priceColumns(mode, { prices, canSeeMargin = false, edit = null, onCalculate = null, tnCardPercent = null }) {
  const columns = (MODES[mode] ?? MODES.normal).map((column) => {
    const listRow = column.list ? LIST_ROWS.get(column.list) : null;
    const editable = Boolean(edit && listRow && edit.permissions[listRow.perm]);
    const togglable = Boolean(edit?.onToggle && column.toggles && edit.permissions[TOGGLE_PERMS[column.toggles]]);
    const renderProduct = (productId) => {
      const content = renderCell(productId);
      const product = productId == null || prices.error ? null : prices.byId.get(productId);
      if (!column.showTnPrice || !product || !tnShownPrice(product)) return content;
      return (
        <div className={`${styles.stack} ${styles.stackEnd}`}>
          <TnPriceLine product={product} percent={tnCardPercent} />
          {content}
        </div>
      );
    };
    const renderCell = (productId) => {
      const product = productId == null ? null : prices.byId.get(productId);
      const failed = productId != null && prices.error;
      const cell = (
        <ListPriceCell product={product} column={column} loading={productId != null && prices.loading} failed={failed} canSeeMargin={canSeeMargin} />
      );
      if (!product || failed) return cell;
      if (togglable) {
        return (
          <ToggleEditCell kind={column.toggles} label={column.header} product={product} saving={edit.saving} onSave={(draft) => edit.onToggle(column.toggles, product, draft)}>
            {cell}
          </ToggleEditCell>
        );
      }
      if (!editable) return cell;
      return (
        <PriceEditCell label={column.header} value={product[column.price]} saving={edit.saving} onSave={(text) => edit.onSave(listRow, product, text)}>
          {cell}
        </PriceEditCell>
      );
    };
    return {
      key: column.key,
      group: GROUP,
      header: column.header,
      // The Web Transf. column holds the Tienda Nube price and its transfer hint on one line, as Productos (S3).
      width: column.showTnPrice ? 240 : 130,
      align: 'right',
      list: column.list,
      render: (item) => renderProduct(item.link?.producto_item_id ?? null),
      renderProduct,
    };
  });
  return onCalculate ? [...columns, calculateColumn(prices, onCalculate)] : columns;
}

function calculateColumn(prices, onCalculate) {
  // Only on a product whose prices are here: the modal shows its cost and stock from the same listing.
  const renderProduct = (productId) => {
    const product = productId == null ? null : prices.byId.get(productId);
    if (!product) return null;
    const label = product.descripcion ? `Calcular el precio de ${product.descripcion}` : `Calcular el precio del producto ${product.item_id}`;
    return (
      <button type="button" className={styles.calculate} aria-label={label} title={label} onClick={() => onCalculate(product)}>
        <Calculator size={14} aria-hidden="true" />
      </button>
    );
  };
  return {
    key: 'calcular_precio',
    group: GROUP,
    header: 'Calcular',
    width: 84,
    align: 'center',
    render: (item) => renderProduct(item.link?.producto_item_id ?? null),
    renderProduct,
  };
}

import { useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import { preciosAPI } from '../../services/api';
import { formatAmount } from '../../utils/ventasMlFormat';
import styles from './ProductPrices.module.css';

/**
 * The prices shown, per list, with the `ProductoResponse` columns of each
 * price and its markup. "Lista ML" is what pricing.py calls `lista_tipo=web`
 * (there are no separate web cuotas).
 */
const CUOTAS = ['3', '6', '9', '12'];

const LISTS = [
  {
    title: 'Lista ML',
    rows: [
      { id: 'ml-clasica', label: 'Clásica', precio: 'precio_lista_ml', markup: 'markup' },
      ...CUOTAS.map((cuota) => ({ id: `ml-${cuota}`, label: `${cuota} cuotas`, precio: `precio_${cuota}_cuotas`, markup: `markup_${cuota}_cuotas` })),
    ],
  },
  {
    title: 'PVP',
    rows: [
      { id: 'pvp-clasica', label: 'PVP clásica', precio: 'precio_pvp', markup: 'markup_pvp' },
      ...CUOTAS.map((cuota) => ({
        id: `pvp-${cuota}`,
        label: `PVP ${cuota} cuotas`,
        precio: `precio_pvp_${cuota}_cuotas`,
        markup: `markup_pvp_${cuota}_cuotas`,
      })),
    ],
  },
];

const isBlank = (value) => value === null || value === undefined;

const errorText = (error, fallback) => {
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' && detail ? detail : fallback;
};

const Empty = () => <span className={styles.empty}>—</span>;

function PriceRow({ row, product }) {
  const price = product[row.precio];
  const markup = product[row.markup];
  return (
    <tr>
      <th scope="row" className={styles.label}>
        {row.label}
      </th>
      <td className={styles.price}>{isBlank(price) ? <Empty /> : `$ ${formatAmount(price)}`}</td>
      <td className={styles.markup} data-negative={!isBlank(markup) && Number(markup) < 0 ? '' : undefined}>
        {isBlank(markup) ? <Empty /> : `${formatAmount(markup)}%`}
      </td>
    </tr>
  );
}

/**
 * The prices of ONE product (ML list and PVP, clásica and instalments) with
 * their markups, as `GET /productos/{item_id}` stores them. It needs only the
 * product's `item_id`, so the panel of a publication mounts it today and a
 * product row can mount it later. A missing price or markup is "—" (an older
 * backend sends no instalment markups), never 0.
 *
 * A price belongs to the product: the legend says a change reaches all its
 * publications.
 *
 * @param {object} props
 * @param {number} props.productItemId
 */
export default function ProductPrices({ productItemId }) {
  const [state, setState] = useState({ status: 'loading', product: null, error: null });

  useEffect(() => {
    let active = true;
    setState({ status: 'loading', product: null, error: null });
    preciosAPI
      .obtenerProducto(productItemId)
      .then((response) => active && setState({ status: 'ready', product: response.data, error: null }))
      .catch((error) => active && setState({ status: 'error', product: null, error: errorText(error, 'No se pudieron cargar los precios del producto.') }));
    return () => {
      active = false;
    };
  }, [productItemId]);

  const { status, product } = state;

  return (
    <div className={styles.prices}>
      <p className={styles.legend} role="note">
        <Info size={14} aria-hidden="true" />
        <span>El precio es del producto: cambiarlo afecta a todas sus publicaciones.</span>
      </p>

      {status === 'loading' && (
        <p className={styles.note} role="status">
          Cargando precios…
        </p>
      )}

      {status === 'error' && (
        <p className={styles.error} role="alert">
          {state.error}
        </p>
      )}

      {status === 'ready' && (
        <>
          <div className={styles.product}>
            <span className={styles.code}>{product.codigo}</span>
            <span>{product.descripcion}</span>
          </div>
          {LISTS.map((list) => (
            <table key={list.title} className={styles.table}>
              <caption className={styles.caption}>{list.title}</caption>
              <thead>
                <tr>
                  <th scope="col">Lista</th>
                  <th scope="col">Precio</th>
                  <th scope="col">Markup</th>
                </tr>
              </thead>
              <tbody>
                {list.rows.map((row) => (
                  <PriceRow key={row.id} row={row} product={product} />
                ))}
              </tbody>
            </table>
          ))}
        </>
      )}
    </div>
  );
}

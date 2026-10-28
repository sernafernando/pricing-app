import { useEffect, useState } from 'react';
import { usePermisos } from '../../../contexts/PermisosContext';
import { productosAPI } from '../../../services/api';
import { day } from './format';
import { Section } from './PanelParts';
import styles from './panel.module.css';

const VIEW_PERMISSION = 'productos.ver_info_compras';

// The ERP's currency ids (`curr_id`).
const CURRENCIES = { 1: 'ARS', 2: 'USD' };

const MONEY = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const QUANTITY = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2 });

/** An amount in the purchase's currency; an unknown currency is said, never shown as its id. */
function money(value, currencyId) {
  const code = CURRENCIES[currencyId];
  return code ? `${code} ${MONEY.format(value)}` : `${MONEY.format(value)} (moneda sin identificar)`;
}

/** Quantity × unit price = total; a missing quantity or price is said, and then there is no total to show. */
function Line({ quantity, unit, currencyId }) {
  if (quantity == null || unit == null) {
    return (
      <>
        {quantity == null ? 'Cantidad sin dato' : `${QUANTITY.format(quantity)} u.`} ×{' '}
        {unit == null ? 'precio sin dato' : money(unit, currencyId)}
      </>
    );
  }
  return (
    <>
      {QUANTITY.format(quantity)} u. × {money(unit, currencyId)} = <strong>{money(quantity * unit, currencyId)}</strong>
    </>
  );
}

function Purchase({ purchase }) {
  return (
    <li className={styles.entry}>
      <div className={styles.entryHead}>
        <span className={styles.entryTitle}>{purchase.proveedor || 'Sin proveedor'}</span>
        <span className={styles.entryWhen}>{day(purchase.fecha) ?? 'Sin fecha'}</span>
      </div>
      <span className={styles.change}>
        <Line quantity={purchase.cantidad} unit={purchase.precio_unitario} currencyId={purchase.moneda_id} />
      </span>
    </li>
  );
}

/**
 * A product's last five purchases from suppliers, as Productos' info modal shows them (`GET /productos/{id}/detalle`):
 * date, supplier, quantity, unit price in the purchase's currency and total. Only with `productos.ver_info_compras`;
 * without it nothing is read. Self-contained so the panel can place it anywhere; mount it with `key={productItemId}`.
 *
 * @param {object} props
 * @param {number} props.productItemId The ERP product.
 */
export default function ProductPurchases({ productItemId }) {
  const { tienePermiso } = usePermisos();
  const allowed = tienePermiso(VIEW_PERMISSION);
  const [read, setRead] = useState({ status: 'loading', purchases: [] });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!allowed) return undefined;
    let current = true;
    productosAPI
      .detalle(productItemId)
      .then(({ data }) => current && setRead({ status: 'ready', purchases: data?.ultimas_compras ?? [] }))
      .catch(() => current && setRead({ status: 'error', purchases: [] }));
    return () => {
      current = false;
    };
  }, [allowed, productItemId, attempt]);

  if (!allowed) return null;

  const retry = () => {
    setRead({ status: 'loading', purchases: [] });
    setAttempt((n) => n + 1);
  };

  let body;
  if (read.status === 'loading') {
    body = (
      <p className={styles.note} role="status">
        Cargando últimas compras…
      </p>
    );
  } else if (read.status === 'error') {
    body = (
      <div className={styles.error} role="alert">
        <span>No se pudieron cargar las últimas compras.</span>
        <button type="button" className="btn-tesla outline sm" onClick={retry}>
          Reintentar
        </button>
      </div>
    );
  } else if (read.purchases.length === 0) {
    body = <p className={styles.note}>No hay compras registradas para este producto.</p>;
  } else {
    body = (
      <ul className={styles.entries}>
        {read.purchases.map((purchase, index) => (
          <Purchase key={`${purchase.fecha}-${index}`} purchase={purchase} />
        ))}
      </ul>
    );
  }

  return <Section title="Últimas compras">{body}</Section>;
}

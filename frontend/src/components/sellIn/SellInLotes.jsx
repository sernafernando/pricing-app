import { useEffect, useId, useState } from 'react';
import { sellInLotesAPI } from '../../services/sellInAPI';
import styles from './SellInLotes.module.css';

const TITLE = 'Lotes sell in';
const PAGE_SIZE = 20;

const MONEY = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const money = (value) => `$ ${MONEY.format(Number(value))}`;

const CHANNELS = { ml: 'ML', fuera: 'Fuera de ML', tn: 'Tienda Nube' };

/** 'YYYY-MM-DD' as dd/mm/yyyy (or dd/mm), without going through a Date (no time zone shift). */
function day(value, { year = true } = {}) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? '');
  if (!match) return '-';
  return year ? `${match[3]}/${match[2]}/${match[1]}` : `${match[3]}/${match[2]}`;
}

const units = (n) => (n === 1 ? 'queda 1 unidad' : `quedan ${n} unidades`);

function statusLabel(lote) {
  if (lote.estado === 'vigente') return 'Vigente';
  if (lote.estado === 'en_cola') return 'En cola';
  if (lote.estado === 'agotado') return 'Agotado';
  return `Desde ${day(lote.fecha_desde, { year: false })}`;
}

function purchaseLabel(lote) {
  return [`#${lote.compra_id}`, lote.proveedor || 'Sin proveedor', ...lote.facturas].join(' · ');
}

/** S3: what the next sale gets, or, with no lot left, that the cost is back to normal and the cost bonus if any. */
function NextSale({ proxima, bonoCosto, hayLotes }) {
  if (proxima) {
    const { siguiente } = proxima;
    let despues = 'el costo vuelve al normal';
    if (siguiente) {
      const desde = siguiente.estado === 'desde' ? ` (desde ${day(siguiente.fecha_desde, { year: false })})` : '';
      despues = `${money(siguiente.descuento_unit)}${desde}`;
    }
    return (
      <p className={styles.next}>
        {`La próxima venta descuenta ${money(proxima.descuento_unit)} por unidad (lote ${proxima.numero}); ${units(proxima.restantes)} a ese valor, después ${despues}`}
      </p>
    );
  }
  const sinLote = hayLotes ? 'No quedan lotes con unidades: el costo vuelve al normal.' : 'Este producto no tiene lotes de sell in.';
  const bono = bonoCosto
    ? `Aplica el bono de costo ${bonoCosto.bono_ids.map((id) => `#${id}`).join(', ')}: descuenta ${money(bonoCosto.descuento_unit)} por unidad.`
    : 'Ningún bono de costo aplica.';
  return <p className={styles.next}>{`${sinLote} ${bono}`}</p>;
}

/** S4: the sales that consumed one lot, oldest first, a page at a time. */
function LotSales({ productItemId, lote }) {
  const [read, setRead] = useState({ status: 'loading', items: [], total: 0, page: 1 });
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const listId = useId();

  useEffect(() => {
    let current = true;
    sellInLotesAPI
      .consumos(productItemId, lote.compra_item_id, { page, page_size: PAGE_SIZE })
      .then(({ data }) => {
        if (!current) return;
        setRead((prev) => ({
          status: 'ready',
          items: page === 1 ? data.items : [...prev.items, ...data.items],
          total: data.total,
          page,
        }));
      })
      .catch(() => current && setRead((prev) => ({ ...prev, status: 'error' })));
    return () => {
      current = false;
    };
  }, [productItemId, lote.compra_item_id, page, attempt]);

  if (read.status === 'error') {
    return (
      <div className={styles.error} role="alert">
        <span>No se pudieron cargar las ventas del lote.</span>
        <button type="button" className="btn-tesla outline sm" onClick={() => setAttempt((n) => n + 1)}>
          Reintentar
        </button>
      </div>
    );
  }
  if (read.status === 'loading' && read.items.length === 0) {
    return (
      <p className={styles.note} role="status">
        Cargando ventas…
      </p>
    );
  }
  if (read.items.length === 0) return <p className={styles.note}>Ninguna venta consumió este lote todavía.</p>;
  return (
    <>
      <ul id={listId} className={styles.sales} aria-label={`Ventas del lote ${lote.numero}`}>
        {read.items.map((venta) => (
          <li key={`${venta.canal}-${venta.venta_ref}`}>
            {`${CHANNELS[venta.canal] ?? venta.canal} · venta ${venta.venta_ref} · ${day(venta.fecha_venta)} · ${venta.unidades} u. · ${money(venta.descuento_ars)}`}
          </li>
        ))}
      </ul>
      {read.items.length < read.total && (
        <button type="button" className={styles.toggle} disabled={read.status === 'loading'} onClick={() => setPage(read.page + 1)}>
          Ver más ventas
        </button>
      )}
    </>
  );
}

function DefaultSection({ title, children }) {
  const id = useId();
  return (
    <section aria-labelledby={id}>
      <h3 id={id}>{title}</h3>
      {children}
    </section>
  );
}

/**
 * The sell-in lots of a product as the next sales will consume them (`GET /sell-in/productos/{id}/lotes`): FIFO order,
 * each lot's purchase, the date it counts from, units, units consumed and left, unit discount in ARS and status
 * (Vigente, En cola, Agotado, Desde dd/mm); what the next sale gets; and, per lot, the sales that consumed it. Read
 * only. Without the permission that shows the product (403) it renders nothing. Mount it with `key={productItemId}`.
 *
 * @param {object} props
 * @param {number} props.productItemId The ERP product.
 * @param {Function} [props.container] The host's section (`{ title, children }`), so the viewer looks like its siblings.
 */
export default function SellInLotes({ productItemId, container = DefaultSection }) {
  const Container = container;
  const [read, setRead] = useState({ status: 'loading', data: null });
  const [attempt, setAttempt] = useState(0);
  const [open, setOpen] = useState(() => new Set());

  useEffect(() => {
    let current = true;
    sellInLotesAPI
      .lotes(productItemId)
      .then(({ data }) => current && setRead({ status: 'ready', data }))
      .catch((error) => current && setRead({ status: error?.response?.status === 403 ? 'forbidden' : 'error', data: null }));
    return () => {
      current = false;
    };
  }, [productItemId, attempt]);

  if (read.status === 'forbidden') return null;

  const toggle = (compraItemId) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(compraItemId)) next.delete(compraItemId);
      else next.add(compraItemId);
      return next;
    });

  let body;
  if (read.status === 'loading') {
    body = (
      <p className={styles.note} role="status">
        Cargando lotes…
      </p>
    );
  } else if (read.status === 'error') {
    body = (
      <div className={styles.error} role="alert">
        <span>No se pudieron cargar los lotes.</span>
        <button
          type="button"
          className="btn-tesla outline sm"
          onClick={() => {
            setRead({ status: 'loading', data: null });
            setAttempt((n) => n + 1);
          }}
        >
          Reintentar
        </button>
      </div>
    );
  } else {
    const { lotes = [], proxima = null, bono_costo: bonoCosto = null } = read.data ?? {};
    body = (
      <div className={styles.wrap}>
        <NextSale proxima={proxima} bonoCosto={bonoCosto} hayLotes={lotes.length > 0} />
        {lotes.length > 0 && (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Lote</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Compra</th>
                  <th scope="col">Desde</th>
                  <th scope="col" className={styles.num}>Unid.</th>
                  <th scope="col" className={styles.num}>Usadas</th>
                  <th scope="col" className={styles.num}>Quedan</th>
                  <th scope="col" className={styles.num}>Desc. x u.</th>
                  <th scope="col">Ventas</th>
                </tr>
              </thead>
              <tbody>
                {lotes.flatMap((lote) => {
                  const abierto = open.has(lote.compra_item_id);
                  const fila = (
                    <tr key={lote.compra_item_id} className={styles[lote.estado]}>
                      <td>{lote.numero}</td>
                      <td className={`${styles.status} ${lote.estado === 'desde' ? styles.statusDesde : ''}`}>{statusLabel(lote)}</td>
                      <td className={styles.purchase}>{purchaseLabel(lote)}</td>
                      <td>{day(lote.fecha_desde)}</td>
                      <td className={styles.num}>{lote.cantidad}</td>
                      <td className={styles.num}>{lote.consumidas}</td>
                      <td className={styles.num}>{lote.restantes}</td>
                      <td className={styles.num}>
                        {lote.moneda === 'ARS' ? money(lote.descuento_unit) : `${money(lote.descuento_unit)} (${lote.moneda})`}
                      </td>
                      <td>
                        <button
                          type="button"
                          className={styles.toggle}
                          aria-expanded={abierto}
                          aria-label={`${abierto ? 'Ocultar' : 'Ver'} ventas del lote ${lote.numero}`}
                          onClick={() => toggle(lote.compra_item_id)}
                        >
                          {abierto ? 'Ocultar' : 'Ver'}
                        </button>
                      </td>
                    </tr>
                  );
                  if (!abierto) return [fila];
                  return [
                    fila,
                    <tr key={`${lote.compra_item_id}-ventas`}>
                      <td colSpan={9}>
                        <LotSales productItemId={productItemId} lote={lote} />
                      </td>
                    </tr>,
                  ];
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  return <Container title={TITLE}>{body}</Container>;
}

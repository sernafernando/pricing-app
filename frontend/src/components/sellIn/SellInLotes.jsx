import { useEffect, useId, useState } from 'react';
import { sellInLotesAPI } from '../../services/sellInAPI';
import SellInModoCosto from './SellInModoCosto';
import { money } from './money';
import styles from './SellInLotes.module.css';

const TITLE = 'Historial de lotes sell in';
const PAGE_SIZE = 20;

const CHANNELS = { ml: 'ML', fuera: 'Fuera de ML', tn: 'Tienda Nube' };

/** 'YYYY-MM-DD' as dd/mm/yyyy (or dd/mm), without going through a Date (no time zone shift). */
function day(value, { year = true } = {}) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? '');
  if (!match) return '-';
  return year ? `${match[3]}/${match[2]}/${match[1]}` : `${match[3]}/${match[2]}`;
}


// The lots are history (sell-in-costo-si T5 PR A, L24): one still holding units is closed, never current, queued or
// due on a date.
function statusLabel(lote) {
  if (lote.estado === 'agotado') return 'Agotado';
  if (lote.estado === 'reemplazado') return 'Reemplazado';
  return 'Cerrado';
}

function unitsLabel(lote) {
  const usadas = lote.consumidas === 1 ? '1 usada' : `${lote.consumidas} usadas`;
  return `Quedan ${lote.restantes} de ${lote.cantidad} · ${usadas} · desde ${day(lote.fecha_desde)}`;
}

/** Without the purchases permission the supplier and invoices are withheld (`compraVisible`), never "Sin proveedor". */
function purchaseLabel(lote, compraVisible) {
  // A manual cost mode's block is no purchase: it is filed under its mode row.
  if (lote.manual) return `Carga manual #${lote.compra_id}`;
  if (!compraVisible) return `Compra #${lote.compra_id}`;
  return [`#${lote.compra_id}`, lote.proveedor || 'Sin proveedor', ...lote.facturas].join(' · ');
}

/** The lots no longer discount sales (T5 PR A, L24): what stays is their history, and costo SI holds the sell in. */
const HISTORIAL = 'Historial: los lotes ya no descuentan ventas. El sell in baja el costo SI a través de sus facturas.';

function LotsHistory({ lotes }) {
  return <p className={styles.next}>{lotes.length > 0 ? HISTORIAL : 'Este producto no tiene lotes de sell in.'}</p>;
}

/** S4: the sales that consumed one lot, oldest first, a page at a time. */
function LotSales({ productItemId, lote }) {
  const [read, setRead] = useState({ status: 'loading', items: [], total: 0, page: 1 });
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);

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

  const retry = (
    <div className={styles.error} role="alert">
      <span>No se pudieron cargar las ventas del lote.</span>
      <button
        type="button"
        className="btn-tesla outline sm"
        onClick={() => {
          setRead((prev) => ({ ...prev, status: 'loading' }));
          setAttempt((n) => n + 1);
        }}
      >
        Reintentar
      </button>
    </div>
  );
  // A failed first page has nothing to keep; a failed next page keeps the sales already listed.
  if (read.status === 'error' && read.items.length === 0) return retry;
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
      <ul className={styles.sales} aria-label={`Ventas del lote ${lote.numero}`}>
        {read.items.map((venta) => (
          <li key={`${venta.canal}-${venta.venta_ref}`}>
            {`${CHANNELS[venta.canal] ?? venta.canal} · venta ${venta.venta_ref} · ${day(venta.fecha_venta)} · ${venta.unidades} u. · ${money(venta.descuento_ars)}`}
          </li>
        ))}
      </ul>
      {read.status === 'error' && retry}
      {read.status !== 'error' && read.items.length < read.total && (
        <button
          type="button"
          className={styles.toggle}
          disabled={read.status === 'loading'}
          onClick={() => {
            setRead((prev) => ({ ...prev, status: 'loading' }));
            setPage(read.page + 1);
          }}
        >
          {read.status === 'loading' ? 'Cargando ventas…' : 'Ver más ventas'}
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
 * (Vigente, En cola, Agotado, Desde dd/mm); what the next sale gets; per lot, the sales that consumed it; and the
 * product's cost mode (`SellInModoCosto`), the only part that writes, behind its own permissions. Without the
 * permission that shows the product (403) it renders nothing. Mount it with `key={productItemId}`.
 *
 * @param {object} props
 * @param {number} props.productItemId The ERP product.
 * @param {Function} [props.container] The host's section (`{ title, children }`), so the viewer looks like its siblings.
 * @param {Function} [props.onChanged] Runs after the cost mode changed (the viewer reads its lots again by itself).
 * @param {Function} [props.layout] Places the parts itself: `({ nextSale, lots, modo, status }) => node` (each part
 *   may be null; all three are null without the permission; `status` is loading, error, ready or forbidden). Without
 *   it they go in that order inside `container`.
 * @param {boolean} [props.collapseModo] Shows the cost mode collapsed behind its current mode (product panel, S5).
 */
export default function SellInLotes({ productItemId, container = DefaultSection, onChanged, layout, collapseModo = false }) {
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

  if (read.status === 'forbidden') return layout ? layout({ nextSale: null, lots: null, modo: null, status: 'forbidden' }) : null;

  const toggle = (compraItemId) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(compraItemId)) next.delete(compraItemId);
      else next.add(compraItemId);
      return next;
    });

  let lots;
  let nextSale = null;
  let modo = null;
  if (read.status === 'loading') {
    lots = (
      <p className={styles.note} role="status">
        Cargando lotes…
      </p>
    );
  } else if (read.status === 'error') {
    lots = (
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
    const { lotes = [], proxima = null, compra_visible: compraVisible = false } = read.data ?? {};
    nextSale = <LotsHistory lotes={lotes} />;
    lots =
      lotes.length > 0 ? (
        <ol className={styles.lots} aria-label="Lotes en orden FIFO">
          {lotes.map((lote) => {
            const abierto = open.has(lote.compra_item_id);
            return (
              <li key={lote.compra_item_id} className={`${styles.lot} ${styles[lote.estado] ?? ''}`}>
                <div className={styles.lotHead}>
                  <span className={styles.lotNumber}>{`Lote ${lote.numero}`}</span>
                  <span className={`${styles.status} ${lote.estado === 'desde' ? styles.statusDesde : ''}`}>{statusLabel(lote)}</span>
                  <span className={styles.discount}>
                    {`${money(lote.descuento_unit)} por unidad${lote.moneda === 'ARS' ? '' : ` (compra en ${lote.moneda})`}`}
                  </span>
                </div>
                <div className={styles.lotLine}>{unitsLabel(lote)}</div>
                <div className={styles.lotLine}>
                  <span>{purchaseLabel(lote, compraVisible)}</span>
                  <button
                    type="button"
                    className={styles.toggle}
                    aria-expanded={abierto}
                    aria-label={`${abierto ? 'Ocultar' : 'Ver'} ventas del lote ${lote.numero}`}
                    onClick={() => toggle(lote.compra_item_id)}
                  >
                    {abierto ? 'Ocultar ventas' : 'Ver ventas'}
                  </button>
                </div>
                {abierto && <LotSales productItemId={productItemId} lote={lote} />}
              </li>
            );
          })}
        </ol>
      ) : null;
    modo = (
      <SellInModoCosto
        productItemId={productItemId}
        lotes={lotes}
        proxima={proxima}
        collapsible={collapseModo}
        onChanged={() => {
          setAttempt((n) => n + 1);
          onChanged?.();
        }}
      />
    );
  }

  if (layout) return layout({ nextSale, lots, modo, status: read.status });
  return (
    <Container title={TITLE}>
      {modo ? (
        <div className={styles.wrap}>
          {nextSale}
          {lots}
          {modo}
        </div>
      ) : (
        lots
      )}
    </Container>
  );
}

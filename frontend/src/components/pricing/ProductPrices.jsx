import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Info, Pencil, Percent, X } from 'lucide-react';
import { preciosAPI } from '../../services/api';
import { useOffsetsVigentes } from '../../hooks/useOffsetsVigentes';
import { useUsdRate } from '../../hooks/useUsdRate';
import { costoConOffset, markupConOffset, requiereTipoCambio } from '../../utils/offsetsGanancia';
import { formatMarkupInput, formatPrecioInput, parseMarkupInput, parsePrecioInput } from '../../utils/precioInput';
import { formatAmount } from '../../utils/ventasMlFormat';
import { Empty, MarkupChip } from './PriceParts';
import { formatRate, isBlank } from './priceFormat';
import { LISTS, errorText, warningText, writePrice } from './priceWrites';
import ProductToggles from './ProductToggles';
import styles from './ProductPrices.module.css';
import { sellInOrigen } from '../../utils/sellInOrigen';

/** The typed value as editable text again, for the editor's mode. */
const editorValue = (row, product, mode) =>
  mode === 'markup' ? formatMarkupInput(product[row.markup]) : formatPrecioInput(product[row.precio]);


/** "-": the product has no sell in (or no sell out) today. */
const NoSellInOut = ({ title }) => (
  <span className={styles.muted} title={title}>
    -
  </span>
);

/**
 * The cost of the purchase lot the next sale takes its sell in from (FIFO),
 * with its discount per unit and its origin (the lot's units left, or the % of cost bonuses) in the tooltip.
 */
function SellInCost({ sellIn }) {
  if (!sellIn) return <NoSellInOut title="Sin sell in vigente" />;
  const origen = sellInOrigen(sellIn); // a purchase lot or the % of cost bonuses (T25c)
  const pesos = `$ ${formatAmount(sellIn.descuento_unit)}`;
  // S10: in the cost's own currency (the backend converts it at the rate it converted the cost with), pesos aside.
  const moneda = sellIn.moneda_costo;
  if (moneda && moneda !== 'ARS') {
    const lines = [];
    if (!isBlank(sellIn.descuento_unit_moneda)) {
      lines.push(`Descuento por unidad: ${moneda} ${formatAmount(sellIn.descuento_unit_moneda)} (${pesos})`);
    } else {
      lines.push(`Descuento por unidad: ${pesos}`);
    }
    if (!isBlank(sellIn.costo)) lines.push(`c/ sell in en pesos: $ ${formatAmount(sellIn.costo)}`);
    lines.push(origen);
    const detalleMoneda = lines.join('\n');
    if (isBlank(sellIn.costo_moneda)) {
      return (
        <span className={styles.muted} title={detalleMoneda}>
          Sin tipo de cambio
        </span>
      );
    }
    return (
      <span className={styles.sellInCost} title={detalleMoneda}>
        {moneda} {formatAmount(sellIn.costo_moneda)}
      </span>
    );
  }
  const detalle = `Descuento por unidad: ${pesos}\n${origen}`;
  if (isBlank(sellIn.costo)) {
    return (
      <span className={styles.muted} title={detalle}>
        Sin tipo de cambio
      </span>
    );
  }
  return (
    <span className={styles.sellInCost} title={detalle}>
      $ {formatAmount(sellIn.costo)}
    </span>
  );
}

/** The credit per unit (without VAT) of the campaigns that would credit the next sale. */
function SellOutAmount({ sellOut }) {
  if (!sellOut) return <NoSellInOut title="Sin campañas de sell out vigentes" />;
  if (isBlank(sellOut.monto_unit)) {
    return (
      <span className={styles.muted} title="Falta el tipo de cambio o la base de la campaña para calcular el monto">
        Pendiente
      </span>
    );
  }
  return <span title="Por unidad, sin IVA">$ {formatAmount(sellOut.monto_unit)}</span>;
}

/**
 * The row's markup with sell in and sell out when there is sell out, else with
 * sell in only; "-" when the product has neither. "Pendiente" when an amount
 * is unknown (a lot without an ARS cost, a sell out without its rate or base),
 * so it never reads like a row without price ("—").
 */
function SellInOutMarkup({ row, price, sellInOut }) {
  if (!sellInOut) return <NoSellInOut title="Sin sell in ni sell out" />;
  // A row without price has no markup at all: nothing is pending there.
  if (isBlank(price)) return <Empty />;
  const conSellOut = sellInOut.markups_sell_in_out?.[row.sellInOut];
  if (!isBlank(conSellOut)) {
    return (
      <span title="Con sell in y sell out">
        <MarkupChip value={conSellOut} />
      </span>
    );
  }
  const sellOutPendiente = Boolean(sellInOut.sell_out) && isBlank(sellInOut.sell_out.monto_unit);
  const conSellIn = sellInOut.markups_sell_in?.[row.sellInOut];
  if (isBlank(conSellIn)) {
    const costoPendiente = Boolean(sellInOut.sell_in) && isBlank(sellInOut.sell_in.costo);
    if (costoPendiente || sellOutPendiente) {
      return (
        <span className={styles.muted} title="Falta el tipo de cambio o la base para calcular el markup">
          Pendiente
        </span>
      );
    }
    return <Empty />;
  }
  return (
    <span title={sellOutPendiente ? 'Con sell in; el sell out está pendiente' : 'Con sell in'}>
      <MarkupChip value={conSellIn} />
    </span>
  );
}

/**
 * What to keep in mind while setting a price: the product's IVA rate
 * (anyone who sees the prices) and, only for `showCost` (the caller's
 * ml_metricas.ver_ganancia), its cost in its own currency. A USD cost shows
 * its pesos at the current rate (`rate`, venta) as a small secondary figure.
 * Beside it, the cost with sell in and the sell out per unit, as the
 * backend computes them (`sell_in_out`). `action` (the panel's Calcular) closes the line.
 */
function ProductFacts({ product, showCost, isUsd, rate, action }) {

  let cost = <Empty />;
  if (isUsd) {
    // S10: the cost in its own currency first (USD 17,04); its pesos only as a small secondary figure.
    const original = `USD ${formatAmount(product.costo)}`;
    if (rate === undefined) cost = original;
    else if (rate === null) cost = `${original} (sin tipo de cambio)`;
    else {
      cost = (
        <>
          <span>{original}</span>{' '}
          <span className={styles.muted}>
            $ {formatAmount(product.costo * rate)} (× {formatAmount(rate)})
          </span>
        </>
      );
    }
  } else if (!isBlank(product.costo_ars ?? product.costo)) {
    cost = `$ ${formatAmount(product.costo_ars ?? product.costo)}`;
  }

  return (
    <div className={styles.facts} role="group" aria-label="Referencias del producto">
      <dl className={styles.factList}>
        {showCost && (
          <>
            <div className={styles.fact}>
              <dt className={styles.factLabel}>Costo</dt>
              <dd className={styles.factValue}>{cost}</dd>
            </div>
            <div className={styles.fact}>
              <dt className={styles.factLabel}>Costo c/ sell in</dt>
              <dd className={styles.factValue}>
                <SellInCost sellIn={product.sell_in_out?.sell_in} />
              </dd>
            </div>
            <div className={styles.fact}>
              <dt className={styles.factLabel}>Sell out por unidad</dt>
              <dd className={styles.factValue}>
                <SellOutAmount sellOut={product.sell_in_out?.sell_out} />
              </dd>
            </div>
          </>
        )}
        <div className={styles.fact}>
          <dt className={styles.factLabel}>IVA</dt>
          <dd className={styles.factValue}>{isBlank(product.iva) ? <Empty /> : `${formatRate(product.iva)}%`}</dd>
        </div>
      </dl>
      {action && <div className={styles.factAction}>{action}</div>}
    </div>
  );
}

/**
 * One price of a plan (S2): the amount and its markup under it, then -- for `showCost` -- the markup with offset and
 * with sell in/out, each with its own small label. The amount never wraps. Its editor replaces the amount in place.
 */
function PriceEntry({ row, product, costo, showCost, canEdit, editing, saving, onStart, onChange, onToggleMode, onSave, onCancel }) {
  const price = product[row.precio];
  const markup = product[row.markup];
  const isEditing = editing?.id === row.id;
  const byMarkup = isEditing && editing.mode === 'markup';

  const handleKeyDown = (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      onSave();
    } else if (event.key === 'Escape') {
      // Cancel the edit, not the side panel around the prices.
      event.stopPropagation();
      onCancel();
    }
  };

  return (
    <td className={styles.planEntry} data-entry={row.id} data-entry-label={row.label} data-editing={isEditing ? '' : undefined}>
      {isEditing ? (
        <div className={styles.priceEditor}>
          <input
            className={styles.input}
            type="text"
            inputMode="decimal"
            aria-label={byMarkup ? `${row.label} markup objetivo` : row.label}
            placeholder={byMarkup ? '%' : undefined}
            value={editing.value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={(event) => event.target.select()}
            disabled={saving}
            autoFocus
          />
          <span className={styles.entry}>
            <button
              type="button"
              className={`btn-tesla xs ${byMarkup ? 'outline-subtle-info' : 'outline'}`}
              aria-pressed={byMarkup}
              title={byMarkup ? 'Volver a editar el precio' : 'Fijar el markup y calcular el precio'}
              onClick={onToggleMode}
              disabled={saving}
            >
              <Percent size={12} aria-hidden="true" />
              Por markup
            </button>
            <button type="button" className="btn-tesla outline-subtle-success icon-only xs" aria-label="Guardar" onClick={onSave} disabled={saving}>
              <Check size={14} aria-hidden="true" />
            </button>
            <button type="button" className="btn-tesla ghost icon-only xs" aria-label="Cancelar" onClick={onCancel} disabled={saving}>
              <X size={14} aria-hidden="true" />
            </button>
          </span>
        </div>
      ) : (
        <div className={styles.entryTop}>
          <span className={styles.price}>{isBlank(price) ? <Empty /> : `$ ${formatAmount(price)}`}</span>
          {canEdit && (
            <span className={styles.entry}>
              <button
                type="button"
                className="btn-tesla ghost icon-only xs"
                aria-label={`Editar ${row.label}`}
                title="Editar el precio"
                onClick={() => onStart('precio')}
                disabled={saving}
              >
                <Pencil size={14} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="btn-tesla outline-subtle-info icon-only xs"
                aria-label={`Editar ${row.label} por markup`}
                title="Fijar el markup y calcular el precio"
                onClick={() => onStart('markup')}
                disabled={saving}
              >
                <Percent size={14} aria-hidden="true" />
              </button>
            </span>
          )}
        </div>
      )}
      <div className={styles.markup} data-col="markup" data-negative={!isBlank(markup) && Number(markup) < 0 ? '' : undefined}>
        <MarkupChip value={markup} />
      </div>
      {showCost && (
        <div className={styles.markupExtra}>
          <span className={styles.extraLabel}>c/ offset</span>
          <span data-col="markup-offset">
            <MarkupChip value={markupConOffset(markup, costo)} />
          </span>
        </div>
      )}
      {showCost && (
        <div className={styles.markupExtra}>
          <span className={styles.extraLabel}>c/ sell in/out</span>
          <span data-col="markup-sell-in-out">
            <SellInOutMarkup row={row} price={price} sellInOut={product.sell_in_out} />
          </span>
        </div>
      )}
    </td>
  );
}

// A row per plan (S2): the ML list's row and the PVP row of the same instalments, side by side.
const ML_LIST = LISTS.find((list) => list.id === 'ml');
const PVP_LIST = LISTS.find((list) => list.id === 'pvp');
// Paired by instalments, not by position: a plan the PVP list lacks shows an empty PVP cell.
const PLANS = ML_LIST.rows.map((ml) => ({
  id: ml.cuota ?? 'clasica',
  label: ml.label,
  entries: [ml, PVP_LIST.rows.find((pvp) => (pvp.cuota ?? null) === (ml.cuota ?? null)) ?? null],
}));

/**
 * The prices of ONE product in one table, a row per plan (clásica and each
 * instalment plan) with its ML list and PVP price and markup side by side
 * (S2), then its rebate, best offer and web transferencia (ProductToggles),
 * as `GET /productos/{item_id}` stores them; every price shows once. It needs only the
 * product's `item_id`, so the panel of a publication mounts it today and a
 * product row can mount it later. A missing price or markup is "—" (an older
 * backend sends no instalment markups), never 0.
 *
 * With `permissions`, each price the user may write gets an inline editor that
 * uses the same endpoints, payloads and negative-markup check Productos uses;
 * without any, the view is read-only. After a write the stored prices and
 * markups are read again and `onWritten` tells the caller.
 *
 * A price belongs to the product: the legend says a change reaches all its
 * publications (no confirmation per change).
 *
 * @param {object} props
 * @param {number} props.productItemId
 * @param {ReturnType<typeof import('./productPricePermissions').pricePermissions>} [props.permissions]
 * @param {() => void} [props.onWritten] Called after every successful write.
 * @param {boolean} [props.showCost] Show the product cost (ml_metricas.ver_ganancia).
 * @param {number} [props.readAgain] Changing it reads the prices again (something else wrote them), keeping an open
 *   edit as it was typed.
 * @param {import('react').ReactNode} [props.referenceAction] Closes the reference line (a panel's Calcular).
 * @param {import('react').ReactNode} [props.webTransferNote] Under the web transfer (a panel's Tienda Nube price).
 */
export default function ProductPrices({ productItemId, permissions, onWritten, showCost = false, readAgain = 0, referenceAction = null, webTransferNote = null }) {
  const [state, setState] = useState({ status: 'loading', product: null, error: null });
  const [editing, setEditing] = useState(null);
  const [pending, setPending] = useState(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  // The product on screen: a write that finishes after a switch must not
  // re-read, report or show anything for the previous one.
  const shownItemRef = useRef(productItemId);
  // The editor's version: every edit, mode switch, open or cancel bumps it, and
  // a markup preview only lands if the editor is still the one it was asked for.
  const editorVersionRef = useRef(0);
  const touchEditor = () => {
    editorVersionRef.current += 1;
  };

  const load = useCallback(async () => (await preciosAPI.obtenerProducto(productItemId)).data, [productItemId]);

  useEffect(() => {
    let active = true;
    shownItemRef.current = productItemId;
    setState({ status: 'loading', product: null, error: null });
    setEditing(null);
    setPending(null);
    setSaving(false);
    setMessage(null);
    load()
      .then((product) => active && setState({ status: 'ready', product, error: null }))
      .catch((error) => active && setState({ status: 'error', product: null, error: errorText(error, 'No se pudieron cargar los precios del producto.') }));
    return () => {
      active = false;
    };
  }, [load, productItemId]);

  // A read asked from outside: only the prices change, the editor and its message stay. Only a change of `readAgain`
  // asks it: another product is read by the effect above, once.
  const readAgainSeen = useRef(readAgain);
  useEffect(() => {
    if (readAgain === readAgainSeen.current) return undefined;
    readAgainSeen.current = readAgain;
    const itemId = productItemId;
    let active = true;
    load()
      .then((product) => active && shownItemRef.current === itemId && setState({ status: 'ready', product, error: null }))
      // A failed re-read keeps the prices on screen: the caller's own write already succeeded.
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [load, productItemId, readAgain]);

  const { status, product } = state;
  const editable = LISTS.some((list) => list.rows.some((row) => permissions?.[row.perm]));
  // The offsets are about the cost: read and shown only to who may see it.
  const offsets = useOffsetsVigentes(showCost);
  // This is the Mercado Libre channel: offsets that do not apply to it are left out.
  const contexto = offsets ? { ...offsets, canal: 'ml' } : null;
  const isUsd = product?.moneda_costo === 'USD' && !isBlank(product?.costo);
  // ONE rate for everything this tab converts -- the USD cost AND the USD
  // per-unit offsets: /tipo-cambio/actual venta, the rate pricing converts costs
  // with and the one the Costo line shows. Productos converts offsets with
  // /tipo-cambio-hoy instead (same latest venta, but with a CurExchHistory and
  // a 1000 fallback); here a missing rate is said, never assumed.
  const needsRate = isUsd || Boolean(product && contexto && requiereTipoCambio(product, contexto));
  const rate = useUsdRate(showCost && needsRate);
  const costo = product && contexto && (!needsRate || rate) ? costoConOffset(product, { ...contexto, tipoCambio: needsRate ? rate : null }) : null;

  // After a write the stored prices and markups are the backend's: read them again.
  const isShown = (itemId) => shownItemRef.current === itemId;

  const afterWrite = async (itemId, saved = 'Precio guardado') => {
    setMessage({ tone: 'ok', text: `${saved}.` });
    try {
      const fresh = await load();
      if (!isShown(itemId)) return;
      setState({ status: 'ready', product: fresh, error: null });
    } catch {
      if (!isShown(itemId)) return;
      setMessage({ tone: 'error', text: `${saved}, pero no se pudieron releer los precios.` });
    }
    onWritten?.();
  };

  /**
   * A rebate / web transferencia / fuera de tarjetas write (ProductToggles):
   * the same re-read and report as a price. Resolves true when it was saved.
   */
  const saveToggle = async (write, { saved, fallback }) => {
    const itemId = productItemId;
    setSaving(true);
    setMessage(null);
    try {
      await write(itemId);
      if (!isShown(itemId)) return false;
      await afterWrite(itemId, saved);
      return true;
    } catch (error) {
      if (isShown(itemId)) setMessage({ tone: 'error', text: errorText(error, fallback) });
      return false;
    } finally {
      if (isShown(itemId)) setSaving(false);
    }
  };

  const save = async (row, value, force = false) => {
    const precio = parsePrecioInput(value);
    if (precio === null) {
      setMessage({ tone: 'error', text: 'El precio debe ser un número válido mayor o igual a 0 (ej. 120.000,50).' });
      return;
    }
    if (!force && precio === 0) {
      // 0 clears the price in the backend, as in Productos: confirm it first.
      setPending({ kind: 'zero', row, value });
      return;
    }
    const itemId = productItemId;
    setSaving(true);
    setMessage(null);
    try {
      if (!force) {
        // Productos asks before saving a price under cost + fees; a failed check does not block the save.
        const check = await preciosAPI.calcularMarkup({ item_id: itemId, precio, pricelist_id: row.pricelist }).catch(() => null);
        if (!isShown(itemId)) return;
        const markup = check?.data?.markup;
        if (typeof markup === 'number' && markup < 0) {
          setPending({ kind: 'negative', row, value, markup });
          return;
        }
      }
      await commit(row, itemId, precio);
    } catch (error) {
      if (isShown(itemId)) setMessage({ tone: 'error', text: errorText(error, 'No se pudo guardar el precio.') });
    } finally {
      if (isShown(itemId)) setSaving(false);
    }
  };

  /** The write itself, shared by a typed price and a price resolved from a markup. */
  const commit = async (row, itemId, precio) => {
    await writePrice(row, itemId, precio, product);
    if (!isShown(itemId)) return;
    setEditing(null);
    setPending(null);
    await afterWrite(itemId);
  };

  /** Saves the price a confirmed markup preview resolved to (no second markup check). */
  const saveResolved = async ({ row, precio }) => {
    const itemId = productItemId;
    setSaving(true);
    setMessage(null);
    try {
      await commit(row, itemId, precio);
    } catch (error) {
      if (isShown(itemId)) setMessage({ tone: 'error', text: errorText(error, 'No se pudo guardar el precio.') });
    } finally {
      if (isShown(itemId)) setSaving(false);
    }
  };

  /**
   * A target markup: the backend resolves the row's price for it (with no
   * extra markup on top) and the user confirms that price before it is
   * written -- with the negative-markup warning when it lands below cost.
   */
  const previewMarkup = async (row, value) => {
    const markupObjetivo = parseMarkupInput(value);
    if (markupObjetivo === null) {
      setMessage({ tone: 'error', text: 'El markup debe ser un número válido (ej. 25 o 18,5).' });
      return;
    }
    const itemId = productItemId;
    const version = editorVersionRef.current;
    const isCurrent = () => isShown(itemId) && editorVersionRef.current === version;
    setSaving(true);
    setMessage(null);
    try {
      const { data } = await preciosAPI.calcularPorMarkup({
        item_id: itemId,
        pricelist_id: row.pricelist,
        markup_objetivo: markupObjetivo,
        adicional_markup: 0,
      });
      // A late answer for a markup the editor no longer holds is dropped.
      if (!isCurrent()) return;
      const precio = typeof data?.precio === 'number' ? data.precio : NaN;
      if (!Number.isFinite(precio) || precio <= 0) {
        setMessage({ tone: 'error', text: 'No se pudo calcular un precio válido para ese markup.' });
        return;
      }
      const markup = typeof data.markup_real === 'number' ? data.markup_real : markupObjetivo;
      const negative = markupObjetivo < 0 || markup < 0;
      setPending({ kind: negative ? 'negative' : 'markup', resolved: true, row, value, markup, precio });
    } catch (error) {
      if (isCurrent()) setMessage({ tone: 'error', text: errorText(error, 'No se pudo calcular un precio para ese markup.') });
    } finally {
      if (isShown(itemId)) setSaving(false);
    }
  };

  const confirm = (current) => (current.resolved ? saveResolved(current) : save(current.row, current.value, true));

  const cancel = () => {
    touchEditor();
    setEditing(null);
    setPending(null);
  };

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
          <ProductFacts product={product} showCost={showCost} isUsd={isUsd} rate={rate} action={referenceAction} />
          {editable && (
            <p className={styles.hint}>
              <Percent size={14} aria-hidden="true" />
              <span>Cada precio se edita por monto o al fijar su markup: el precio resultante se calcula y se confirma antes de guardarlo.</span>
            </p>
          )}
          {/* A table wider than the panel scrolls on its own instead of widening the panel. */}
          <div className={styles.planScroll}>
            <table className={styles.table} aria-label="Precios por plan">
              <caption className={styles.caption}>
                <span className={styles.captionTitle}>Precios</span>
                <span className={styles.captionSub}>Lista ML y PVP de cada plan de cuotas</span>
              </caption>
              <thead>
                <tr>
                  <th scope="col">Plan</th>
                  <th scope="col" title={ML_LIST.subtitle}>
                    {ML_LIST.title}
                  </th>
                  <th scope="col" title={PVP_LIST.subtitle}>
                    {PVP_LIST.title}
                  </th>
                </tr>
              </thead>
              <tbody>
                {PLANS.map((plan) => (
                  <tr key={plan.id} className={styles.row} data-editing={plan.entries.some((row) => row && editing?.id === row.id) ? '' : undefined}>
                    <th scope="row" className={styles.label}>
                      {plan.label}
                    </th>
                    {plan.entries.map((row, index) =>
                      row === null ? (
                        <td key={`none-${index}`} className={styles.planEntry}>
                          <Empty />
                        </td>
                      ) : (
                        <PriceEntry
                          key={row.id}
                          row={row}
                          product={product}
                          costo={costo}
                          showCost={showCost}
                          canEdit={Boolean(permissions?.[row.perm])}
                          editing={editing}
                          saving={saving}
                          onStart={(mode) => {
                            touchEditor();
                            setPending(null);
                            setMessage(null);
                            setEditing({ id: row.id, mode, value: editorValue(row, product, mode) });
                          }}
                          onToggleMode={() => {
                            touchEditor();
                            setPending(null);
                            setMessage(null);
                            setEditing((current) => {
                              const mode = current.mode === 'markup' ? 'precio' : 'markup';
                              return { ...current, mode, value: editorValue(row, product, mode) };
                            });
                          }}
                          onChange={(value) => {
                            // A warning confirms the value it was raised for: a new value drops it.
                            touchEditor();
                            setPending(null);
                            setEditing((current) => ({ ...current, value }));
                          }}
                          onSave={() => (editing.mode === 'markup' ? previewMarkup(row, editing.value) : save(row, editing.value))}
                          onCancel={cancel}
                        />
                      ),
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ProductToggles
            key={productItemId}
            product={product}
            permissions={permissions}
            saving={saving}
            onSave={saveToggle}
            onInvalid={(text) => setMessage({ tone: 'error', text })}
            webTransferNote={webTransferNote}
          />

          {pending && (
            <div className={pending.kind === 'markup' ? styles.preview : styles.warning} role={pending.kind === 'markup' ? 'status' : 'alert'}>
              <span>{warningText(pending)}</span>
              <div className={styles.warningActions}>
                <button type="button" className="btn-tesla outline sm" onClick={() => setPending(null)} disabled={saving}>
                  Cancelar
                </button>
                <button
                  type="button"
                  className={pending.kind === 'markup' ? 'btn-tesla primary sm' : 'btn-tesla outline-subtle-danger sm'}
                  onClick={() => confirm(pending)}
                  disabled={saving}
                >
                  {pending.kind === 'zero' ? 'Borrar el precio' : pending.kind === 'markup' ? 'Guardar precio' : 'Guardar de todas formas'}
                </button>
              </div>
            </div>
          )}

          {message && (
            <p className={message.tone === 'error' ? styles.error : styles.note} role={message.tone === 'error' ? 'alert' : 'status'}>
              {message.text}
            </p>
          )}
        </>
      )}
    </div>
  );
}

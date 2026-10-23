import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Info, Pencil, Percent, X } from 'lucide-react';
import { preciosAPI } from '../../services/api';
import { useOffsetsVigentes } from '../../hooks/useOffsetsVigentes';
import { costoConOffset, markupConOffset, requiereTipoCambio } from '../../utils/offsetsGanancia';
import { formatMarkupInput, formatPrecioInput, parseMarkupInput, parsePrecioInput } from '../../utils/precioInput';
import { formatAmount } from '../../utils/ventasMlFormat';
import { Empty, MarkupChip } from './PriceParts';
import { formatRate, isBlank } from './priceFormat';
import ProductToggles from './ProductToggles';
import styles from './ProductPrices.module.css';

/**
 * The prices shown, per list, with the `ProductoResponse` columns of each
 * price and its markup. "Lista ML" is what pricing.py calls `lista_tipo=web`
 * (there are no separate web cuotas).
 *
 * To write one, `write` names the endpoint Productos uses for that cell
 * (`rapido` = /precios/set-rapido, `cuota` = /precios/set-cuota),
 * `pricelist` the list its negative-markup check asks about and `perm` the
 * `pricePermissions` flag that allows it. `short` is the visible label of an
 * installments row ("12C"), so every list fits the side panel; `label` stays
 * its full name (tooltip, accessible name, messages). `sellInOut` is the row's key in
 * `sell_in_out.markups_sell_in[_out]` of GET /productos/{item_id}, the PPP
 * markup keys (costo_ppp_service.ppp_key_*).
 */
const ML_CUOTAS = [
  ['3', 17],
  ['6', 14],
  ['9', 13],
  ['12', 23],
];
const PVP_CUOTAS = [
  ['3', 18],
  ['6', 19],
  ['9', 20],
  ['12', 21],
];

const LISTS = [
  {
    id: 'ml',
    title: 'Lista ML',
    subtitle: 'Precio de las publicaciones en Mercado Libre',
    rows: [
      { id: 'ml-clasica', label: 'Clásica', precio: 'precio_lista_ml', markup: 'markup', pricelist: 4, write: 'rapido', listaTipo: 'web', perm: 'canEditClasica', sellInOut: 'clasica' },
      ...ML_CUOTAS.map(([cuota, pricelist]) => ({
        id: `ml-${cuota}`,
        label: `${cuota} cuotas`,
        short: `${cuota}C`,
        precio: `precio_${cuota}_cuotas`,
        markup: `markup_${cuota}_cuotas`,
        pricelist,
        write: 'cuota',
        cuota,
        listaTipo: 'web',
        perm: 'canEditMlCuotas',
        sellInOut: `cuota_clasica_${cuota}`,
      })),
    ],
  },
  {
    id: 'pvp',
    title: 'PVP',
    subtitle: 'Precio de venta al público',
    rows: [
      { id: 'pvp-clasica', label: 'PVP clásica', short: 'PVP clás.', precio: 'precio_pvp', markup: 'markup_pvp', pricelist: 12, write: 'rapido', listaTipo: 'pvp', perm: 'canEditPvp', sellInOut: 'pvp_clasica' },
      ...PVP_CUOTAS.map(([cuota, pricelist]) => ({
        id: `pvp-${cuota}`,
        label: `PVP ${cuota} cuotas`,
        short: `PVP ${cuota}C`,
        precio: `precio_pvp_${cuota}_cuotas`,
        markup: `markup_pvp_${cuota}_cuotas`,
        pricelist,
        write: 'cuota',
        cuota,
        listaTipo: 'pvp',
        perm: 'canEditPvp',
        sellInOut: `pvp_cuota_${cuota}`,
      })),
    ],
  },
];

const errorText = (error, fallback) => {
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' && detail ? detail : fallback;
};

/** The user's Productos preference for recalculating instalments, default on. */
function recalcularCuotasPreference() {
  try {
    const saved = window.localStorage.getItem('recalcularCuotasAuto');
    return saved === null ? true : JSON.parse(saved);
  } catch {
    return true;
  }
}

/** Same rule as Productos: the product's own setting wins over the preference. */
const recalcularCuotas = (product) =>
  isBlank(product.recalcular_cuotas_auto) ? recalcularCuotasPreference() : product.recalcular_cuotas_auto;

/**
 * What the inline confirmation says before a price is saved: a cleared price,
 * a negative markup, or the price a target markup resolved to.
 */
function warningText(pending) {
  const { row } = pending;
  const resulting = pending.precio === undefined ? '' : ` Precio resultante: $ ${formatAmount(pending.precio)}.`;
  if (pending.kind === 'markup') {
    return `Precio resultante para ${row.label} con markup ${formatAmount(pending.markup)}%: $ ${formatAmount(pending.precio)}.`;
  }
  if (pending.kind === 'zero') {
    return row.write === 'rapido'
      ? `Esto borra el precio de la lista ${row.listaTipo === 'pvp' ? 'PVP' : 'ML'} y todas sus cuotas.`
      : `Esto borra el precio de ${row.label}.`;
  }
  return `Markup negativo en ${row.label}: ${formatAmount(pending.markup)}%. El precio queda por debajo del costo más comisiones.${resulting}`;
}

/** The typed value as editable text again, for the editor's mode. */
const editorValue = (row, product, mode) =>
  mode === 'markup' ? formatMarkupInput(product[row.markup]) : formatPrecioInput(product[row.precio]);

function writePrice(row, itemId, precio, product) {
  if (row.write === 'rapido') {
    const params = { item_id: itemId, precio, recalcular_cuotas: recalcularCuotas(product) };
    return preciosAPI.setRapido(row.listaTipo === 'pvp' ? { ...params, lista_tipo: 'pvp' } : params);
  }
  return preciosAPI.setCuota({ item_id: itemId, tipo_cuota: row.cuota, precio, lista_tipo: row.listaTipo });
}

/**
 * The current USD rate (`venta`, the one pricing converts costs with), read
 * only when the cost shown needs it (a USD cost or a USD per-unit offset):
 * undefined while it loads, null when there is none.
 */
function useUsdRate(enabled) {
  const [rate, setRate] = useState(undefined);
  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    setRate(undefined);
    preciosAPI
      .tipoCambioActual()
      .then((response) => {
        const venta = Number(response?.data?.venta);
        if (active) setRate(Number.isFinite(venta) && venta > 0 ? venta : null);
      })
      .catch(() => active && setRate(null));
    return () => {
      active = false;
    };
  }, [enabled]);
  return rate;
}

/** "Rebate TP-Link" or, without a description, the offset's id. */
const offsetLabel = (aplicado) => aplicado.descripcion || `Offset #${aplicado.id}`;

/**
 * The cost with the profit offsets that reach the product discounted, as
 * Productos applies them to its "markup con offsets": the amount and, below,
 * each offset that applied with its discount in ARS.
 */
function OffsetCost({ product, offsets, needsRate, rate, costo }) {
  if (isBlank(product.costo)) return <Empty />;
  if (offsets === undefined || (needsRate && rate === undefined)) return <span className={styles.muted}>Cargando offsets…</span>;
  if (offsets === null) return <span className={styles.muted}>No se pudieron leer los offsets</span>;
  if (needsRate && rate === null) return <span className={styles.muted}>Sin tipo de cambio para el offset</span>;
  if (!costo) return <span className={styles.muted}>Sin offsets vigentes</span>;
  const detalle = costo.aplicados.map((a) => `${offsetLabel(a)}: -$ ${formatAmount(a.monto)}`).join('\n');
  return (
    <>
      <span className={styles.offsetCost} title={detalle}>
        $ {formatAmount(costo.costoAjustado)}
      </span>
      <ul className={styles.offsetList} aria-label="Offsets aplicados">
        {costo.aplicados.map((a) => (
          <li key={a.id} className={styles.offsetItem}>
            <span className={styles.offsetName}>{offsetLabel(a)}</span>
            <span className={styles.offsetAmount}>-$ {formatAmount(a.monto)}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

/** "-": the product has no sell in (or no sell out) today. */
const NoSellInOut = ({ title }) => (
  <span className={styles.muted} title={title}>
    -
  </span>
);

/**
 * The cost of the purchase lot the next sale takes its sell in from (FIFO),
 * with its discount per unit and the units left of the lot in the tooltip.
 */
function SellInCost({ sellIn }) {
  if (!sellIn) return <NoSellInOut title="Sin sell in vigente" />;
  const detalle = `Descuento por unidad: $ ${formatAmount(sellIn.descuento_unit)}\nUnidades restantes del lote: ${sellIn.unidades_restantes}`;
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
function SellInOutMarkup({ row, sellInOut }) {
  if (!sellInOut) return <NoSellInOut title="Sin sell in ni sell out" />;
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
 * ml_metricas.ver_ganancia), its cost in ARS and its cost with offset. A USD
 * cost is converted with the current rate (`rate`, venta) and keeps its
 * original amount beside it; the cost with offset uses that same rate.
 * Beside them, the cost with sell in and the sell out per unit, as the
 * backend computes them (`sell_in_out`).
 */
function ProductFacts({ product, showCost, isUsd, needsRate, rate, offsets, costo }) {

  let cost = <Empty />;
  if (isUsd) {
    const original = `USD ${formatAmount(product.costo)}`;
    if (rate === undefined) cost = original;
    else if (rate === null) cost = `${original} (sin tipo de cambio)`;
    else cost = `$ ${formatAmount(product.costo * rate)} (${original} × ${formatAmount(rate)})`;
  } else if (!isBlank(product.costo_ars ?? product.costo)) {
    cost = `$ ${formatAmount(product.costo_ars ?? product.costo)}`;
  }

  return (
    <dl className={styles.facts} role="group" aria-label="Referencias del producto">
      {showCost && (
        <>
          <div className={styles.fact}>
            <dt className={styles.factLabel}>Costo</dt>
            <dd className={styles.factValue}>{cost}</dd>
          </div>
          <div className={styles.fact}>
            <dt className={styles.factLabel}>Costo con offset</dt>
            <dd className={styles.factValue}>
              <OffsetCost product={product} offsets={offsets} needsRate={needsRate} rate={rate} costo={costo} />
            </dd>
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
  );
}

function PriceRow({ row, product, costo, showCost, editable, canEdit, editing, saving, onStart, onChange, onToggleMode, onSave, onCancel }) {
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
    <tr className={styles.row} data-editing={isEditing ? '' : undefined}>
      <th scope="row" className={styles.label} title={row.short && row.label} aria-label={row.short && row.label}>
        {row.short ?? row.label}
      </th>
      <td className={styles.price}>
        {isEditing ? (
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
        ) : isBlank(price) ? (
          <Empty />
        ) : (
          `$ ${formatAmount(price)}`
        )}
      </td>
      <td className={styles.markup} data-col="markup" data-negative={!isBlank(markup) && Number(markup) < 0 ? '' : undefined}>
        <MarkupChip value={markup} />
      </td>
      {showCost && (
        <td className={styles.markup} data-col="markup-offset">
          <MarkupChip value={markupConOffset(markup, costo)} />
        </td>
      )}
      {showCost && (
        <td className={styles.markup} data-col="markup-sell-in-out">
          <SellInOutMarkup row={row} sellInOut={product.sell_in_out} />
        </td>
      )}
      {editable && (
        <td className={styles.actions}>
          {isEditing ? (
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
          ) : (
            canEdit && (
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
            )
          )}
        </td>
      )}
    </tr>
  );
}

/**
 * The prices of ONE product (ML list and PVP, clásica and instalments) with
 * their markups, then its rebate, best offer and web transferencia
 * (ProductToggles), as `GET /productos/{item_id}` stores them. It needs only the
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
 */
export default function ProductPrices({ productItemId, permissions, onWritten, showCost = false }) {
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
          <ProductFacts product={product} showCost={showCost} isUsd={isUsd} needsRate={needsRate} rate={rate} offsets={offsets} costo={costo} />
          {editable && (
            <p className={styles.hint}>
              <Percent size={14} aria-hidden="true" />
              <span>Cada precio se edita por monto o al fijar su markup: el precio resultante se calcula y se confirma antes de guardarlo.</span>
            </p>
          )}
          {LISTS.map((list) => (
            <section key={list.id} className={styles.group} data-list={list.id}>
              <table className={styles.table}>
                <caption className={styles.caption}>
                  <span className={styles.captionTitle}>{list.title}</span>
                  <span className={styles.captionSub}>{list.subtitle}</span>
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Lista</th>
                    <th scope="col">Precio</th>
                    <th scope="col">Markup</th>
                    {showCost && (
                      <th scope="col" className={styles.wrapHead}>
                        Markup con offset
                      </th>
                    )}
                    {showCost && (
                      <th scope="col" className={styles.wrapHead}>
                        Markup c/ sell in/out
                      </th>
                    )}
                    {editable && (
                      <th scope="col">
                        <span className={styles.srOnly}>Acciones</span>
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {list.rows.map((row) => (
                    <PriceRow
                      key={row.id}
                      row={row}
                      product={product}
                      costo={costo}
                      showCost={showCost}
                      editable={editable}
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
                  ))}
                </tbody>
              </table>
            </section>
          ))}

          <ProductToggles
            key={productItemId}
            product={product}
            permissions={permissions}
            saving={saving}
            onSave={saveToggle}
            onInvalid={(text) => setMessage({ tone: 'error', text })}
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

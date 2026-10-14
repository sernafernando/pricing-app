import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Info, Pencil, X } from 'lucide-react';
import { preciosAPI } from '../../services/api';
import { formatPrecioInput, parsePrecioInput } from '../../utils/precioInput';
import { formatAmount } from '../../utils/ventasMlFormat';
import styles from './ProductPrices.module.css';

/**
 * The prices shown, per list, with the `ProductoResponse` columns of each
 * price and its markup. "Lista ML" is what pricing.py calls `lista_tipo=web`
 * (there are no separate web cuotas).
 *
 * To write one, `write` names the endpoint Productos uses for that cell
 * (`rapido` = /precios/set-rapido, `cuota` = /precios/set-cuota),
 * `pricelist` the list its negative-markup check asks about and `perm` the
 * `pricePermissions` flag that allows it.
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
    title: 'Lista ML',
    rows: [
      { id: 'ml-clasica', label: 'Clásica', precio: 'precio_lista_ml', markup: 'markup', pricelist: 4, write: 'rapido', listaTipo: 'web', perm: 'canEditClasica' },
      ...ML_CUOTAS.map(([cuota, pricelist]) => ({
        id: `ml-${cuota}`,
        label: `${cuota} cuotas`,
        precio: `precio_${cuota}_cuotas`,
        markup: `markup_${cuota}_cuotas`,
        pricelist,
        write: 'cuota',
        cuota,
        listaTipo: 'web',
        perm: 'canEditMlCuotas',
      })),
    ],
  },
  {
    title: 'PVP',
    rows: [
      { id: 'pvp-clasica', label: 'PVP clásica', precio: 'precio_pvp', markup: 'markup_pvp', pricelist: 12, write: 'rapido', listaTipo: 'pvp', perm: 'canEditPvp' },
      ...PVP_CUOTAS.map(([cuota, pricelist]) => ({
        id: `pvp-${cuota}`,
        label: `PVP ${cuota} cuotas`,
        precio: `precio_pvp_${cuota}_cuotas`,
        markup: `markup_pvp_${cuota}_cuotas`,
        pricelist,
        write: 'cuota',
        cuota,
        listaTipo: 'pvp',
        perm: 'canEditPvp',
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

/** What the inline warning says before a negative markup or a cleared price is saved. */
function warningText(pending) {
  const { row } = pending;
  if (pending.kind === 'zero') {
    return row.write === 'rapido'
      ? `Esto borra el precio de la lista ${row.listaTipo === 'pvp' ? 'PVP' : 'ML'} y todas sus cuotas.`
      : `Esto borra el precio de ${row.label}.`;
  }
  return `Markup negativo en ${row.label}: ${formatAmount(pending.markup)}%. El precio queda por debajo del costo más comisiones.`;
}

function writePrice(row, itemId, precio, product) {
  if (row.write === 'rapido') {
    const params = { item_id: itemId, precio, recalcular_cuotas: recalcularCuotas(product) };
    return preciosAPI.setRapido(row.listaTipo === 'pvp' ? { ...params, lista_tipo: 'pvp' } : params);
  }
  return preciosAPI.setCuota({ item_id: itemId, tipo_cuota: row.cuota, precio, lista_tipo: row.listaTipo });
}

function PriceRow({ row, product, editable, canEdit, editing, saving, onStart, onChange, onSave, onCancel }) {
  const price = product[row.precio];
  const markup = product[row.markup];
  const isEditing = editing?.id === row.id;

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
    <tr>
      <th scope="row" className={styles.label}>
        {row.label}
      </th>
      <td className={styles.price}>
        {isEditing ? (
          <input
            className={styles.input}
            type="text"
            inputMode="decimal"
            aria-label={row.label}
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
      <td className={styles.markup} data-negative={!isBlank(markup) && Number(markup) < 0 ? '' : undefined}>
        {isBlank(markup) ? <Empty /> : `${formatAmount(markup)}%`}
      </td>
      {editable && (
        <td className={styles.actions}>
          {isEditing ? (
            <>
              <button type="button" className={styles.iconButton} aria-label="Guardar" onClick={onSave} disabled={saving}>
                <Check size={14} aria-hidden="true" />
              </button>
              <button type="button" className={styles.iconButton} aria-label="Cancelar" onClick={onCancel} disabled={saving}>
                <X size={14} aria-hidden="true" />
              </button>
            </>
          ) : (
            canEdit && (
              <button type="button" className={styles.iconButton} aria-label={`Editar ${row.label}`} onClick={onStart} disabled={saving}>
                <Pencil size={14} aria-hidden="true" />
              </button>
            )
          )}
        </td>
      )}
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
 */
export default function ProductPrices({ productItemId, permissions, onWritten }) {
  const [state, setState] = useState({ status: 'loading', product: null, error: null });
  const [editing, setEditing] = useState(null);
  const [pending, setPending] = useState(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  // The product on screen: a write that finishes after a switch must not
  // re-read, report or show anything for the previous one.
  const shownItemRef = useRef(productItemId);

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

  // After a write the stored prices and markups are the backend's: read them again.
  const isShown = (itemId) => shownItemRef.current === itemId;

  const afterWrite = async (itemId) => {
    setMessage({ tone: 'ok', text: 'Precio guardado.' });
    try {
      const fresh = await load();
      if (!isShown(itemId)) return;
      setState({ status: 'ready', product: fresh, error: null });
    } catch {
      if (!isShown(itemId)) return;
      setMessage({ tone: 'error', text: 'Precio guardado, pero no se pudieron releer los precios.' });
    }
    onWritten?.();
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
      await writePrice(row, itemId, precio, product);
      if (!isShown(itemId)) return;
      setEditing(null);
      setPending(null);
      await afterWrite(itemId);
    } catch (error) {
      if (isShown(itemId)) setMessage({ tone: 'error', text: errorText(error, 'No se pudo guardar el precio.') });
    } finally {
      if (isShown(itemId)) setSaving(false);
    }
  };

  const cancel = () => {
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
          {LISTS.map((list) => (
            <table key={list.title} className={styles.table}>
              <caption className={styles.caption}>{list.title}</caption>
              <thead>
                <tr>
                  <th scope="col">Lista</th>
                  <th scope="col">Precio</th>
                  <th scope="col">Markup</th>
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
                    editable={editable}
                    canEdit={Boolean(permissions?.[row.perm])}
                    editing={editing}
                    saving={saving}
                    onStart={() => {
                      setPending(null);
                      setMessage(null);
                      setEditing({ id: row.id, value: formatPrecioInput(product[row.precio]) });
                    }}
                    onChange={(value) => {
                      // A warning confirms the value it was raised for: a new value drops it.
                      setPending(null);
                      setEditing((current) => ({ ...current, value }));
                    }}
                    onSave={() => save(row, editing.value)}
                    onCancel={cancel}
                  />
                ))}
              </tbody>
            </table>
          ))}

          {pending && (
            <div className={styles.warning} role="alert">
              <span>{warningText(pending)}</span>
              <div className={styles.warningActions}>
                <button type="button" className="btn-tesla outline sm" onClick={() => setPending(null)} disabled={saving}>
                  Cancelar
                </button>
                <button type="button" className="btn-tesla outline-subtle-danger sm" onClick={() => save(pending.row, pending.value, true)} disabled={saving}>
                  {pending.kind === 'zero' ? 'Borrar el precio' : 'Guardar de todas formas'}
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

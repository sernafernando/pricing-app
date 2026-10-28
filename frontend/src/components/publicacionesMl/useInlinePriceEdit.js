import { useCallback, useRef, useState } from 'react';
import { preciosAPI } from '../../services/api';
import { parsePrecioInput } from '../../utils/precioInput';
import { errorText, warningText, writePrice } from '../pricing/priceWrites';
import { WEB_TRANSF_DEFAULT, storedRebate, rebateWrite, webTransfWrite } from '../pricing/toggleWrites';

/**
 * The r / w / o toggles (S9): each flips one flag of the product as the panel's ProductToggles writes it, keeping
 * its stored percentage. `flag` is the flag as it stands now; `on`, the state the flip leads to.
 */
const TOGGLES = {
  rebate: (product, flag) => {
    const on = !flag;
    return {
      write: () => preciosAPI.setRebate(product.item_id, { participa_rebate: on, porcentaje_rebate: storedRebate(product) }),
      saved: on ? 'Rebate activado' : 'Rebate desactivado',
      fallback: 'No se pudo cambiar el rebate.',
    };
  },
  web: (product, flag) => {
    const on = !flag;
    const params = {
      participa: on,
      porcentaje_markup: product.porcentaje_markup_web || WEB_TRANSF_DEFAULT,
      // Omitting it resets it to false in the backend.
      preservar_porcentaje: Boolean(product.preservar_porcentaje_web),
    };
    return {
      write: () => preciosAPI.setWebTransferencia(product.item_id, params),
      saved: on ? 'Web transferencia activada' : 'Web transferencia desactivada',
      fallback: 'No se pudo cambiar web transferencia.',
    };
  },
  tarjetas: (product, flag) => {
    const on = !flag;
    return {
      write: () => preciosAPI.setOutOfCards(product.item_id, on),
      saved: on ? 'Fuera de tarjetas activado' : 'Fuera de tarjetas desactivado',
      fallback: 'No se pudo cambiar fuera de tarjetas.',
    };
  },
};
const FLAGS = { rebate: 'participa_rebate', web: 'participa_web_transferencia', tarjetas: 'out_of_cards' };
// The rebate and web transfer as their editors save them (S1): the panel's ProductToggles' writes.
const EDITS = { rebate: rebateWrite, web: webTransfWrite };

/**
 * Saves a price typed in a Publicaciones ML table cell (S11c) with the flow of the product panel and Productos:
 * an invalid value is an error, a 0 (it clears the price) and a negative markup are confirmed first, and a failed
 * markup check does not block the save. `row` is one of `LISTS`, `product` the listing's product (its `item_id` and
 * `recalcular_cuotas_auto`). `onWritten` runs after every write, for the caller to read the prices again.
 *
 * `toggle(kind, product)` flips the product's rebate ('rebate'), web transfer ('web') or "fuera de tarjetas"
 * ('tarjetas'), the r / w / o shortcuts, with the same report and re-read. `editToggle(kind, product, draft)` saves
 * the rebate ('rebate') or web transfer ('web') as its row editor left it (S1): takes part, its typed % and, for the
 * web transfer, "preservar porcentaje"; a % that is not sent is an error.
 *
 * `save`, `confirm`, `toggle` and `editToggle` resolve true when the price was written. `save` stays the same function between
 * renders (the table's columns hold it) as long as `onWritten` does.
 */
export default function useInlinePriceEdit({ onWritten } = {}) {
  const [saving, setSaving] = useState(false);
  const [pending, setPending] = useState(null);
  const [message, setMessage] = useState(null);
  // One write at a time (a typed price's markup check included): a second one started on the same figures would
  // write the same thing again.
  const busy = useRef(false);
  // The flags just written, until the prices are read again: `over` is the product object they were written over, so
  // a press before the re-read flips from what was written and a fresh read of the product wins again.
  const written = useRef(new Map());

  const refuseWhileBusy = useCallback(() => {
    if (!busy.current) return false;
    setMessage({ tone: 'error', text: 'Esperá a que termine el cambio anterior.' });
    return true;
  }, []);

  // One write: reported, and the caller re-reads after it.
  const run = useCallback(
    async ({ write, saved, fallback }) => {
      if (refuseWhileBusy()) return false;
      busy.current = true;
      setSaving(true);
      setMessage(null);
      try {
        await write();
        setPending(null);
        setMessage({ tone: 'ok', text: `${saved}.` });
        onWritten?.();
        return true;
      } catch (error) {
        setMessage({ tone: 'error', text: errorText(error, fallback) });
        return false;
      } finally {
        busy.current = false;
        setSaving(false);
      }
    },
    [refuseWhileBusy, onWritten],
  );

  const commit = useCallback(
    (row, product, precio) =>
      run({ write: () => writePrice(row, product.item_id, precio, product), saved: 'Precio guardado', fallback: 'No se pudo guardar el precio.' }),
    [run],
  );

  const toggle = useCallback(
    async (kind, product) => {
      const key = `${kind}:${product.item_id}`;
      const last = written.current.get(key);
      const flag = last?.over === product ? last.on : Boolean(product[FLAGS[kind]]);
      const done = await run(TOGGLES[kind](product, flag));
      if (done) written.current.set(key, { over: product, on: !flag });
      return done;
    },
    [run],
  );

  const editToggle = useCallback(
    async (kind, product, draft) => {
      if (refuseWhileBusy()) return false;
      const built = EDITS[kind](product, draft);
      if (built.error) {
        setMessage({ tone: 'error', text: built.error });
        return false;
      }
      const done = await run({ ...built, write: () => built.write(product.item_id) });
      // As a toggle: an r / w pressed before the re-read flips from what was saved.
      if (done) written.current.set(`${kind}:${product.item_id}`, { over: product, on: Boolean(draft.participa) });
      return done;
    },
    [refuseWhileBusy, run],
  );

  const save = useCallback(
    async (row, product, value) => {
      if (refuseWhileBusy()) return false;
      const precio = parsePrecioInput(value);
      if (precio === null) {
        setMessage({ tone: 'error', text: 'El precio debe ser un número válido mayor o igual a 0 (ej. 120.000,50).' });
        return false;
      }
      if (precio === 0) {
        setPending({ kind: 'zero', row, product, precio });
        return false;
      }
      busy.current = true;
      setSaving(true);
      // Productos asks before saving a price under cost + fees; a failed check does not block the save.
      const check = await preciosAPI.calcularMarkup({ item_id: product.item_id, precio, pricelist_id: row.pricelist }).catch(() => null);
      busy.current = false;
      const markup = check?.data?.markup;
      if (typeof markup === 'number' && markup < 0) {
        setSaving(false);
        setPending({ kind: 'negative', row, product, precio, markup });
        return false;
      }
      return commit(row, product, precio);
    },
    [refuseWhileBusy, commit],
  );

  const confirm = () => (pending ? commit(pending.row, pending.product, pending.precio) : Promise.resolve(false));
  const cancel = () => setPending(null);

  return { saving, pending, warning: pending ? warningText(pending) : null, message, save, confirm, cancel, toggle, editToggle };
}

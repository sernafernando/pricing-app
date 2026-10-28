import { useState } from 'react';
import { preciosAPI } from '../../services/api';
import { parsePrecioInput } from '../../utils/precioInput';
import { errorText, warningText, writePrice } from '../pricing/priceWrites';

/**
 * Saves a price typed in a Publicaciones ML table cell (S11c) with the flow of the product panel and Productos:
 * an invalid value is an error, a 0 (it clears the price) and a negative markup are confirmed first, and a failed
 * markup check does not block the save. `row` is one of `LISTS`, `product` the listing's product (its `item_id` and
 * `recalcular_cuotas_auto`). `onWritten` runs after every write, for the caller to read the prices again.
 *
 * `save` and `confirm` resolve true when the price was written.
 */
export default function useInlinePriceEdit({ onWritten } = {}) {
  const [saving, setSaving] = useState(false);
  const [pending, setPending] = useState(null);
  const [message, setMessage] = useState(null);

  const commit = async (row, product, precio) => {
    setSaving(true);
    setMessage(null);
    try {
      await writePrice(row, product.item_id, precio, product);
      setPending(null);
      setMessage({ tone: 'ok', text: 'Precio guardado.' });
      onWritten?.();
      return true;
    } catch (error) {
      setMessage({ tone: 'error', text: errorText(error, 'No se pudo guardar el precio.') });
      return false;
    } finally {
      setSaving(false);
    }
  };

  const save = async (row, product, value) => {
    const precio = parsePrecioInput(value);
    if (precio === null) {
      setMessage({ tone: 'error', text: 'El precio debe ser un número válido mayor o igual a 0 (ej. 120.000,50).' });
      return false;
    }
    if (precio === 0) {
      setPending({ kind: 'zero', row, product, precio });
      return false;
    }
    setSaving(true);
    // Productos asks before saving a price under cost + fees; a failed check does not block the save.
    const check = await preciosAPI.calcularMarkup({ item_id: product.item_id, precio, pricelist_id: row.pricelist }).catch(() => null);
    const markup = check?.data?.markup;
    if (typeof markup === 'number' && markup < 0) {
      setSaving(false);
      setPending({ kind: 'negative', row, product, precio, markup });
      return false;
    }
    return commit(row, product, precio);
  };

  const confirm = () => (pending ? commit(pending.row, pending.product, pending.precio) : Promise.resolve(false));
  const cancel = () => setPending(null);

  return { saving, pending, warning: pending ? warningText(pending) : null, message, save, confirm, cancel };
}

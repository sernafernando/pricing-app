import { useEffect, useId, useState } from 'react';
import { Pencil } from 'lucide-react';
import { productosPropiosAPI } from '../../../services/api';
import { Field, Fields, Section } from './PanelParts';
import ProductData from './ProductData';
import styles from './panel.module.css';

/** What to tell the operator when the save did not go through. */
function describeSaveError(error) {
  const status = error?.response?.status;
  if (status === 403) return 'No tenés permiso para editar el SKU y el EAN.';
  if (status === 422) return 'Revisá los valores: hasta 100 caracteres cada uno.';
  return 'No se pudo guardar. Probá de nuevo.';
}

function Value({ value, manual }) {
  return (
    <>
      {value}
      {manual && <span className={styles.manualTag}>manual</span>}
    </>
  );
}

function SkuValue({ product }) {
  if (product.sku != null) return <Value value={product.sku} manual={product.sku_manual} />;
  if (product.sku_candidatos.length > 1) {
    return <span className={styles.note}>{`Las publicaciones tienen SKUs distintos: ${product.sku_candidatos.join(', ')}`}</span>;
  }
  return null;
}

/** What a blank field goes back to: the SKU the linked publications share (none when they disagree), the ERP code. */
function computedValues(product) {
  const sharedSku = product.sku_candidatos.length === 1 ? product.sku_candidatos[0] : '';
  return {
    sku: product.sku_manual ? sharedSku : (product.sku ?? ''),
    ean: product.ean_manual ? (product.codigo ?? '') : (product.ean ?? ''),
  };
}

/**
 * The SKU and EAN of our own product (the ERP `item_id`), under the product panel's Resumen. The server computes them
 * (EAN: the ERP code; SKU: the one its linked publications share) unless someone typed one (`manual`).
 *
 * Editing (`can_edit`, `ml_publicaciones.editar_producto`; the server enforces it too) starts from the manual values
 * only: a blank field goes back to the computed value, shown as its placeholder, so saving without touching a field
 * never pins today's computed value. The linked publications' SKUs are offered as suggestions. Mount with
 * `key={productItemId}`.
 *
 * Below it, the product's data copied from one of its publications (`ProductData`), from the same read.
 *
 * @param {object} props
 * @param {number} props.productItemId
 * @param {object[]} [props.publications] The product's publications the panel lists (the copy's possible sources).
 */
export default function ProductIdentity({ productItemId, publications = [] }) {
  const [product, setProduct] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [form, setForm] = useState(null); // { sku, ean, status: 'editing' | 'saving', error }
  const [saved, setSaved] = useState(false);
  const [attempt, setAttempt] = useState(0); // bumped by Reintentar: loads again
  const listId = useId();

  useEffect(() => {
    let current = true;
    productosPropiosAPI
      .get(productItemId)
      .then(({ data }) => current && setProduct(data))
      .catch(() => current && setLoadError(true));
    return () => {
      current = false;
    };
  }, [productItemId, attempt]);

  const retry = () => {
    setLoadError(false);
    setAttempt((n) => n + 1);
  };

  if (loadError) {
    return (
      <Section title="Identificación">
        <div className={styles.resync}>
          <p className={styles.feedback} role="alert">
            No se pudieron cargar el SKU y el EAN.
          </p>
          <button type="button" className="btn-tesla outline sm" onClick={retry}>
            Reintentar
          </button>
        </div>
      </Section>
    );
  }
  if (!product) {
    return (
      <Section title="Identificación">
        <p className={styles.note}>Cargando SKU y EAN…</p>
      </Section>
    );
  }

  const edit = () => {
    setSaved(false);
    setForm({
      sku: product.sku_manual ? product.sku : '',
      ean: product.ean_manual ? product.ean : '',
      status: 'editing',
      error: null,
    });
  };

  const save = async (event) => {
    event.preventDefault();
    if (form.status === 'saving') return;
    setForm({ ...form, status: 'saving', error: null });
    try {
      const { data } = await productosPropiosAPI.save(productItemId, { sku: form.sku, ean: form.ean });
      setProduct(data);
      setForm(null);
      setSaved(true);
    } catch (error) {
      setForm({ ...form, status: 'editing', error: describeSaveError(error) });
    }
  };

  const computed = computedValues(product);

  return (
    <>
      <Section title="Identificación">
        {form ? (
          <form className={styles.identityForm} onSubmit={save}>
            <label className={styles.identityField}>
              <span>SKU</span>
              <input
                className={styles.identityInput}
                value={form.sku}
                placeholder={computed.sku}
                list={listId}
                maxLength={100}
                disabled={form.status === 'saving'}
                onChange={(event) => setForm({ ...form, sku: event.target.value })}
              />
            </label>
            <datalist id={listId}>
              {product.sku_candidatos.map((sku) => (
                <option key={sku} value={sku} />
              ))}
            </datalist>
            <label className={styles.identityField}>
              <span>EAN</span>
              <input
                className={styles.identityInput}
                value={form.ean}
                placeholder={computed.ean}
                maxLength={100}
                disabled={form.status === 'saving'}
                onChange={(event) => setForm({ ...form, ean: event.target.value })}
              />
            </label>
            <p className={styles.note}>Vacío: el SKU de las publicaciones y el EAN del ERP.</p>
            <div className={styles.statusConfirm}>
              <button type="submit" className="btn-tesla primary sm" disabled={form.status === 'saving'}>
                Guardar
              </button>
              <button type="button" className="btn-tesla outline sm" onClick={() => setForm(null)} disabled={form.status === 'saving'}>
                Cancelar
              </button>
            </div>
            {form.error && (
              <p className={styles.feedback} role="alert">
                {form.error}
              </p>
            )}
          </form>
        ) : (
          <>
            <Fields>
              <Field label="EAN">{product.ean != null && <Value value={product.ean} manual={product.ean_manual} />}</Field>
              <Field label="SKU">
                {(product.sku != null || product.sku_candidatos.length > 1) && <SkuValue product={product} />}
              </Field>
            </Fields>
            {product.can_edit && (
              <button type="button" className={`btn-tesla outline sm ${styles.identityEdit}`} onClick={edit}>
                <Pencil size={14} aria-hidden="true" />
                Editar
              </button>
            )}
            {saved && (
              <p className={styles.feedback} role="status">
                Guardado.
              </p>
            )}
          </>
        )}
      </Section>
      <ProductData product={product} publications={publications} onSaved={setProduct} />
    </>
  );
}

import { useState } from 'react';
import { ArrowDown, ArrowUp, X } from 'lucide-react';
import { productosPropiosAPI } from '../../../services/api';
import { apiErrorMessage } from '../../../utils/apiErrorMessage';
import styles from './panel.module.css';

// The server's limits (`productos_propios` router): titles and attribute values, and ML's limit on a description.
const MAX_TITULO_LENGTH = 255;
const MAX_ATRIBUTO_VALUE_LENGTH = 255;
const MAX_DESCRIPCION_LENGTH = 50000;

/** What to tell the operator when the save did not go through (a 409, or a 422 in words, is the server's own). */
function describeError(error) {
  const status = error?.response?.status;
  if (status === 403) return 'No tenés permiso para editar los datos del producto.';
  if (status === 409) return apiErrorMessage(error, 'No se pudieron guardar los datos. Probá de nuevo.');
  if (status === 422) return apiErrorMessage(error, 'Revisá los datos: el título y cada valor, hasta 255 caracteres.');
  return 'No se pudieron guardar los datos. Probá de nuevo.';
}

/**
 * Why the form cannot be saved as it is, or null: the server rejects a blank title or attribute value, and keeps
 * pictures by their ML id (a picture copied without one can only be removed).
 */
function formError(form) {
  if (!form.titulo.trim()) return 'El título no puede quedar vacío.';
  const sinId = form.fotos.findIndex((foto) => !foto.id);
  if (sinId >= 0) return `La foto ${sinId + 1} vino de ML sin identificador y no se puede guardar: quitala.`;
  const blank = form.atributos.find((atributo) => !atributo.value_name.trim());
  return blank ? `Completá el valor de ${blank.name ?? blank.id} o quitalo.` : null;
}

/** `list` with the entry at `index` swapped with the one `offset` away. */
function moved(list, index, offset) {
  const next = [...list];
  [next[index], next[index + offset]] = [next[index + offset], next[index]];
  return next;
}

/**
 * Edit the product's copied data and save it whole (`PUT /productos-propios/{item_id}/datos`): the title, the
 * description (blank saves none), the copied pictures (remove, reorder; no new ones) and the copied attributes (edit
 * the value, remove). Nothing outside the copy can be added: the server only takes what was copied.
 *
 * @param {object} props
 * @param {number} props.itemId
 * @param {object} props.datos The copy as the server last answered it.
 * @param {(product: object) => void} props.onSaved Receives the product as the server answered the save.
 * @param {() => void} props.onCancel
 */
export default function ProductDataForm({ itemId, datos, onSaved, onCancel }) {
  const [form, setForm] = useState({
    titulo: datos.titulo ?? '',
    descripcion: datos.descripcion ?? '',
    fotos: datos.fotos,
    atributos: datos.atributos,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const change = (fields) => {
    setForm({ ...form, ...fields });
    setError(null);
  };

  const setAtributo = (index, valueName) =>
    change({ atributos: form.atributos.map((atributo, i) => (i === index ? { ...atributo, value_name: valueName } : atributo)) });

  const save = async (event) => {
    event.preventDefault();
    if (saving) return; // a second click before the re-render
    const invalid = formError(form);
    if (invalid) {
      setError(invalid);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const { data } = await productosPropiosAPI.saveDatos(itemId, {
        titulo: form.titulo,
        descripcion: form.descripcion.trim() ? form.descripcion : null,
        fotos: form.fotos.map((foto) => foto.id),
        atributos: form.atributos.map((atributo) => ({ id: atributo.id, value_name: atributo.value_name })),
      });
      onSaved(data);
    } catch (saveError) {
      setSaving(false);
      setError(describeError(saveError));
    }
  };

  return (
    <form className={styles.identityForm} onSubmit={save}>
      <label className={styles.identityField}>
        <span>Título</span>
        <input
          className={`${styles.identityInput} ${styles.wideInput}`}
          value={form.titulo}
          maxLength={MAX_TITULO_LENGTH}
          disabled={saving}
          onChange={(event) => change({ titulo: event.target.value })}
        />
      </label>
      <label className={styles.identityField}>
        <span>Descripción</span>
        <textarea
          className={`${styles.identityInput} ${styles.wideInput} ${styles.descriptionInput}`}
          value={form.descripcion}
          maxLength={MAX_DESCRIPCION_LENGTH}
          rows={6}
          disabled={saving}
          onChange={(event) => change({ descripcion: event.target.value })}
        />
      </label>

      <h4 className={styles.subTitle}>Fotos</h4>
      {form.fotos.length > 0 ? (
        <ul className={`${styles.pictures} ${styles.picturesEdit}`}>
          {form.fotos.map((foto, index) => {
            const n = index + 1;
            return (
              <li key={foto.id ?? foto.url} className={styles.pictureEdit}>
                <img src={foto.url} alt={`Foto ${n}`} className={styles.picture} loading="lazy" />
                <div className={styles.pictureActions}>
                  <button
                    type="button"
                    className="btn-tesla outline-subtle-primary icon-only sm"
                    aria-label={`Subir foto ${n}`}
                    disabled={saving || index === 0}
                    onClick={() => change({ fotos: moved(form.fotos, index, -1) })}
                  >
                    <ArrowUp size={14} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="btn-tesla outline-subtle-primary icon-only sm"
                    aria-label={`Bajar foto ${n}`}
                    disabled={saving || index === form.fotos.length - 1}
                    onClick={() => change({ fotos: moved(form.fotos, index, 1) })}
                  >
                    <ArrowDown size={14} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="btn-tesla outline-subtle-danger icon-only sm"
                    aria-label={`Quitar foto ${n}`}
                    disabled={saving}
                    onClick={() => change({ fotos: form.fotos.filter((_, i) => i !== index) })}
                  >
                    <X size={14} aria-hidden="true" />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className={styles.note}>Sin fotos.</p>
      )}

      <h4 className={styles.subTitle}>Atributos</h4>
      {form.atributos.length > 0 ? (
        form.atributos.map((atributo, index) => (
          <div key={atributo.id} className={styles.attributeEdit}>
            <label className={styles.identityField}>
              <span>{atributo.name ?? atributo.id}</span>
              <input
                className={styles.identityInput}
                value={atributo.value_name}
                maxLength={MAX_ATRIBUTO_VALUE_LENGTH}
                disabled={saving}
                onChange={(event) => setAtributo(index, event.target.value)}
              />
            </label>
            <button
              type="button"
              className="btn-tesla outline-subtle-danger icon-only sm"
              aria-label={`Quitar ${atributo.name ?? atributo.id}`}
              disabled={saving}
              onClick={() => change({ atributos: form.atributos.filter((_, i) => i !== index) })}
            >
              <X size={14} aria-hidden="true" />
            </button>
          </div>
        ))
      ) : (
        <p className={styles.note}>Sin atributos.</p>
      )}

      <div className={styles.statusConfirm}>
        <button type="submit" className="btn-tesla primary sm" disabled={saving}>
          Guardar
        </button>
        <button type="button" className="btn-tesla outline sm" onClick={onCancel} disabled={saving}>
          Cancelar
        </button>
      </div>
      {error && (
        <p className={styles.feedback} role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

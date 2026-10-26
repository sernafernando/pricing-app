import { useId, useState } from 'react';
import { Copy, Pencil } from 'lucide-react';
import { productosPropiosAPI } from '../../../services/api';
import { isDeletedPublication } from '../publicationStatus';
import { Field, Fields, Section } from './PanelParts';
import ProductDataForm from './ProductDataForm';
import { date } from './format';
import styles from './panel.module.css';

/** What to tell the operator when the copy did not go through (a 409 is the server's own reason). */
function describeError(error) {
  const status = error?.response?.status;
  if (status === 403) return 'No tenés permiso para copiar los datos del producto.';
  if (status === 409 && error.response.data?.detail) return error.response.data.detail;
  return 'No se pudieron copiar los datos. Probá de nuevo.';
}

/** The publications a copy may come from: the live ones (the server checks it again). */
const liveOnly = (publications) =>
  publications.filter((publication) => !publication.gone && !isDeletedPublication(publication.status, publication.sub_status));

function Copied({ datos }) {
  return (
    <>
      <p className={styles.note}>{`Copiados de ${datos.fuente_mla}${datos.copiado_at ? ` el ${date(datos.copiado_at)}` : ''}`}</p>
      <Fields>
        <Field label="Título">{datos.titulo}</Field>
      </Fields>
      <h4 className={styles.subTitle}>Descripción</h4>
      {datos.descripcion ? <p className={styles.description}>{datos.descripcion}</p> : <p className={styles.note}>Sin descripción.</p>}
      <h4 className={styles.subTitle}>Fotos</h4>
      {datos.fotos.length > 0 ? (
        <ul className={styles.pictures}>
          {datos.fotos.map((foto, index) => (
            <li key={foto.id ?? foto.url}>
              <img src={foto.url} alt={`Foto ${index + 1}`} className={styles.picture} loading="lazy" />
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.note}>Sin fotos.</p>
      )}
      <h4 className={styles.subTitle}>Atributos</h4>
      {datos.atributos.length > 0 ? (
        <Fields>
          {datos.atributos.map((atributo) => (
            <Field key={atributo.id} label={atributo.name ?? atributo.id}>
              {atributo.value_name}
            </Field>
          ))}
        </Fields>
      ) : (
        <p className={styles.note}>Sin atributos.</p>
      )}
    </>
  );
}

/**
 * The product's data copied from one of its publications (T7): title, description, pictures and attributes, and
 * the MLA they came from. A copy, not a live link: later changes of the publication do not reach it.
 *
 * With `can_edit` (`ml_publicaciones.editar_producto`; the server enforces it too) the operator picks the
 * publication to copy from among the product's live publications the panel lists (`publications`). Replacing an
 * earlier copy asks first: it also drops what was edited on it. Once copied, the data can be edited
 * (`ProductDataForm`).
 *
 * @param {object} props
 * @param {object} props.product The read of `GET /productos-propios/{item_id}`.
 * @param {object[]} props.publications The product's publications as the panel lists them.
 * @param {(product: object) => void} props.onSaved Receives the product as the server answered the copy or the edit.
 */
export default function ProductData({ product, publications, onSaved }) {
  const datos = product.datos;
  // idle: showing the copy; editing: the form open; choosing: the picker open; confirming: replacing a copy;
  // sending: the copy request is out
  const [state, setState] = useState({ phase: datos ? 'idle' : 'choosing', mla: '', error: null });
  const [saved, setSaved] = useState(false);
  const selectId = useId();
  const candidates = liveOnly(publications);

  const send = async () => {
    if (state.phase === 'sending') return; // a second click before the re-render
    setState({ ...state, phase: 'sending', error: null });
    setSaved(false);
    try {
      const { data } = await productosPropiosAPI.chooseSource(product.item_id, state.mla);
      setState({ phase: 'idle', mla: '', error: null });
      onSaved(data);
    } catch (error) {
      setState({ ...state, phase: 'choosing', error: describeError(error) });
    }
  };

  const copy = () => (datos ? setState({ ...state, phase: 'confirming', error: null }) : send());
  const cancel = () => setState({ phase: datos ? 'idle' : 'choosing', mla: '', error: null });
  const picking = product.can_edit && ['choosing', 'confirming', 'sending'].includes(state.phase);

  const edited = (data) => {
    setState({ phase: 'idle', mla: '', error: null });
    setSaved(true);
    onSaved(data);
  };

  if (product.can_edit && datos && state.phase === 'editing') {
    return (
      <Section title="Datos del producto">
        <ProductDataForm itemId={product.item_id} datos={datos} onSaved={edited} onCancel={cancel} />
      </Section>
    );
  }

  return (
    <Section title="Datos del producto">
      {datos ? <Copied datos={datos} /> : <p className={styles.note}>Todavía no se copiaron datos de ninguna publicación.</p>}

      {picking && candidates.length === 0 && (
        <p className={styles.note}>No hay publicaciones vigentes en la lista para copiar. Probá cambiando los filtros.</p>
      )}

      {picking && candidates.length > 0 && (
        <div className={styles.identityForm}>
          <label className={styles.identityField} htmlFor={selectId}>
            <span>Publicación de origen</span>
          </label>
          <select
            id={selectId}
            className={styles.identityInput}
            value={state.mla}
            disabled={state.phase !== 'choosing'}
            onChange={(event) => setState({ ...state, mla: event.target.value, error: null })}
          >
            <option value="">Elegí una publicación…</option>
            {candidates.map((publication) => (
              <option key={publication.item_id} value={publication.item_id}>
                {`${publication.item_id} · ${publication.title ?? 'Sin título'}`}
              </option>
            ))}
          </select>
          {state.phase === 'confirming' ? (
            <div className={styles.statusConfirm}>
              <span>{`Se reemplazan los datos copiados y lo editado. ¿Copiar de ${state.mla}?`}</span>
              <button type="button" className="btn-tesla primary sm" onClick={send}>
                Confirmar
              </button>
              <button type="button" className="btn-tesla outline sm" onClick={cancel}>
                Cancelar
              </button>
            </div>
          ) : (
            <div className={styles.statusConfirm}>
              <button type="button" className="btn-tesla primary sm" onClick={copy} disabled={!state.mla || state.phase === 'sending'}>
                <Copy size={14} aria-hidden="true" />
                Copiar datos
              </button>
              {datos && (
                <button type="button" className="btn-tesla outline sm" onClick={cancel} disabled={state.phase === 'sending'}>
                  Cancelar
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {state.error && (
        <p className={styles.feedback} role="alert">
          {state.error}
        </p>
      )}

      {product.can_edit && datos && state.phase === 'idle' && (
        <div className={styles.statusConfirm}>
          <button
            type="button"
            className="btn-tesla outline sm"
            onClick={() => {
              setSaved(false);
              setState({ phase: 'editing', mla: '', error: null });
            }}
          >
            <Pencil size={14} aria-hidden="true" />
            Editar datos
          </button>
          <button
            type="button"
            className="btn-tesla outline sm"
            onClick={() => {
              setSaved(false);
              setState({ phase: 'choosing', mla: '', error: null });
            }}
          >
            <Copy size={14} aria-hidden="true" />
            Cambiar publicación
          </button>
        </div>
      )}

      {saved && state.phase === 'idle' && (
        <p className={styles.feedback} role="status">
          Guardado.
        </p>
      )}
    </Section>
  );
}

import { useEffect, useState } from 'react';
import { Pencil } from 'lucide-react';
import { mlItemOverridesAPI } from '../../../services/api';
import DataFields from './DataFields';
import { Section } from './PanelParts';
import PublicationDataForm from './PublicationDataForm';
import PushToMl from './PushToMl';
import { date } from './format';
import styles from './panel.module.css';

// The override's fields, in the order the operator reads them.
const FIELD_LABELS = [
  ['titulo', 'título'],
  ['descripcion', 'descripción'],
  ['fotos', 'fotos'],
  ['atributos', 'atributos'],
];

/** "título, fotos y atributos": the fields the override sets (a null one follows ML). */
function overriddenFields(override) {
  const names = FIELD_LABELS.filter(([field]) => override[field] !== null).map(([, name]) => name);
  return names.length > 1 ? `${names.slice(0, -1).join(', ')} y ${names.at(-1)}` : names[0];
}

/**
 * The publication's data (T8b): title, description, pictures and attributes. Someone may override them here, field by
 * field, without changing ML; then the panel shows the data that applies (the override, else ML's) and, apart, the
 * original ML has (`GET /ml-item-overrides/{mla}`).
 *
 * With `can_edit` (`ml_publicaciones.editar_publicacion`; the server enforces it too) "Editar datos" opens the form
 * (`PublicationDataForm`); a deleted publication reads but cannot be edited. With an override, "Actualizar en ML"
 * sends it to Mercado Libre (`PushToMl`), a separate step; the publication is read again after it.
 *
 * @param {object} props
 * @param {string} props.itemId The MLA.
 */
export default function DatosTab({ itemId }) {
  // Each tagged with its MLA: the panel keeps this tab mounted when another publication is selected.
  const [loaded, setLoaded] = useState(null); // { itemId, data }
  const [failedFor, setFailedFor] = useState(null);
  const [attempt, setAttempt] = useState(0); // bumped by Reintentar: loads again
  const [editingFor, setEditingFor] = useState(null); // the MLA whose form is open
  const [savedFor, setSavedFor] = useState(null); // the MLA just saved
  const [pushingFor, setPushingFor] = useState(null); // the MLA whose push is out: no edit until it answers

  useEffect(() => {
    let current = true;
    mlItemOverridesAPI
      .get(itemId)
      .then(({ data }) => {
        if (!current) return;
        setLoaded({ itemId, data });
        setFailedFor(null); // an earlier failure of this MLA is over
      })
      .catch(() => current && setFailedFor(itemId));
    return () => {
      current = false;
    };
  }, [itemId, attempt]);

  const retry = () => {
    setFailedFor(null);
    setAttempt((n) => n + 1);
  };

  const read = loaded?.itemId === itemId ? loaded.data : null;

  if (failedFor === itemId) {
    return (
      <Section title="Datos de la publicación">
        <div className={styles.resync}>
          <p className={styles.feedback} role="alert">
            No se pudieron cargar los datos de la publicación.
          </p>
          <button type="button" className="btn-tesla outline sm" onClick={retry}>
            Reintentar
          </button>
        </div>
      </Section>
    );
  }
  if (!read) {
    return (
      <Section title="Datos de la publicación">
        <p className={styles.note}>Cargando datos…</p>
      </Section>
    );
  }

  if (read.can_edit && read.editable && editingFor === itemId) {
    const saved = (data) => {
      setLoaded({ itemId, data });
      setEditingFor(null);
      setSavedFor(itemId);
    };
    return (
      <Section title="Editar datos de la publicación">
        <p className={styles.note}>Se guardan acá, sin cambiar la publicación en Mercado Libre.</p>
        <PublicationDataForm itemId={itemId} aplicado={read.aplicado} original={read.original} onSaved={saved} onCancel={() => setEditingFor(null)} />
      </Section>
    );
  }

  const actions = (
    <>
      {read.can_edit && !read.editable && <p className={styles.note}>La publicación está eliminada: sus datos no se pueden editar.</p>}
      {read.can_edit && read.editable && pushingFor !== itemId && (
        <div className={styles.statusConfirm}>
          <button
            type="button"
            className="btn-tesla outline sm"
            onClick={() => {
              setSavedFor(null);
              setEditingFor(itemId);
            }}
          >
            <Pencil size={14} aria-hidden="true" />
            Editar datos
          </button>
        </div>
      )}
      {read.can_edit && read.editable && (
        // Mounted without an override too, so a result stays when the re-read after a push finds the override gone.
        <PushToMl
          key={itemId}
          itemId={itemId}
          canPush={Boolean(read.override)}
          replacesPictures={read.override?.fotos != null}
          onSendingChange={(sending) => setPushingFor((current) => (sending ? itemId : current === itemId ? null : current))}
          onPushed={() => setAttempt((n) => n + 1)}
        />
      )}
      {savedFor === itemId && (
        <p className={styles.feedback} role="status">
          Guardado. No se cambió nada en Mercado Libre.
        </p>
      )}
    </>
  );

  if (!read.override) {
    return (
      <Section title="Datos de la publicación">
        <p className={styles.note}>Sin cambios locales: se usan los datos de Mercado Libre.</p>
        <DataFields datos={read.original} />
        {actions}
      </Section>
    );
  }

  return (
    <>
      <Section title="Datos que se usan">
        <p className={styles.note}>
          {`Sobrescritos${read.updated_at ? ` el ${date(read.updated_at)}` : ''}: ${overriddenFields(read.override)}. Guardar no los cambia en Mercado Libre.`}
        </p>
        <DataFields datos={read.aplicado} />
        {actions}
      </Section>
      <Section title="Original en Mercado Libre">
        <DataFields datos={read.original} />
      </Section>
    </>
  );
}

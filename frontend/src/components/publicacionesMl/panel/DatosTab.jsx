import { useEffect, useState } from 'react';
import { mlItemOverridesAPI } from '../../../services/api';
import DataFields from './DataFields';
import { Section } from './PanelParts';
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
 * @param {object} props
 * @param {string} props.itemId The MLA.
 */
export default function DatosTab({ itemId }) {
  // Each tagged with its MLA: the panel keeps this tab mounted when another publication is selected.
  const [loaded, setLoaded] = useState(null); // { itemId, data }
  const [failedFor, setFailedFor] = useState(null);
  const [attempt, setAttempt] = useState(0); // bumped by Reintentar: loads again

  useEffect(() => {
    let current = true;
    mlItemOverridesAPI
      .get(itemId)
      .then(({ data }) => current && setLoaded({ itemId, data }))
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

  if (!read.override) {
    return (
      <Section title="Datos de la publicación">
        <p className={styles.note}>Sin cambios locales: se usan los datos de Mercado Libre.</p>
        <DataFields datos={read.original} />
      </Section>
    );
  }

  return (
    <>
      <Section title="Datos que se usan">
        <p className={styles.note}>
          {`Sobrescritos${read.updated_at ? ` el ${date(read.updated_at)}` : ''}: ${overriddenFields(read.override)}. No se cambian en Mercado Libre.`}
        </p>
        <DataFields datos={read.aplicado} />
      </Section>
      <Section title="Original en Mercado Libre">
        <DataFields datos={read.original} />
      </Section>
    </>
  );
}

import { useEffect, useState } from 'react';
import { ArrowRight, Lock, Inbox } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { ejemplosAPI } from '../services/api';
import styles from './TriageEjemplos.module.css';

const CAMPOS = [
  { value: 'severidad', label: 'Severidad' },
  { value: 'urgencia', label: 'Urgencia' },
];

// Accent by corrected value — direction B row anatomy, PR5b. All colors are
// design tokens (`--cf-accent-*`) so they adapt across themes — no literal
// hex, matching the rest of the CSS module (`.rowError`, `.counterDot`).
function accentFor(valorCorregido) {
  const v = (valorCorregido || '').toLowerCase();
  if (v === 'critica' || v === 'inmediata') {
    return { border: 'var(--cf-accent-red)', bg: 'var(--cf-accent-red)', color: 'var(--cf-accent-red)' };
  }
  if (v === 'mayor' || v === 'alta') {
    return { border: 'var(--cf-accent-orange)', bg: 'var(--cf-accent-orange)', color: 'var(--cf-accent-orange)' };
  }
  if (v === 'trivial' || v === 'baja') {
    return { border: 'var(--cf-text-tertiary)', bg: 'var(--cf-text-tertiary)', color: 'var(--cf-text-tertiary)' };
  }
  return { border: 'var(--cf-accent-blue)', bg: 'var(--cf-accent-blue)', color: 'var(--cf-accent-blue)' };
}

function formatFecha(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const dias = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (dias <= 0) return 'hoy';
  if (dias === 1) return 'ayer';
  return `hace ${dias} días`;
}

function EjemploRow({ ejemplo, onToggle, error }) {
  const accent = accentFor(ejemplo.valor_corregido);
  const rowStyle = ejemplo.active
    ? { '--rowAccent': accent.border }
    : { '--rowAccent': 'var(--cf-border-default)' };
  const pillStyle = ejemplo.active
    ? { '--pillBg': accent.bg, '--pillColor': accent.color }
    : {};

  return (
    <div
      data-testid="ejemplo-row"
      className={`${styles.row} ${!ejemplo.active ? styles.rowInactive : ''}`}
      style={rowStyle}
    >
      <div className={styles.rowMain}>
        <p className={styles.rowText}>{ejemplo.texto}</p>
        <div className={styles.rowMeta}>
          <span className={styles.metaLabel}>IA</span>
          <span className={styles.valorTachado}>{ejemplo.valor_ia}</span>
          <ArrowRight size={12} />
          <span className={styles.metaLabel}>Humano</span>
          <span className={styles.pill} style={pillStyle}>{ejemplo.valor_corregido}</span>
          <span>·</span>
          <span className={styles.rowDate}>{formatFecha(ejemplo.created_at)}</span>
        </div>
        {error && <p className={styles.rowError}>{error}</p>}
      </div>

      <div className={styles.toggleWrap}>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={ejemplo.active}
            aria-label={ejemplo.active ? 'Desactivar ejemplo' : 'Activar ejemplo'}
            onChange={(e) => onToggle(ejemplo, e.target.checked)}
          />
          <span className={styles.toggleTrack} />
        </label>
        <span className={ejemplo.active ? `${styles.toggleLabel} ${styles.toggleLabelOn}` : `${styles.toggleLabel} ${styles.toggleLabelOff}`}>
          {ejemplo.active ? 'Influye' : 'Ignorado'}
        </span>
      </div>
    </div>
  );
}

export default function TriageEjemplos() {
  const { tienePermiso, loading: permLoading } = usePermisos();
  const [campo, setCampo] = useState('severidad');
  const [ejemplos, setEjemplos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [errores, setErrores] = useState({});
  // Corpus-wide check (no `campo` filter) — distinguishes "nothing captured
  // anywhere yet" from "this campo's tab is empty, try the other one".
  const [corpusVacio, setCorpusVacio] = useState(null);
  const [errorCarga, setErrorCarga] = useState(null);

  const tienePermisoEjemplos = tienePermiso('tickets.triage.ejemplos');

  useEffect(() => {
    if (!tienePermisoEjemplos) return;
    let cancelado = false;
    ejemplosAPI
      .listar(undefined, { limit: 1 })
      .then(({ data }) => {
        if (!cancelado) setCorpusVacio(data.length === 0);
      })
      .catch(() => {
        // Non-fatal: only feeds which of the two empty-state copies to
        // show. Fall back to the "empty corpus" copy (not `false`) so an
        // empty-and-unerrored main list still renders SOME explanation
        // instead of a blank gap between the tabs and the footnote.
        if (!cancelado) setCorpusVacio(true);
      });
    return () => {
      cancelado = true;
    };
  }, [tienePermisoEjemplos]);

  useEffect(() => {
    if (!tienePermisoEjemplos) return;
    let cancelado = false;
    setLoading(true);
    setErrorCarga(null);
    ejemplosAPI
      .listar(campo, { limit: 200 })
      .then(({ data }) => {
        if (!cancelado) setEjemplos(data);
      })
      .catch((err) => {
        if (!cancelado) {
          setEjemplos([]);
          setErrorCarga(err?.response?.data?.detail || 'No se pudieron cargar los ejemplos');
        }
      })
      .finally(() => {
        if (!cancelado) setLoading(false);
      });
    return () => {
      cancelado = true;
    };
  }, [campo, tienePermisoEjemplos]);

  if (permLoading) return null;

  if (!tienePermisoEjemplos) {
    return (
      <div className={styles.container}>
        <div className={styles.denied}>
          <Lock size={32} />
          <p>No tenés permisos para acceder a la curación de ejemplos de triage.</p>
        </div>
      </div>
    );
  }

  const handleToggle = async (ejemplo, nuevoActive) => {
    setErrores((prev) => ({ ...prev, [ejemplo.id]: null }));
    try {
      const { data } = await ejemplosAPI.toggle(ejemplo.id, nuevoActive);
      setEjemplos((prev) => prev.map((e) => (e.id === ejemplo.id ? data : e)));
    } catch (err) {
      const detail = err?.response?.data?.detail || 'No se pudo actualizar el ejemplo';
      setErrores((prev) => ({ ...prev, [ejemplo.id]: detail }));
    }
  };

  const total = ejemplos.length;
  const activos = ejemplos.filter((e) => e.active).length;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>Ejemplos de corrección de triage</h1>
        <p className={styles.subtitle}>
          Cada vez que corregís la severidad o la urgencia que propuso la IA, esa corrección
          queda guardada acá y pasa a orientar las clasificaciones siguientes.
        </p>
      </div>

      <div className={styles.toolbar}>
        <div className={styles.filterTabs}>
          {CAMPOS.map((c) => (
            <button
              key={c.value}
              type="button"
              className={`${styles.filterTab} ${campo === c.value ? styles.filterTabActive : ''}`}
              onClick={() => setCampo(c.value)}
            >
              {c.label}
            </button>
          ))}
        </div>
        {total > 0 && (
          <div className={styles.counter}>
            <span className={styles.counterDot} />
            <span>{activos} de {total} influyen en el triage</span>
          </div>
        )}
      </div>

      {loading && <p className={styles.footnote}>Cargando ejemplos…</p>}

      {!loading && errorCarga && (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>No se pudieron cargar los ejemplos</p>
          <p className={styles.emptyText}>{errorCarga}</p>
        </div>
      )}

      {!loading && !errorCarga && total === 0 && corpusVacio && (
        <div className={styles.empty}>
          <Inbox size={48} className={styles.emptyIcon} />
          <p className={styles.emptyTitle}>Todavía no hay ejemplos</p>
          <p className={styles.emptyText}>
            Cada vez que corregís la severidad o la urgencia que propuso la IA, esa corrección
            queda guardada acá y pasa a orientar las clasificaciones siguientes.
          </p>
        </div>
      )}

      {!loading && !errorCarga && total === 0 && corpusVacio === false && (
        <div className={styles.empty}>
          <Inbox size={48} className={styles.emptyIcon} />
          <p className={styles.emptyTitle}>No hay ejemplos para este campo</p>
          <p className={styles.emptyText}>
            No hay ejemplos guardados para {CAMPOS.find((c) => c.value === campo)?.label} todavía.
            Probá con {CAMPOS.find((c) => c.value !== campo)?.label}.
          </p>
        </div>
      )}

      {!loading && total > 0 && (
        <div className={styles.list}>
          {ejemplos.map((ejemplo) => (
            <EjemploRow
              key={ejemplo.id}
              ejemplo={ejemplo}
              onToggle={handleToggle}
              error={errores[ejemplo.id]}
            />
          ))}
        </div>
      )}

      <p className={styles.footnote}>
        Apagar un ejemplo lo excluye de la próxima clasificación, no borra nada — se puede
        volver a prender en cualquier momento.
      </p>
    </div>
  );
}

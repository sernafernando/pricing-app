import { useEffect, useState } from 'react';
import { ArrowRight, Lock, Inbox } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { ejemplosAPI } from '../services/api';
import styles from './TriageEjemplos.module.css';

const CAMPOS = [
  { value: 'severidad', label: 'Severidad' },
  { value: 'urgencia', label: 'Urgencia' },
];

// Accent by corrected value — direction B row anatomy, PR5b.
function accentFor(valorCorregido) {
  const v = (valorCorregido || '').toLowerCase();
  if (v === 'critica' || v === 'inmediata') {
    return { border: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)', color: '#ef4444' };
  }
  if (v === 'mayor' || v === 'alta') {
    return { border: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b' };
  }
  if (v === 'trivial' || v === 'baja') {
    return { border: 'var(--cf-text-tertiary)', bg: 'rgba(100, 116, 139, 0.15)', color: 'var(--cf-text-tertiary)' };
  }
  return { border: '#3b82f6', bg: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' };
}

function formatFecha(iso) {
  try {
    const d = new Date(iso);
    const dias = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (dias <= 0) return 'hoy';
    if (dias === 1) return 'ayer';
    return `hace ${dias} días`;
  } catch {
    return '';
  }
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

  const tienePermisoEjemplos = tienePermiso('tickets.triage.ejemplos');

  useEffect(() => {
    if (!tienePermisoEjemplos) return;
    let cancelado = false;
    ejemplosAPI.listar(undefined, { limit: 1 }).then(({ data }) => {
      if (!cancelado) setCorpusVacio(data.length === 0);
    });
    return () => {
      cancelado = true;
    };
  }, [tienePermisoEjemplos]);

  useEffect(() => {
    if (!tienePermisoEjemplos) return;
    let cancelado = false;
    setLoading(true);
    ejemplosAPI
      .listar(campo, { limit: 200 })
      .then(({ data }) => {
        if (!cancelado) setEjemplos(data);
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

      {!loading && total === 0 && corpusVacio && (
        <div className={styles.empty}>
          <Inbox size={48} className={styles.emptyIcon} />
          <p className={styles.emptyTitle}>Todavía no hay ejemplos</p>
          <p className={styles.emptyText}>
            Cada vez que corregís la severidad o la urgencia que propuso la IA, esa corrección
            queda guardada acá y pasa a orientar las clasificaciones siguientes.
          </p>
        </div>
      )}

      {!loading && total === 0 && corpusVacio === false && (
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

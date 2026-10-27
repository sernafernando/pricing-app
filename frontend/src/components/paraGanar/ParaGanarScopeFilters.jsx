import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown, X } from 'lucide-react';
import api from '../../services/api';
import styles from './ParaGanarScopeFilters.module.css';

/**
 * Shared marca / subcategoría / PM scope filters for Advisor and Criterios.
 * Options come from GET /para-ganar/alcance-opciones (sandbox-safe).
 */

function MultiSelect({
  label,
  options,
  selected,
  onChange,
  getKey,
  getLabel,
  emptyHint,
  disabled,
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const listId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const toggle = (key) => {
    if (selected.includes(key)) {
      onChange(selected.filter((item) => item !== key));
    } else {
      onChange([...selected, key]);
    }
  };

  const count = selected.length;
  const buttonLabel = count > 0 ? `${label} (${count})` : label;

  return (
    <div className={styles.selectWrap} ref={rootRef}>
      <button
        type="button"
        className={`${styles.selectBtn} ${count > 0 ? styles.selectBtnActive : ''}`}
        aria-expanded={open}
        aria-controls={listId}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
      >
        <span>{buttonLabel}</span>
        <ChevronDown size={14} aria-hidden />
      </button>
      {open && (
        <div className={styles.dropdown} id={listId} role="listbox" aria-label={label}>
          {options.length === 0 ? (
            <p className={styles.emptyHint}>{emptyHint}</p>
          ) : (
            <ul className={styles.optionList}>
              {options.map((option) => {
                const key = getKey(option);
                const checked = selected.includes(key);
                return (
                  <li key={String(key)}>
                    <label className={`${styles.option} ${checked ? styles.optionSelected : ''}`}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(key)}
                      />
                      <span>{getLabel(option)}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          {count > 0 && (
            <button
              type="button"
              className={styles.clearLocal}
              onClick={() => onChange([])}
            >
              Limpiar {label.toLowerCase()}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function ParaGanarScopeFilters({
  marcas,
  subcategorias,
  pms,
  onMarcasChange,
  onSubcategoriasChange,
  onPmsChange,
  onClear,
}) {
  const [opciones, setOpciones] = useState({ marcas: [], subcategorias: [], pms: [] });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setLoadError(null);
      try {
        const { data } = await api.get('/para-ganar/alcance-opciones');
        if (cancelled) return;
        setOpciones({
          marcas: data.marcas || [],
          subcategorias: data.subcategorias || [],
          pms: data.pms || [],
        });
      } catch (err) {
        if (cancelled) return;
        setOpciones({ marcas: [], subcategorias: [], pms: [] });
        if (err.response?.status === 403) {
          setLoadError('No tenés permiso para cargar filtros de alcance.');
        } else {
          setLoadError('No se pudieron cargar las opciones de alcance.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  const hasActive = marcas.length > 0 || subcategorias.length > 0 || pms.length > 0;
  const emptyHint = (emptyLabel) => {
    if (loading) return 'Cargando…';
    if (loadError) return loadError;
    return emptyLabel;
  };

  return (
    <div className={styles.bar} aria-label="Filtros de alcance">
      {loadError && (
        <p className={styles.loadError} role="alert">
          {loadError}{' '}
          <button
            type="button"
            className={styles.retryBtn}
            onClick={() => setReloadToken((n) => n + 1)}
          >
            Reintentar
          </button>
        </p>
      )}
      <MultiSelect
        label="Marca"
        options={opciones.marcas}
        selected={marcas}
        onChange={onMarcasChange}
        getKey={(marca) => marca}
        getLabel={(marca) => marca}
        emptyHint={emptyHint('Sin marcas en la cola')}
        disabled={loading || Boolean(loadError)}
      />
      <MultiSelect
        label="Subcategoría"
        options={opciones.subcategorias}
        selected={subcategorias}
        onChange={onSubcategoriasChange}
        getKey={(row) => row.id}
        getLabel={(row) => row.nombre}
        emptyHint={emptyHint('Sin subcategorías en la cola')}
        disabled={loading || Boolean(loadError)}
      />
      <MultiSelect
        label="PM"
        options={opciones.pms}
        selected={pms}
        onChange={onPmsChange}
        getKey={(row) => row.id}
        getLabel={(row) => row.nombre}
        emptyHint={emptyHint('Sin PMs asignados (sandbox)')}
        disabled={loading || Boolean(loadError)}
      />
      {hasActive && (
        <button type="button" className={styles.clearAll} onClick={onClear}>
          <X size={14} aria-hidden />
          Limpiar alcance
        </button>
      )}
    </div>
  );
}

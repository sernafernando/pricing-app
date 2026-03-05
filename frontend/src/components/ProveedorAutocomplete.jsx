/**
 * ProveedorAutocomplete — Input con búsqueda contra /rma-proveedores.
 *
 * Props:
 *   value        — nombre del proveedor actual (string)
 *   suppId       — supp_id actual (para mostrar estado "vinculado")
 *   onSelect     — callback({ supp_id, nombre }) cuando se elige uno
 *   disabled     — deshabilitar input
 *   className    — clase CSS para el wrapper
 *   inputClass   — clase CSS para el input
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, X } from 'lucide-react';
import api from '../services/api';
import styles from './ProveedorAutocomplete.module.css';

const DEBOUNCE_MS = 350;

export default function ProveedorAutocomplete({ value, suppId, onSelect, disabled, className, inputClass }) {
  const [query, setQuery] = useState(value || '');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef(null);
  const wrapperRef = useRef(null);

  // Sync external value changes (e.g. when item reloads)
  useEffect(() => {
    setQuery(value || '');
  }, [value]);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClick = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const buscar = useCallback(async (term) => {
    if (!term || term.length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.get('/rma-proveedores', {
        params: { search: term, page_size: 10 },
      });
      setResults(data.proveedores || []);
      setOpen(true);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleChange = (e) => {
    const val = e.target.value;
    setQuery(val);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => buscar(val), DEBOUNCE_MS);
  };

  const handleSelect = (prov) => {
    setQuery(prov.nombre);
    setOpen(false);
    setResults([]);
    onSelect({ supp_id: prov.supp_id, nombre: prov.nombre });
  };

  const handleClear = () => {
    setQuery('');
    setOpen(false);
    setResults([]);
    onSelect({ supp_id: null, nombre: null });
  };

  return (
    <div ref={wrapperRef} className={`${styles.wrapper} ${className || ''}`}>
      <div className={styles.inputWrap}>
        <Search size={14} className={styles.searchIcon} />
        <input
          className={`${inputClass || ''} ${styles.input}`}
          type="text"
          value={query}
          onChange={handleChange}
          onFocus={() => { if (results.length > 0) setOpen(true); }}
          placeholder="Buscar proveedor..."
          disabled={disabled}
        />
        {query && !disabled && (
          <button className={styles.clearBtn} onClick={handleClear} aria-label="Limpiar proveedor" type="button">
            <X size={14} />
          </button>
        )}
      </div>

      {suppId && (
        <span className={styles.linkedBadge}>ID: {suppId}</span>
      )}

      {open && results.length > 0 && (
        <ul className={styles.dropdown}>
          {results.map((p) => (
            <li key={p.id}>
              <button
                className={styles.option}
                onClick={() => handleSelect(p)}
                type="button"
              >
                <span className={styles.optName}>{p.nombre}</span>
                {p.cuit && <span className={styles.optDetail}>{p.cuit}</span>}
                {p.ciudad && <span className={styles.optDetail}>{p.ciudad}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      {open && loading && (
        <div className={styles.dropdown}>
          <div className={styles.loadingMsg}>Buscando...</div>
        </div>
      )}

      {open && !loading && query.length >= 2 && results.length === 0 && (
        <div className={styles.dropdown}>
          <div className={styles.emptyMsg}>Sin resultados</div>
        </div>
      )}
    </div>
  );
}

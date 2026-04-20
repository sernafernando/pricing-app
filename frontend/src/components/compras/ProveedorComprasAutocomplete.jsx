/**
 * ProveedorComprasAutocomplete — Autocomplete de proveedores para el módulo compras.
 *
 * Busca contra `/api/administracion/proveedores?search=...` (endpoint del módulo
 * Administración, NO el legacy /rma-proveedores que usa ProveedorAutocomplete).
 *
 * Display por ítem: `{supp_id} - {nombre}` + CUIT en subtítulo si existe.
 *
 * COMPRAS-7.7 — Reemplazo del input numérico de proveedor_id en los forms.
 *
 * Props:
 *   value        — proveedor_id actual (number | string | null)
 *   onChange     — callback(proveedorId: number | null, proveedor?: object)
 *   disabled     — deshabilitar input
 *   autoFocus    — autofocus al montar
 *   placeholder  — placeholder custom
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';
import api from '../../services/api';
import styles from './ProveedorComprasAutocomplete.module.css';

const DEBOUNCE_MS = 350;
const MIN_CHARS = 2;

export default function ProveedorComprasAutocomplete({
  value,
  onChange,
  disabled = false,
  autoFocus = false,
  placeholder = 'Buscar proveedor (nombre, CUIT)...',
}) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(null);
  const timerRef = useRef(null);
  const wrapperRef = useRef(null);

  // Cuando `value` cambia externamente (ej: edición de pedido existente),
  // pre-cargar el nombre del proveedor para mostrarlo.
  useEffect(() => {
    let cancelled = false;
    const loadCurrent = async () => {
      if (!value) {
        setSelected(null);
        setQuery('');
        return;
      }
      // Si ya tenemos el proveedor cacheado y coincide el id, nada que hacer.
      if (selected && Number(selected.id) === Number(value)) return;
      try {
        const { data } = await api.get(`/administracion/proveedores/${value}`);
        if (!cancelled) {
          setSelected(data);
          setQuery(_displayLabel(data));
        }
      } catch {
        if (!cancelled) {
          setSelected(null);
          setQuery('');
        }
      }
    };
    loadCurrent();
    return () => {
      cancelled = true;
    };
    // `selected` intencionalmente fuera — evita loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  // Cerrar dropdown al click afuera
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
    if (!term || term.length < MIN_CHARS) {
      setResults([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.get('/administracion/proveedores', {
        params: { search: term, page_size: 10, solo_activos: true },
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
    setSelected(prov);
    setQuery(_displayLabel(prov));
    setOpen(false);
    setResults([]);
    onChange(Number(prov.id), prov);
  };

  const handleClear = () => {
    setSelected(null);
    setQuery('');
    setOpen(false);
    setResults([]);
    onChange(null, null);
  };

  return (
    <div ref={wrapperRef} className={styles.wrapper}>
      <div className={styles.inputWrap}>
        <Search size={14} className={styles.searchIcon} />
        <input
          className={styles.input}
          type="text"
          value={query}
          onChange={handleChange}
          onFocus={() => {
            if (results.length > 0) setOpen(true);
          }}
          placeholder={placeholder}
          disabled={disabled}
          autoFocus={autoFocus}
          aria-label="Buscar proveedor"
        />
        {query && !disabled && (
          <button
            className={styles.clearBtn}
            onClick={handleClear}
            aria-label="Limpiar proveedor"
            type="button"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {open && loading && (
        <div className={styles.dropdown}>
          <div className={styles.loadingMsg}>Buscando...</div>
        </div>
      )}

      {open && !loading && results.length > 0 && (
        <ul className={styles.dropdown}>
          {results.map((p) => (
            <li key={p.id}>
              <button
                className={styles.option}
                onClick={() => handleSelect(p)}
                type="button"
              >
                <span className={styles.optName}>{_displayLabel(p)}</span>
                {p.cuit && <span className={styles.optDetail}>CUIT {p.cuit}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      {open && !loading && query.length >= MIN_CHARS && results.length === 0 && (
        <div className={styles.dropdown}>
          <div className={styles.emptyMsg}>Sin resultados</div>
        </div>
      )}
    </div>
  );
}

function _displayLabel(p) {
  if (!p) return '';
  // Preferimos supp_id (interno ERP) cuando está — es el que usa el módulo compras.
  const prefix = p.supp_id != null ? p.supp_id : p.id;
  return `${prefix} - ${p.nombre || p.supp_name || '(sin nombre)'}`;
}

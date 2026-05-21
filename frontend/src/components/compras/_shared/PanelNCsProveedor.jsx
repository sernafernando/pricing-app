import { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import useNCsLocales from '../../../hooks/useNCsLocales';
import styles from './PanelNCsProveedor.module.css';

/**
 * PanelNCsProveedor — panel colapsable de NCs disponibles para un proveedor.
 *
 * Soporta dos modos:
 *
 * mode="aplicar" (default — usado desde ModalOrdenPagoDetalle / F4):
 *   - Muestra un input de monto por NC y un botón "Aplicar".
 *   - Al hacer click llama `onAplicar(nc, monto)`.
 *   - El caller es responsable de hacer la llamada al backend y refrescar.
 *
 * mode="seleccionar" (F7 — usado desde ModalOrdenPagoNueva):
 *   - Muestra checkboxes + input de monto.
 *   - Mantiene estado interno de las NCs seleccionadas y notifica al padre
 *     vía `onChange(ncsSeleccionadas)` donde cada entrada es
 *     `{ nc_id, monto, pedido_id }`.
 *   - `pedido_id` se deja en null aquí; el caller lo inyecta cuando tiene
 *     un único pedido en los items, o el backend lo resuelve con 422 si
 *     hace falta y el usuario no lo proveyó.
 *
 * Props:
 *   proveedorId   (number|string)  — id del proveedor; si es falsy el panel no carga.
 *   moneda        (string)         — "ARS" | "USD"; filtra NCs por moneda (opcional).
 *   mode          ("aplicar"|"seleccionar") — default "aplicar".
 *   onAplicar     (nc, monto) => Promise<void>  — sólo en mode="aplicar".
 *   onChange      (ncsSeleccionadas) => void    — sólo en mode="seleccionar".
 *   disabled      (bool)           — desactiva inputs/botones.
 */
const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export default function PanelNCsProveedor({
  proveedorId,
  moneda,
  mode = 'aplicar',
  onAplicar,
  onChange,
  disabled = false,
}) {
  const { listarDisponibles: listarNCs } = useNCsLocales();

  const [abierto, setAbierto] = useState(false);
  const [ncsDisponibles, setNcsDisponibles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // mode="aplicar": map nc.id → monto string
  const [montos, setMontos] = useState({});
  // mode="aplicar": map nc.id → { loading, error }
  const [aplicando, setAplicando] = useState({});

  // mode="seleccionar": map nc.id → { checked, monto }
  const [seleccion, setSeleccion] = useState({});

  const fetchNCs = useCallback(async () => {
    if (!proveedorId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await listarNCs({ proveedor_id: proveedorId, limit: 100, offset: 0 });
      let items = Array.isArray(result) ? result : [];
      // Optional client-side moneda filter (backend may not support it).
      if (moneda) {
        items = items.filter((nc) => nc.moneda === moneda);
      }
      setNcsDisponibles(items);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar NCs del proveedor.');
    } finally {
      setLoading(false);
    }
  }, [listarNCs, proveedorId, moneda]);

  useEffect(() => {
    if (abierto && proveedorId) {
      fetchNCs();
    }
  }, [abierto, proveedorId, fetchNCs]);

  // Reset state when proveedor changes.
  useEffect(() => {
    setNcsDisponibles([]);
    setMontos({});
    setAplicando({});
    setSeleccion({});
    setError(null);
  }, [proveedorId]);

  // ── mode="aplicar" handlers ────────────────────────────────────────────

  const handleAplicar = useCallback(
    async (nc) => {
      const montoStr = montos[nc.id] ?? '';
      const monto = parseFloat(montoStr);
      if (!monto || monto <= 0) {
        setAplicando((prev) => ({
          ...prev,
          [nc.id]: { loading: false, error: 'Ingresá un monto mayor a 0.' },
        }));
        return;
      }
      setAplicando((prev) => ({ ...prev, [nc.id]: { loading: true, error: null } }));
      try {
        await onAplicar(nc, monto);
        setMontos((prev) => ({ ...prev, [nc.id]: '' }));
        setAplicando((prev) => ({ ...prev, [nc.id]: { loading: false, error: null } }));
        await fetchNCs();
      } catch (err) {
        const msg = err.response?.data?.detail || err.message || 'Error al aplicar la NC.';
        setAplicando((prev) => ({
          ...prev,
          [nc.id]: {
            loading: false,
            error: typeof msg === 'string' ? msg : 'Error al aplicar la NC.',
          },
        }));
      }
    },
    [montos, onAplicar, fetchNCs],
  );

  // ── mode="seleccionar" handlers ────────────────────────────────────────

  const notifyChange = useCallback(
    (nextSeleccion) => {
      if (!onChange) return;
      const result = Object.entries(nextSeleccion)
        .filter(([, v]) => v.checked && parseFloat(v.monto) > 0)
        .map(([ncId, v]) => ({
          nc_id: Number(ncId),
          monto: parseFloat(v.monto),
          pedido_id: null, // resolved by backend or caller
        }));
      onChange(result);
    },
    [onChange],
  );

  const handleToggle = (nc) => {
    const cur = seleccion[nc.id] ?? { checked: false, monto: '' };
    const next = { ...seleccion, [nc.id]: { ...cur, checked: !cur.checked } };
    setSeleccion(next);
    notifyChange(next);
  };

  const handleMontoSeleccion = (nc, value) => {
    const cur = seleccion[nc.id] ?? { checked: false, monto: '' };
    const next = { ...seleccion, [nc.id]: { ...cur, monto: value } };
    setSeleccion(next);
    notifyChange(next);
  };

  if (!proveedorId) return null;

  return (
    <div className={styles.wrapper}>
      <button
        type="button"
        className={styles.toggleBtn}
        onClick={() => setAbierto((v) => !v)}
        aria-expanded={abierto}
      >
        NCs disponibles del proveedor{' '}
        {abierto ? (
          <ChevronDown size={14} className={styles.arrow} />
        ) : (
          <ChevronRight size={14} className={styles.arrow} />
        )}
      </button>

      {abierto && (
        <div className={styles.panel}>
          {loading && (
            <div className={styles.centered}>
              <Loader2 size={16} className={styles.spin} /> Cargando NCs...
            </div>
          )}
          {error && <div className={styles.errorBanner}>{error}</div>}
          {!loading && !error && ncsDisponibles.length === 0 && (
            <div className={styles.emptySection}>
              Sin NCs aprobadas con saldo disponible para este proveedor
              {moneda ? ` en ${moneda}` : ''}.
            </div>
          )}
          {!loading && ncsDisponibles.length > 0 && (
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    {mode === 'seleccionar' && <th></th>}
                    <th>NC</th>
                    <th>Moneda</th>
                    <th className={styles.thRight}>Saldo disponible</th>
                    <th>{mode === 'aplicar' ? 'Monto a aplicar' : 'Monto a descontar'}</th>
                    {mode === 'aplicar' && <th></th>}
                  </tr>
                </thead>
                <tbody>
                  {ncsDisponibles.map((nc) => {
                    const saldo = Number(nc.saldo_pendiente ?? nc.monto) || 0;

                    if (mode === 'aplicar') {
                      const rowState = aplicando[nc.id] ?? {};
                      return (
                        <tr key={nc.id}>
                          <td className={styles.tdSecondary}>{nc.numero}</td>
                          <td>{nc.moneda}</td>
                          <td className={styles.tdRight}>{formatCurrency(saldo, nc.moneda)}</td>
                          <td>
                            <input
                              type="number"
                              min="0.01"
                              step="0.01"
                              max={saldo}
                              placeholder="Monto"
                              className={styles.montoInput}
                              value={montos[nc.id] ?? ''}
                              onChange={(e) =>
                                setMontos((prev) => ({ ...prev, [nc.id]: e.target.value }))
                              }
                              disabled={disabled || rowState.loading}
                              aria-label={`Monto a aplicar para NC ${nc.numero}`}
                            />
                          </td>
                          <td>
                            <button
                              type="button"
                              className={styles.btnSmall}
                              onClick={() => handleAplicar(nc)}
                              disabled={disabled || rowState.loading}
                              aria-label={`Aplicar NC ${nc.numero}`}
                            >
                              {rowState.loading ? (
                                <Loader2 size={12} className={styles.spin} />
                              ) : (
                                'Aplicar'
                              )}
                            </button>
                            {rowState.error && (
                              <p className={styles.rowError}>{rowState.error}</p>
                            )}
                          </td>
                        </tr>
                      );
                    }

                    // mode="seleccionar"
                    const sel = seleccion[nc.id] ?? { checked: false, monto: '' };
                    return (
                      <tr key={nc.id}>
                        <td>
                          <input
                            type="checkbox"
                            checked={sel.checked}
                            onChange={() => handleToggle(nc)}
                            disabled={disabled}
                            aria-label={`Seleccionar NC ${nc.numero}`}
                          />
                        </td>
                        <td className={styles.tdSecondary}>{nc.numero}</td>
                        <td>{nc.moneda}</td>
                        <td className={styles.tdRight}>{formatCurrency(saldo, nc.moneda)}</td>
                        <td>
                          <input
                            type="number"
                            min="0.01"
                            step="0.01"
                            max={saldo}
                            placeholder="Monto"
                            className={styles.montoInput}
                            value={sel.monto}
                            onChange={(e) => handleMontoSeleccion(nc, e.target.value)}
                            disabled={disabled || !sel.checked}
                            aria-label={`Monto a descontar para NC ${nc.numero}`}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

import { useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import api from '../services/api';
import { useDebounce } from '../hooks/useDebounce';
import styles from './GestionFull.module.css';

const GROUP_TONES = ['toneA', 'toneB', 'toneC'];

/** Assign a stable tint class per contiguous EAN group. */
function withGroupTones(items) {
  let groupIndex = -1;
  let prevEan = null;
  return items.map((row) => {
    if (row.ean !== prevEan) {
      groupIndex += 1;
      prevEan = row.ean;
    }
    return { ...row, _tone: GROUP_TONES[groupIndex % GROUP_TONES.length] };
  });
}

function cell(value) {
  if (value === null || value === undefined || value === '') return '—';
  return value;
}

function overrideDraftValue(value) {
  if (value === null || value === undefined) return '';
  return String(value);
}

export default function GestionFull() {
  const [q, setQ] = useState('');
  const [marca, setMarca] = useState('');
  const [categoria, setCategoria] = useState('');
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [drafts, setDrafts] = useState({});
  const [savingId, setSavingId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const debouncedQ = useDebounce(q, 300);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setLoadError(null);
      setSaveError(null);
      try {
        const { data } = await api.get('/gestion-full', {
          params: {
            q: debouncedQ || undefined,
            marca: marca || undefined,
            categoria: categoria || undefined,
            limit: 200,
            offset: 0,
          },
        });
        if (cancelled) return;
        const nextItems = withGroupTones(data.items || []);
        setItems(nextItems);
        setTotal(data.total || 0);
        const nextDrafts = {};
        nextItems.forEach((row) => {
          nextDrafts[row.inventory_id] = overrideDraftValue(row.override);
        });
        setDrafts(nextDrafts);
      } catch {
        if (!cancelled) setLoadError('No se pudo cargar Gestión Full');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [debouncedQ, marca, categoria]);

  const clearFilters = () => {
    setQ('');
    setMarca('');
    setCategoria('');
  };

  const onDraftChange = (inventoryId, value) => {
    setDrafts((prev) => ({ ...prev, [inventoryId]: value }));
  };

  const saveOverride = async (row) => {
    if (!row.puede_editar_override) return;
    const raw = (drafts[row.inventory_id] ?? '').trim();
    const next =
      raw === '' ? null : Number.parseInt(raw, 10);
    if (raw !== '' && (Number.isNaN(next) || next < 0)) {
      setDrafts((prev) => ({
        ...prev,
        [row.inventory_id]: overrideDraftValue(row.override),
      }));
      return;
    }
    if (next === (row.override ?? null)) return;

    setSavingId(row.inventory_id);
    setSaveError(null);
    try {
      const { data } = await api.patch(`/gestion-full/${encodeURIComponent(row.inventory_id)}`, {
        cantidad: next,
      });
      setItems((prev) =>
        prev.map((item) =>
          item.inventory_id === row.inventory_id
            ? { ...item, override: data.override ?? null }
            : item,
        ),
      );
      setDrafts((prev) => ({
        ...prev,
        [row.inventory_id]: overrideDraftValue(data.override),
      }));
    } catch {
      setSaveError(`No se pudo guardar override de ${row.inventory_id}`);
      setDrafts((prev) => ({
        ...prev,
        [row.inventory_id]: overrideDraftValue(row.override),
      }));
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Gestión Full</h1>
        <p className={styles.subtitle}>Reposición Full por producto</p>
      </header>

      <div className={styles.filters}>
        <label className={styles.search}>
          <Search size={14} aria-hidden />
          <input
            className={styles.input}
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="EAN, descripción o inventory_id…"
            aria-label="Buscar"
          />
        </label>
        <input
          className={styles.input}
          type="text"
          value={marca}
          onChange={(e) => setMarca(e.target.value)}
          placeholder="Marca (exacta)"
          aria-label="Marca"
        />
        <input
          className={styles.input}
          type="text"
          value={categoria}
          onChange={(e) => setCategoria(e.target.value)}
          placeholder="Categoría (exacta)"
          aria-label="Categoría"
        />
        <button type="button" className={styles.clearBtn} onClick={clearFilters}>
          Limpiar
        </button>
        <span className={styles.meta}>{total} filas</span>
      </div>

      {loadError && <div className={styles.error}>{loadError}</div>}
      {saveError && <div className={styles.error}>{saveError}</div>}
      {loading && <div className={styles.loading}>Cargando…</div>}

      {!loading && !loadError && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>EAN</th>
                <th>Descripción</th>
                <th>Código ML</th>
                <th>Familia (MLAU)</th>
                <th>Full 7d</th>
                <th>Full 14d</th>
                <th>Full 21d</th>
                <th>Full 30d</th>
                <th>C+F 7d</th>
                <th>C+F 30d</th>
                <th>Stock ERP</th>
                <th>Stock Full</th>
                <th>Target</th>
                <th>Sugerido</th>
                <th>Override</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={`${row.producto_item_id}-${row.inventory_id}`} className={styles[row._tone]}>
                  <td className={styles.mono}>{cell(row.ean)}</td>
                  <td className={styles.desc} title={row.descripcion || ''}>
                    {cell(row.descripcion)}
                  </td>
                  <td className={styles.mono}>{cell(row.inventory_id)}</td>
                  <td className={styles.mono}>{cell(row.user_product_id)}</td>
                  <td className={styles.num}>{cell(row.ventas_full_7d)}</td>
                  <td className={styles.num}>{cell(row.ventas_full_14d)}</td>
                  <td className={styles.num}>{cell(row.ventas_full_21d)}</td>
                  <td className={styles.num}>{cell(row.ventas_full_30d)}</td>
                  <td className={styles.num}>{cell(row.ventas_colecta_flex_7d)}</td>
                  <td className={styles.num}>{cell(row.ventas_colecta_flex_30d)}</td>
                  <td className={styles.num}>{cell(row.stock_erp)}</td>
                  <td className={styles.num}>{cell(row.stock_full)}</td>
                  <td className={styles.num}>{cell(row.target)}</td>
                  <td className={styles.num}>{cell(row.sugerido)}</td>
                  <td>
                    {row.puede_editar_override ? (
                      <input
                        className={styles.override}
                        type="number"
                        inputMode="numeric"
                        min={0}
                        step={1}
                        value={drafts[row.inventory_id] ?? ''}
                        disabled={savingId === row.inventory_id}
                        onChange={(e) => onDraftChange(row.inventory_id, e.target.value)}
                        onBlur={() => saveOverride(row)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.currentTarget.blur();
                          }
                        }}
                        aria-label={`Override ${row.inventory_id}`}
                      />
                    ) : (
                      <span className={styles.muted}>{cell(row.override)}</span>
                    )}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={15} className={styles.empty}>
                    Sin filas con inventory_id vinculado
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

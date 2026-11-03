import { useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import api from '../../services/api';
import { useDebounce } from '../../hooks/useDebounce';
import styles from '../../pages/GestionFull.module.css';

function cell(value) {
  if (value === null || value === undefined || value === '') return '—';
  return value;
}

function parseImportText(text) {
  const rows = [];
  const errors = [];
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  lines.forEach((line, index) => {
    if (index === 0 && /ean/i.test(line) && /unidad/i.test(line)) return;
    const parts = line.split(/[,;\t]/).map((p) => p.trim());
    if (parts.length < 2) {
      errors.push(`Línea ${index + 1}: formato EAN,unidades`);
      return;
    }
    const ean = parts[0];
    const unidades = Number.parseInt(parts[1], 10);
    if (!ean || Number.isNaN(unidades) || unidades < 1) {
      errors.push(`Línea ${index + 1}: EAN/unidades inválidos`);
      return;
    }
    rows.push({ ean, unidades });
  });
  return { rows, errors };
}

/** Unique ERP products from Gestión Full list rows (first MLAU wins). */
function uniqueByProducto(items) {
  const seen = new Set();
  const out = [];
  items.forEach((row) => {
    if (seen.has(row.producto_item_id)) return;
    seen.add(row.producto_item_id);
    out.push(row);
  });
  return out;
}

function motivoLabel(row) {
  const parts = [];
  if (row.en_paquete) parts.push('Paquete');
  if (row.pm_ready) parts.push('Listo');
  return parts.length ? parts.join(' · ') : '—';
}

export default function GestionFullDepositosTab() {
  const [mode, setMode] = useState('pendientes');
  const [q, setQ] = useState('');
  const [items, setItems] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [savingId, setSavingId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [importText, setImportText] = useState('');
  const [importMsg, setImportMsg] = useState(null);
  const debouncedQ = useDebounce(q, 300);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      if (mode === 'pendientes') {
        const { data } = await api.get('/gestion-full/unidades-caja/pendientes', {
          params: { q: debouncedQ || undefined },
        });
        const list = data.items || [];
        setItems(list);
        const next = {};
        list.forEach((row) => {
          next[row.producto_item_id] = '';
        });
        setDrafts(next);
      } else {
        const { data } = await api.get('/gestion-full', {
          params: {
            q: debouncedQ || undefined,
            full_mode: 'todos',
            include_zero_stock: true,
            limit: 200,
            offset: 0,
          },
        });
        const unique = uniqueByProducto(data.items || []);
        setItems(unique);
        const next = {};
        unique.forEach((row) => {
          next[row.producto_item_id] =
            row.unidades_por_caja == null ? '' : String(row.unidades_por_caja);
        });
        setDrafts(next);
      }
    } catch {
      setError('No se pudo cargar productos para depósito');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload on search/mode
  }, [debouncedQ, mode]);

  const saveRow = async (row) => {
    const raw = (drafts[row.producto_item_id] ?? '').trim();
    const next = raw === '' ? null : Number.parseInt(raw, 10);
    if (raw !== '' && (Number.isNaN(next) || next < 1)) {
      setDrafts((prev) => ({
        ...prev,
        [row.producto_item_id]:
          row.unidades_por_caja == null ? '' : String(row.unidades_por_caja),
      }));
      return;
    }
    if (next === (row.unidades_por_caja ?? null)) return;

    setSavingId(row.producto_item_id);
    setError(null);
    try {
      const { data } = await api.patch(
        `/gestion-full/unidades-caja/${row.producto_item_id}`,
        { unidades: next },
      );
      if (mode === 'pendientes' && data.unidades_por_caja != null) {
        setItems((prev) => prev.filter((item) => item.producto_item_id !== row.producto_item_id));
        setDrafts((prev) => {
          const copy = { ...prev };
          delete copy[row.producto_item_id];
          return copy;
        });
      } else {
        setItems((prev) =>
          prev.map((item) =>
            item.producto_item_id === row.producto_item_id
              ? { ...item, unidades_por_caja: data.unidades_por_caja ?? null }
              : item,
          ),
        );
        setDrafts((prev) => ({
          ...prev,
          [row.producto_item_id]:
            data.unidades_por_caja == null ? '' : String(data.unidades_por_caja),
        }));
      }
    } catch {
      setError(`No se pudo guardar U/caja de ${row.ean || row.producto_item_id}`);
    } finally {
      setSavingId(null);
    }
  };

  const runImport = async () => {
    const { rows, errors } = parseImportText(importText);
    if (errors.length) {
      setImportMsg(errors.slice(0, 5).join(' · '));
      return;
    }
    if (!rows.length) {
      setImportMsg('Pegá líneas EAN,unidades');
      return;
    }
    setImportMsg(null);
    setError(null);
    try {
      const { data } = await api.post('/gestion-full/unidades-caja/import', { rows });
      const errN = (data.errors || []).length;
      setImportMsg(
        `Actualizados: ${data.updated}${errN ? ` · errores: ${errN}` : ''}`,
      );
      await load();
    } catch {
      setError('No se pudo importar el listado');
    }
  };

  return (
    <div className={styles.depositos}>
      <p className={styles.subtitle}>
        Unidades por caja cerrada (por producto ERP). Por defecto: pendientes del
        paquete de la semana y/o Listo (para no trabar el Excel). Pegá desde Sheets:
        EAN,unidades.
      </p>

      <div className={styles.filters}>
        <div className={styles.modeToggle} role="group" aria-label="Vista depósito">
          <button
            type="button"
            className={mode === 'pendientes' ? styles.tabActive : styles.tab}
            onClick={() => setMode('pendientes')}
          >
            Pendientes
          </button>
          <button
            type="button"
            className={mode === 'todos' ? styles.tabActive : styles.tab}
            onClick={() => setMode('todos')}
          >
            Todos
          </button>
        </div>
        <label className={styles.search}>
          <Search size={14} aria-hidden />
          <input
            className={styles.input}
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar EAN o descripción…"
            aria-label="Buscar depósito"
          />
        </label>
      </div>

      <label className={styles.importBlock}>
        <span className={styles.filterLabel}>Importar (EAN,unidades)</span>
        <textarea
          className={styles.textarea}
          rows={4}
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          placeholder={'6935364080433,12\n193015522459,24'}
          aria-label="Importar unidades por caja"
        />
      </label>
      <button type="button" className={styles.clearBtn} onClick={runImport}>
        Importar
      </button>
      {importMsg && <div className={styles.meta}>{importMsg}</div>}

      {error && <div className={styles.error}>{error}</div>}
      {loading && <div className={styles.loading}>Cargando…</div>}

      {!loading && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>EAN</th>
                <th>Descripción</th>
                {mode === 'pendientes' && <th>Motivo</th>}
                <th>U/caja</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.producto_item_id}>
                  <td className={styles.mono}>{cell(row.ean)}</td>
                  <td className={styles.desc}>{cell(row.descripcion)}</td>
                  {mode === 'pendientes' && (
                    <td className={styles.meta}>{motivoLabel(row)}</td>
                  )}
                  <td>
                    <input
                      className={styles.override}
                      type="number"
                      inputMode="numeric"
                      min={1}
                      step={1}
                      value={drafts[row.producto_item_id] ?? ''}
                      disabled={savingId === row.producto_item_id}
                      onChange={(e) =>
                        setDrafts((prev) => ({
                          ...prev,
                          [row.producto_item_id]: e.target.value,
                        }))
                      }
                      onBlur={() => saveRow(row)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') e.currentTarget.blur();
                      }}
                      aria-label={`U/caja ${row.ean || row.producto_item_id}`}
                    />
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={mode === 'pendientes' ? 4 : 3} className={styles.empty}>
                    {mode === 'pendientes'
                      ? 'Sin pendientes de U/caja en paquete o Listo'
                      : 'Sin productos'}
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

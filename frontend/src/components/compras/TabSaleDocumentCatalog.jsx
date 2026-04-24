import { useCallback, useEffect, useState } from 'react';
import { Loader2, AlertTriangle, Check, X } from 'lucide-react';
import api from '../../services/api';
import SearchInput from '../SearchInput';
import styles from './TabSaleDocumentCatalog.module.css';

const FLAG_COLS = [
  ['sd_ispurchase', 'compra'],
  ['sd_issales', 'venta'],
  ['sd_isbanking', 'banco'],
  ['sd_iscreditnote', 'NC'],
  ['sd_isdebitnote', 'ND'],
  ['sd_ispackinglist', 'remito'],
  ['sd_isannulment', 'anul'],
  ['sd_isquotation', 'cotiz'],
];

const clasificacionBadge = (c) => {
  if (!c) return 'Sin clasificar';
  return c;
};

export default function TabSaleDocumentCatalog() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [faltantes, setFaltantes] = useState([]);
  const [loadingFaltantes, setLoadingFaltantes] = useState(false);

  const [filtroClasif, setFiltroClasif] = useState('');
  const [filtroBusqueda, setFiltroBusqueda] = useState('');

  const fetchCatalogo = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get('/administracion/compras/sale-documents');
      setItems(data || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar el catálogo.');
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchFaltantes = useCallback(async () => {
    setLoadingFaltantes(true);
    try {
      const { data } = await api.get('/administracion/compras/sale-documents/faltantes');
      setFaltantes(data || []);
    } catch {
      setFaltantes([]);
    } finally {
      setLoadingFaltantes(false);
    }
  }, []);

  useEffect(() => {
    fetchCatalogo();
    fetchFaltantes();
  }, [fetchCatalogo, fetchFaltantes]);

  const clasificacionesUnicas = Array.from(
    new Set(items.map((it) => it.clasificacion).filter(Boolean))
  ).sort();

  const itemsFiltrados = items.filter((it) => {
    if (filtroClasif && it.clasificacion !== filtroClasif) return false;
    if (filtroBusqueda) {
      const q = filtroBusqueda.trim().toLowerCase();
      if (
        !String(it.sd_id).includes(q) &&
        !(it.sd_desc || '').toLowerCase().includes(q)
      )
        return false;
    }
    return true;
  });

  return (
    <div className={styles.container}>
      {/* Alerta de sd_id faltantes */}
      {faltantes.length > 0 && (
        <div className={styles.alertaFaltantes}>
          <AlertTriangle size={18} />
          <div>
            <strong>
              Detectados {faltantes.length} sd_id nuevo(s) en el ERP no catalogado(s):
            </strong>
            <div className={styles.faltantesList}>
              {faltantes.map((f) => (
                <span key={f.sd_id} className={styles.faltanteChip}>
                  sd_id={f.sd_id} ({f.count} txns)
                </span>
              ))}
            </div>
            <p className={styles.faltantesHint}>
              Contactá al admin para agregarlos al catálogo vía migración Alembic (no hay
              sync automático por diseño).
            </p>
          </div>
        </div>
      )}

      {loadingFaltantes && faltantes.length === 0 && (
        <div className={styles.centered}>
          <Loader2 size={14} className={styles.spin} /> Verificando sd_ids faltantes...
        </div>
      )}

      {/* Filtros */}
      <div className={styles.topBar}>
        <div className={styles.filters}>
          <select
            className={styles.select}
            value={filtroClasif}
            onChange={(e) => setFiltroClasif(e.target.value)}
          >
            <option value="">Todas las clasificaciones</option>
            {clasificacionesUnicas.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <SearchInput
            value={filtroBusqueda}
            onChange={setFiltroBusqueda}
            placeholder="Buscar por sd_id o descripción..."
            size="sm"
          />
        </div>
        <div className={styles.countBadge}>
          {itemsFiltrados.length} / {items.length}
        </div>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      {loading && items.length === 0 ? (
        <div className={styles.centered}>
          <Loader2 size={20} className={styles.spin} /> Cargando catálogo...
        </div>
      ) : itemsFiltrados.length === 0 ? (
        <div className={styles.emptyState}>Sin resultados con los filtros aplicados.</div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>sd_id</th>
                <th>Descripción</th>
                <th>+/-</th>
                <th>hacc_group</th>
                <th>Clasificación</th>
                {FLAG_COLS.map((col) => (
                  <th key={col[1]} className={styles.thCenter}>
                    {col[1]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {itemsFiltrados.map((it) => (
                <tr key={it.sd_id}>
                  <td className={styles.tdMono}>{it.sd_id}</td>
                  <td>{it.sd_desc}</td>
                  <td className={styles.tdCenter}>{it.sd_plusorminus > 0 ? '+1' : '-1'}</td>
                  <td className={styles.tdSecondary}>{it.hacc_group ?? '—'}</td>
                  <td>
                    <span className={styles.clasifBadge}>
                      {clasificacionBadge(it.clasificacion)}
                    </span>
                  </td>
                  {FLAG_COLS.map(([key]) => (
                    <td key={key} className={styles.tdCenter}>
                      {it[key] ? (
                        <Check size={14} className={styles.iconCheck} />
                      ) : (
                        <X size={14} className={styles.iconX} />
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

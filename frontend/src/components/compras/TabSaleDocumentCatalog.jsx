import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Check, X, Inbox } from 'lucide-react';
import api from '../../services/api';
import SearchInput from '../SearchInput';
import DataTable from './_shared/DataTable';
import LoadingBlock from './_shared/LoadingBlock';
import FiltersBar from './_shared/FiltersBar';
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

const COLUMNS = [
  { key: 'sd_id', label: 'sd_id', width: '80px' },
  { key: 'sd_desc', label: 'Descripción' },
  { key: 'sd_plusorminus', label: '+/-', align: 'center', width: '60px' },
  { key: 'hacc_group', label: 'hacc_group', width: '110px' },
  { key: 'clasificacion', label: 'Clasificación', width: '160px' },
  ...FLAG_COLS.map(([key, label]) => ({ key, label, align: 'center', width: '70px' })),
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
        <LoadingBlock tone="inline" text="Verificando sd_ids faltantes…" />
      )}

      {/* Filtros */}
      <FiltersBar
        actions={
          <div className={styles.countBadge}>
            {itemsFiltrados.length} / {items.length}
          </div>
        }
      >
        <select
          className={styles.select}
          value={filtroClasif}
          onChange={(e) => setFiltroClasif(e.target.value)}
          aria-label="Filtrar por clasificación"
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
      </FiltersBar>

      {error && <div className={styles.errorBanner}>{error}</div>}

      {loading && items.length === 0 ? (
        <LoadingBlock text="Cargando catálogo…" />
      ) : (
        <DataTable
          columns={COLUMNS}
          rows={itemsFiltrados}
          renderCell={(it, col) => {
            if (col.key === 'sd_id') return <span className={styles.tdMono}>{it.sd_id}</span>;
            if (col.key === 'sd_desc') return it.sd_desc;
            if (col.key === 'sd_plusorminus') return it.sd_plusorminus > 0 ? '+1' : '-1';
            if (col.key === 'hacc_group')
              return <span className={styles.tdSecondary}>{it.hacc_group ?? '—'}</span>;
            if (col.key === 'clasificacion')
              return (
                <span className={styles.clasifBadge}>{clasificacionBadge(it.clasificacion)}</span>
              );
            // Flag columns
            return it[col.key] ? (
              <Check size={14} className={styles.iconCheck} />
            ) : (
              <X size={14} className={styles.iconX} />
            );
          }}
          empty={{
            icon: <Inbox size={28} strokeWidth={1.5} />,
            title: 'Sin resultados con los filtros aplicados.',
          }}
          minWidth="1300px"
        />
      )}
    </div>
  );
}

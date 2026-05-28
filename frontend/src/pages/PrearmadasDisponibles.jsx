import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Filter, Package, PackageOpen } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import usePrearmadasArmadas from '../hooks/usePrearmadasArmadas';
import { useDebounce } from '../hooks/useDebounce';
import styles from './PrearmadasDisponibles.module.css';

const PERM = 'produccion.ver_prearmadas_stats';
const PAGE_SIZE = 50;

// ── Helpers ──────────────────────────────────────────────────────────────────

function WindowsBadge({ value }) {
  if (!value) return <span className={`${styles.winBadge} ${styles.winNone}`}>Sin Windows</span>;
  if (value === 'home') return <span className={`${styles.winBadge} ${styles.winHome}`}>Home</span>;
  if (value === 'pro') return <span className={`${styles.winBadge} ${styles.winPro}`}>Pro</span>;
  return <span className={`${styles.winBadge} ${styles.winNone}`}>{value}</span>;
}

function CoverChip({ cover }) {
  const cls = cover.classification === 'exact' ? styles.coverExact : styles.coverUpgrade;
  return (
    <span className={`${styles.coverChip} ${cls}`} title={cover.item_desc || cover.item_code}>
      {cover.item_code}
    </span>
  );
}

function SkeletonRows({ count = 8, cols = 7 }) {
  return Array.from({ length: count }).map((_, i) => (
    <tr key={i} className={styles.skeletonRow}>
      {Array.from({ length: cols }).map((__, j) => (
        <td key={j}>
          <div className={styles.skeletonCell} style={{ width: j === 1 ? '80%' : '60%' }} />
        </td>
      ))}
    </tr>
  ));
}

// ── Main component ────────────────────────────────────────────────────────────

export default function PrearmadasDisponibles() {
  const { tienePermiso } = usePermisos();

  const [searchInput, setSearchInput] = useState('');
  const [winFilter, setWinFilter] = useState('all');
  const [groupByBase, setGroupByBase] = useState(false);
  const [page, setPage] = useState(1);
  const [collapsedGroups, setCollapsedGroups] = useState({});

  // Debounce the ean_base query param (server-side filter)
  const debouncedEanBase = useDebounce(searchInput, 300);

  const { items, total, loading, error, refetch } = usePrearmadasArmadas({
    eanBase: debouncedEanBase,
    page,
    pageSize: PAGE_SIZE,
  });

  // Reset page when search changes
  useEffect(() => {
    setPage(1);
  }, [debouncedEanBase]);

  // Client-side Windows filter
  const filteredItems = useMemo(() => {
    if (winFilter === 'all') return items;
    if (winFilter === 'none') return items.filter((it) => !it.incluye_windows);
    return items.filter((it) => it.incluye_windows === winFilter);
  }, [items, winFilter]);

  // Client-side grouping by ean_base
  const groupedData = useMemo(() => {
    if (!groupByBase) return null;
    const map = new Map();
    for (const item of filteredItems) {
      const base = item.parsed?.ean_base || '(sin base)';
      if (!map.has(base)) map.set(base, []);
      map.get(base).push(item);
    }
    return map;
  }, [filteredItems, groupByBase]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const toggleGroup = (base) => {
    setCollapsedGroups((prev) => ({ ...prev, [base]: !prev[base] }));
  };

  // ── No permission ──
  if (!tienePermiso(PERM)) {
    return (
      <div className={styles.noPerm}>
        <PackageOpen size={48} />
        <p>No tenés permiso para ver esta sección.</p>
        <small>Solicitá el permiso <code>{PERM}</code> a un administrador.</small>
      </div>
    );
  }

  // ── Table rows (flat) ──
  function renderFlatRows() {
    if (loading) return <SkeletonRows />;
    if (filteredItems.length === 0) {
      return (
        <tr>
          <td colSpan={7}>
            <div className={styles.stateBox}>
              <PackageOpen size={36} />
              <span>No hay prearmadas armadas con los filtros actuales.</span>
            </div>
          </td>
        </tr>
      );
    }
    return filteredItems.map((it) => <ItemRow key={it.prearmado_id} item={it} />);
  }

  // ── Table rows (grouped) ──
  function renderGroupedRows() {
    if (loading) return <SkeletonRows />;
    if (!groupedData || groupedData.size === 0) {
      return (
        <tr>
          <td colSpan={7}>
            <div className={styles.stateBox}>
              <PackageOpen size={36} />
              <span>No hay prearmadas armadas con los filtros actuales.</span>
            </div>
          </td>
        </tr>
      );
    }
    const rows = [];
    for (const [base, groupItems] of groupedData) {
      const isCollapsed = collapsedGroups[base];
      rows.push(
        <tr key={`grp-${base}`} className={styles.groupRow} onClick={() => toggleGroup(base)}>
          <td colSpan={7}>
            <span className={styles.groupRowLabel}>
              {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
              <Package size={14} />
              <strong>{base}</strong>
              <span style={{ fontWeight: 400, marginLeft: 4 }}>({groupItems.length})</span>
            </span>
          </td>
        </tr>,
      );
      if (!isCollapsed) {
        groupItems.forEach((it) => rows.push(<ItemRow key={it.prearmado_id} item={it} />));
      }
    }
    return rows;
  }

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.header}>
        <Package size={22} />
        <h1>Prearmadas disponibles</h1>
      </div>

      {/* Filter bar */}
      <div className={styles.filterBar}>
        <Filter size={15} style={{ color: 'var(--cf-text-muted)' }} />
        <input
          type="text"
          className={styles.searchInput}
          placeholder="Buscar por EAN base (ej: LENOVO)..."
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          aria-label="Filtrar por EAN base"
        />
        <select
          className={styles.filterSelect}
          value={winFilter}
          onChange={(e) => setWinFilter(e.target.value)}
          aria-label="Filtrar por variante Windows"
        >
          <option value="all">Todas las variantes</option>
          <option value="home">Windows Home</option>
          <option value="pro">Windows Pro</option>
          <option value="none">Sin Windows</option>
        </select>
        <label className={styles.groupToggle}>
          <input
            type="checkbox"
            checked={groupByBase}
            onChange={(e) => setGroupByBase(e.target.checked)}
          />
          Agrupar por EAN base
        </label>
      </div>

      {/* Error state */}
      {error && (
        <div className={styles.stateBox}>
          <PackageOpen size={36} />
          <span>Error al cargar las prearmadas. Intentá de nuevo.</span>
          <button className={styles.retryBtn} onClick={refetch}>
            Reintentar
          </button>
        </div>
      )}

      {/* Table */}
      {!error && (
        <div className={styles.tableWrapper}>
          <table className="table-tesla">
            <thead>
              <tr>
                <th>Código</th>
                <th>Combo</th>
                <th>Win11</th>
                <th>Memoria</th>
                <th>Disco</th>
                <th>Cubre SKUs</th>
                <th>Creado</th>
              </tr>
            </thead>
            <tbody>
              {groupByBase ? renderGroupedRows() : renderFlatRows()}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {!error && !loading && total > 0 && (
        <div className={styles.pagination}>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            ← Anterior
          </button>
          <span>
            Página {page} de {totalPages} &nbsp;·&nbsp; {total} resultados
          </span>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
          >
            Siguiente →
          </button>
        </div>
      )}
    </div>
  );
}

// ── Row sub-component ─────────────────────────────────────────────────────────

function ItemRow({ item }) {
  const parsed = item.parsed || {};
  const createdAt = item.created_at
    ? new Date(item.created_at).toLocaleDateString('es-AR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      })
    : '-';

  return (
    <tr>
      <td>{item.codigo}</td>
      <td>
        <div className={styles.itemCode}>{item.combo_item_code}</div>
        {item.combo_item_desc && (
          <div className={styles.itemDesc}>{item.combo_item_desc}</div>
        )}
      </td>
      <td>
        <WindowsBadge value={item.incluye_windows} />
      </td>
      <td>{parsed.memoria ?? <span className={styles.nullValue}>—</span>}</td>
      <td>{parsed.disco ?? <span className={styles.nullValue}>—</span>}</td>
      <td>
        {item.covers && item.covers.length > 0 ? (
          <div className={styles.covers}>
            {item.covers.map((c) => (
              <CoverChip key={c.item_id} cover={c} />
            ))}
          </div>
        ) : (
          <span className={styles.noCoverage}>Sin cobertura</span>
        )}
      </td>
      <td className={styles.dateCell}>{createdAt}</td>
    </tr>
  );
}

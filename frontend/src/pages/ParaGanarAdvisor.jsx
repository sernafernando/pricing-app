import { useEffect, useState } from 'react';
import { Target, RefreshCw, AlertTriangle, Link2 } from 'lucide-react';
import api from '../services/api';
import styles from './ParaGanarAdvisor.module.css';

/**
 * PARA GANAR advisor — MLA queue from local sandbox (read-only).
 * Intent: docs/para-ganar-pro-source-map.md
 */

function formatPrice(value) {
  if (value === null || value === undefined) return '—';
  return Number(value).toLocaleString('es-AR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

export default function ParaGanarAdvisor() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [q, setQ] = useState('');
  const [qInput, setQInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedMla, setSelectedMla] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const { data } = await api.get('/para-ganar/cola', {
          params: { page, page_size: pageSize, q: q || undefined },
        });
        if (cancelled) return;
        setItems(data.items || []);
        setTotal(data.total || 0);
        setSelectedMla((prev) => {
          if (!prev) return null;
          return (data.items || []).some((row) => row.mla === prev) ? prev : null;
        });
      } catch (err) {
        if (cancelled) return;
        if (err.response?.status === 403) {
          setError('No tenés permiso para ver esta sección (productos.ver).');
        } else {
          setError('No se pudo cargar la cola de publicaciones.');
        }
        setItems([]);
        setTotal(0);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [page, pageSize, q, reloadToken]);

  const selected = items.find((row) => row.mla === selectedMla) || null;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const applySearch = (event) => {
    event.preventDefault();
    setPage(1);
    setQ(qInput.trim());
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <Target className={styles.headerIcon} size={28} aria-hidden />
          <div>
            <h1 className={styles.title}>PARA GANAR</h1>
            <p className={styles.subtitle}>
              Advisor de precios por publicación — cola sandbox (solo lectura)
            </p>
          </div>
        </div>
        <form className={styles.searchForm} onSubmit={applySearch}>
          <input
            className={styles.searchInput}
            type="search"
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="Buscar MLA, código o título"
            aria-label="Buscar en la cola"
          />
          <button type="submit" className={styles.searchBtn}>
            Buscar
          </button>
        </form>
      </header>

      <section className={styles.toolbar} aria-label="Filtros de sugerencias">
        <button type="button" className={`${styles.chip} ${styles.chipActive}`} disabled>
          Pendientes
        </button>
        <button type="button" className={styles.chip} disabled>
          Aceptadas
        </button>
        <button type="button" className={styles.chip} disabled>
          Descartadas
        </button>
        <span className={styles.toolbarHint}>
          {total.toLocaleString('es-AR')} publicaciones activas · sugerencias aún no calculadas
        </span>
      </section>

      <div className={styles.layout}>
        <section className={styles.queue} aria-label="Cola de sugerencias">
          <div className={styles.panelTitle}>
            Cola (MLA)
            {!loading && (
              <span className={styles.panelMeta}>
                pág. {page}/{totalPages}
              </span>
            )}
          </div>

          {loading && (
            <div className={styles.loadingState}>
              <RefreshCw size={18} className={styles.spinner} aria-hidden />
              <span>Cargando publicaciones…</span>
            </div>
          )}

          {!loading && error && (
            <div className={styles.errorState}>
              <AlertTriangle size={18} aria-hidden />
              <span>{error}</span>
              <button
                type="button"
                className={styles.retryBtn}
                onClick={() => setReloadToken((n) => n + 1)}
              >
                Reintentar
              </button>
            </div>
          )}

          {!loading && !error && items.length === 0 && (
            <div className={styles.emptyState}>
              <p className={styles.emptyTitle}>Sin resultados</p>
              <p className={styles.emptyBody}>
                No hay publicaciones activas para este filtro en el sandbox.
              </p>
            </div>
          )}

          {!loading && !error && items.length > 0 && (
            <>
              <ul className={styles.queueList}>
                {items.map((row) => {
                  const isSelected = row.mla === selectedMla;
                  return (
                    <li key={row.mla}>
                      <button
                        type="button"
                        className={`${styles.queueRow} ${isSelected ? styles.queueRowSelected : ''}`}
                        onClick={() => setSelectedMla(row.mla)}
                        aria-pressed={isSelected}
                      >
                        <div className={styles.queueRowTop}>
                          <span className={styles.mla}>{row.mla}</span>
                          {row.sync_partner_mla && (
                            <span className={styles.syncBadge} title={`Par sync: ${row.sync_partner_mla}`}>
                              <Link2 size={12} aria-hidden />
                              Sync
                            </span>
                          )}
                          {row.catalog_listing && (
                            <span className={styles.catalogBadge}>Catálogo</span>
                          )}
                        </div>
                        <div className={styles.queueRowTitle}>
                          {row.titulo || row.producto_descripcion || 'Sin título'}
                        </div>
                        <div className={styles.queueRowMeta}>
                          <span>{row.codigo || '—'}</span>
                          <span>{row.lista_nombre || 'Sin lista'}</span>
                          <span className={styles.price}>$ {formatPrice(row.precio)}</span>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
              <div className={styles.pager}>
                <button
                  type="button"
                  className={styles.pagerBtn}
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  Anterior
                </button>
                <button
                  type="button"
                  className={styles.pagerBtn}
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Siguiente
                </button>
              </div>
            </>
          )}
        </section>

        <aside className={styles.detail} aria-label="Detalle de sugerencia">
          <div className={styles.panelTitle}>Detalle</div>
          {!selected && (
            <div className={styles.emptyState}>
              <p className={styles.emptyTitle}>Seleccioná un MLA</p>
              <p className={styles.emptyBody}>
                Catálogo, referente, markup y promoción sugerida van a aparecer acá.
                Por ahora solo mostramos los datos base de la publicación.
              </p>
            </div>
          )}
          {selected && (
            <dl className={styles.detailList}>
              <div>
                <dt>MLA</dt>
                <dd>{selected.mla}</dd>
              </div>
              <div>
                <dt>Código</dt>
                <dd>{selected.codigo || '—'}</dd>
              </div>
              <div>
                <dt>Item ERP</dt>
                <dd>{selected.item_id}</dd>
              </div>
              <div>
                <dt>Título ML</dt>
                <dd>{selected.titulo || '—'}</dd>
              </div>
              <div>
                <dt>Descripción ERP</dt>
                <dd>{selected.producto_descripcion || '—'}</dd>
              </div>
              <div>
                <dt>Lista / tipo</dt>
                <dd>{selected.lista_nombre || '—'}</dd>
              </div>
              <div>
                <dt>Precio lista</dt>
                <dd>$ {formatPrice(selected.precio)}</dd>
              </div>
              <div>
                <dt>Catálogo</dt>
                <dd>
                  {selected.catalog_listing
                    ? `Sí (${selected.catalog_product_id || 'sin id'})`
                    : 'No'}
                </dd>
              </div>
              <div>
                <dt>Par sync</dt>
                <dd>{selected.sync_partner_mla || '—'}</dd>
              </div>
              <div>
                <dt>Estado sugerencia</dt>
                <dd>{selected.suggestion_status}</dd>
              </div>
            </dl>
          )}
        </aside>
      </div>
    </div>
  );
}

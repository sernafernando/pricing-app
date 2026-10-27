import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Target, ListChecks, SlidersHorizontal } from 'lucide-react';
import api from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';
import ParaGanarQueue from '../components/paraGanar/ParaGanarQueue';
import ParaGanarAdvisorDetail from '../components/paraGanar/ParaGanarAdvisorDetail';
import ParaGanarCriteriosDetail from '../components/paraGanar/ParaGanarCriteriosDetail';
import ParaGanarScopeFilters from '../components/paraGanar/ParaGanarScopeFilters';
import styles from './ParaGanarAdvisor.module.css';

/**
 * PARA GANAR shell — tabs Advisor | Criterios share the sandbox MLA queue.
 * Intent: docs/para-ganar-pro-source-map.md
 */

const VISTA_ADVISOR = 'advisor';
const VISTA_CRITERIOS = 'criterios';
const PERMISO_PARA_GANAR = 'productos.ver';

function parseVista(raw) {
  return raw === VISTA_CRITERIOS ? VISTA_CRITERIOS : VISTA_ADVISOR;
}

function joinCsv(values) {
  return values.length > 0 ? values.join(',') : undefined;
}

export default function ParaGanarAdvisor() {
  const [searchParams, setSearchParams] = useSearchParams();
  const vista = parseVista(searchParams.get('vista'));
  const { tienePermiso } = usePermisos();
  const canAdvisor = tienePermiso(PERMISO_PARA_GANAR);
  const canCriterios = tienePermiso(PERMISO_PARA_GANAR);

  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [q, setQ] = useState('');
  const [qInput, setQInput] = useState('');
  const [marcas, setMarcas] = useState([]);
  const [subcategorias, setSubcategorias] = useState([]);
  const [pms, setPms] = useState([]);
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
          params: {
            page,
            page_size: pageSize,
            q: q || undefined,
            marcas: joinCsv(marcas),
            subcategorias: joinCsv(subcategorias),
            pms: joinCsv(pms),
          },
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
  }, [page, pageSize, q, marcas, subcategorias, pms, reloadToken]);

  const selected = items.find((row) => row.mla === selectedMla) || null;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const isCriterios = vista === VISTA_CRITERIOS;

  const setVista = (next) => {
    const params = new URLSearchParams(searchParams);
    if (next === VISTA_ADVISOR) {
      params.delete('vista');
    } else {
      params.set('vista', next);
    }
    setSearchParams(params, { replace: true });
  };

  const applySearch = (event) => {
    event.preventDefault();
    setPage(1);
    setQ(qInput.trim());
  };

  const setMarcasAndReset = (next) => {
    setPage(1);
    setMarcas(next);
  };
  const setSubcatsAndReset = (next) => {
    setPage(1);
    setSubcategorias(next);
  };
  const setPmsAndReset = (next) => {
    setPage(1);
    setPms(next);
  };
  const clearAlcance = () => {
    setPage(1);
    setMarcas([]);
    setSubcategorias([]);
    setPms([]);
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <Target className={styles.headerIcon} size={28} aria-hidden />
          <div>
            <h1 className={styles.title}>PARA GANAR</h1>
            <p className={styles.subtitle}>
              {isCriterios
                ? 'Criterios por MLA — config individual y masiva (WIP)'
                : 'Advisor de sugerencias — cola sandbox (solo lectura)'}
            </p>
          </div>
        </div>
        <form className={styles.searchForm} onSubmit={applySearch}>
          <input
            className={styles.searchInput}
            type="search"
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="Buscar MLA, código, título o marca"
            aria-label="Buscar en la cola"
          />
          <button type="submit" className={styles.searchBtn}>
            Buscar
          </button>
        </form>
      </header>

      <nav className={styles.tabs} aria-label="Secciones PARA GANAR">
        {canAdvisor && (
          <button
            type="button"
            className={`${styles.tab} ${!isCriterios ? styles.tabActive : ''}`}
            aria-current={!isCriterios ? 'page' : undefined}
            onClick={() => setVista(VISTA_ADVISOR)}
          >
            <ListChecks size={14} aria-hidden />
            Advisor
          </button>
        )}
        {canCriterios && (
          <button
            type="button"
            className={`${styles.tab} ${isCriterios ? styles.tabActive : ''}`}
            aria-current={isCriterios ? 'page' : undefined}
            onClick={() => setVista(VISTA_CRITERIOS)}
          >
            <SlidersHorizontal size={14} aria-hidden />
            Criterios
          </button>
        )}
      </nav>

      {(canAdvisor || canCriterios) && (
        <ParaGanarScopeFilters
          marcas={marcas}
          subcategorias={subcategorias}
          pms={pms}
          onMarcasChange={setMarcasAndReset}
          onSubcategoriasChange={setSubcatsAndReset}
          onPmsChange={setPmsAndReset}
          onClear={clearAlcance}
        />
      )}

      <section
        className={styles.toolbar}
        aria-label={isCriterios ? 'Acciones de criterios' : 'Filtros de sugerencias'}
      >
        {!isCriterios && canAdvisor && (
          <>
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
              {total.toLocaleString('es-AR')} publicaciones · sugerencias aún no calculadas
            </span>
          </>
        )}
        {isCriterios && canCriterios && (
          <>
            <button type="button" className={styles.bulkBtn} disabled title="Próximo: aplicar al filtro actual">
              Aplicar criterios al filtro
            </button>
            <span className={styles.toolbarHint}>
              {total.toLocaleString('es-AR')} MLAs en alcance
            </span>
          </>
        )}
      </section>

      <div className={styles.layout}>
        <ParaGanarQueue
          mode={isCriterios ? 'criterios' : 'advisor'}
          items={items}
          loading={loading}
          error={error}
          page={page}
          totalPages={totalPages}
          selectedMla={selectedMla}
          onSelect={setSelectedMla}
          onRetry={() => setReloadToken((n) => n + 1)}
          onPrevPage={() => setPage((p) => Math.max(1, p - 1))}
          onNextPage={() => setPage((p) => p + 1)}
        />
        {isCriterios ? (
          <ParaGanarCriteriosDetail selected={selected} />
        ) : (
          <ParaGanarAdvisorDetail selected={selected} />
        )}
      </div>
    </div>
  );
}

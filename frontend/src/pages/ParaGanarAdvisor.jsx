import { useSearchParams } from 'react-router-dom';
import { Target, ListChecks, SlidersHorizontal } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import useParaGanarCola from '../hooks/useParaGanarCola';
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

export default function ParaGanarAdvisor() {
  const [searchParams, setSearchParams] = useSearchParams();
  const vista = parseVista(searchParams.get('vista'));
  const { tienePermiso } = usePermisos();
  const canAdvisor = tienePermiso(PERMISO_PARA_GANAR);
  const canCriterios = tienePermiso(PERMISO_PARA_GANAR);
  const cola = useParaGanarCola(50);

  const isCriterios = vista === VISTA_CRITERIOS;
  const canCurrent = isCriterios ? canCriterios : canAdvisor;

  const setVista = (next) => {
    const params = new URLSearchParams(searchParams);
    if (next === VISTA_ADVISOR) {
      params.delete('vista');
    } else {
      params.set('vista', next);
    }
    setSearchParams(params, { replace: true });
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
        <form className={styles.searchForm} onSubmit={cola.applySearch}>
          <input
            className={styles.searchInput}
            type="search"
            value={cola.qInput}
            onChange={(e) => cola.setQInput(e.target.value)}
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

      {canCurrent && (
        <ParaGanarScopeFilters
          marcas={cola.marcas}
          subcategorias={cola.subcategorias}
          pms={cola.pms}
          tiposPublicacion={cola.tiposPublicacion}
          pricelists={cola.pricelists}
          tiendas={cola.tiendas}
          ean={cola.eanInput}
          catalogProductId={cola.catalogInput}
          onMarcasChange={cola.setMarcas}
          onSubcategoriasChange={cola.setSubcategorias}
          onPmsChange={cola.setPms}
          onTiposPublicacionChange={cola.setTiposPublicacion}
          onPricelistsChange={cola.setPricelists}
          onTiendasChange={cola.setTiendas}
          onEanChange={cola.setEanInput}
          onCatalogProductIdChange={cola.setCatalogInput}
          onClear={cola.clearAlcance}
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
              {cola.total.toLocaleString('es-AR')} publicaciones · sugerencias aún no calculadas
            </span>
          </>
        )}
        {isCriterios && canCriterios && (
          <>
            <button type="button" className={styles.bulkBtn} disabled title="Próximo: aplicar al filtro actual">
              Aplicar criterios al filtro
            </button>
            <span className={styles.toolbarHint}>
              {cola.total.toLocaleString('es-AR')} MLAs en alcance
            </span>
          </>
        )}
      </section>

      {canCurrent && (
        <div className={styles.layout}>
          <ParaGanarQueue
            mode={isCriterios ? 'criterios' : 'advisor'}
            items={cola.items}
            loading={cola.loading}
            error={cola.error}
            page={cola.page}
            totalPages={cola.totalPages}
            selectedMla={cola.selectedMla}
            onSelect={cola.setSelectedMla}
            onRetry={cola.reload}
            onPrevPage={() => cola.setPage((p) => Math.max(1, p - 1))}
            onNextPage={() => cola.setPage((p) => p + 1)}
          />
          {isCriterios ? (
            <ParaGanarCriteriosDetail selected={cola.selected} />
          ) : (
            <ParaGanarAdvisorDetail selected={cola.selected} />
          )}
        </div>
      )}
    </div>
  );
}

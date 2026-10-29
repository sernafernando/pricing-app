import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Target, ListChecks, SlidersHorizontal, CalendarClock } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import useParaGanarCola from '../hooks/useParaGanarCola';
import api from '../services/api';
import ParaGanarQueue from '../components/paraGanar/ParaGanarQueue';
import ParaGanarAdvisorDetail from '../components/paraGanar/ParaGanarAdvisorDetail';
import ParaGanarCriteriosDetail from '../components/paraGanar/ParaGanarCriteriosDetail';
import ParaGanarMassApplyModal from '../components/paraGanar/ParaGanarMassApplyModal';
import ParaGanarPeriodicidadPanel from '../components/paraGanar/ParaGanarPeriodicidadPanel';
import ParaGanarScopeFilters from '../components/paraGanar/ParaGanarScopeFilters';
import {
  parseVista,
  VISTA_ADVISOR,
  VISTA_CRITERIOS,
  VISTA_PERIODICIDAD,
} from '../components/paraGanar/paraGanarVistas';
import styles from './ParaGanarAdvisor.module.css';

/**
 * PARA GANAR shell — tabs Advisor | Criterios | Periodicidad.
 * Intent: docs/para-ganar-pro-source-map.md
 */

const PERMISO_PARA_GANAR = 'productos.ver';

function subtitleForVista(vista) {
  if (vista === VISTA_CRITERIOS) {
    return 'Criterios por MLA — individual y masivo al filtro';
  }
  if (vista === VISTA_PERIODICIDAD) {
    return 'Gestionar periodicidad — suscripción por EAN';
  }
  return 'Advisor de sugerencias — cola sandbox (solo lectura)';
}

function formatConsultarError(err) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (err?.response?.status === 403) return 'Requiere productos.editar_precios';
  return 'No se pudo encolar la consulta del alcance filtrado';
}

export default function ParaGanarAdvisor() {
  const [searchParams, setSearchParams] = useSearchParams();
  const vista = parseVista(searchParams.get('vista'));
  const { tienePermiso } = usePermisos();
  const canAdvisor = tienePermiso(PERMISO_PARA_GANAR);
  const canCriterios = tienePermiso(PERMISO_PARA_GANAR);
  const canPeriodicidad = tienePermiso(PERMISO_PARA_GANAR);
  const canWriteCriteria = tienePermiso('productos.editar_precios');
  const cola = useParaGanarCola(50);
  const [massOpen, setMassOpen] = useState(false);
  const [massFeedback, setMassFeedback] = useState(null);
  const [evaluandoFiltro, setEvaluandoFiltro] = useState(false);
  const [evaluarFeedback, setEvaluarFeedback] = useState(null);
  const [evaluarError, setEvaluarError] = useState(null);

  const consultarFiltrados = async () => {
    if (evaluandoFiltro || cola.loading || cola.total <= 0 || !canWriteCriteria) return;
    setEvaluandoFiltro(true);
    setEvaluarError(null);
    setEvaluarFeedback(null);
    try {
      const { data } = await api.post('/para-ganar/consulta-jobs', null, {
        params: cola.scopeQueryParams,
      });
      setEvaluarFeedback(data);
    } catch (err) {
      setEvaluarError(formatConsultarError(err));
    } finally {
      setEvaluandoFiltro(false);
    }
  };

  const isAdvisor = vista === VISTA_ADVISOR;
  const isCriterios = vista === VISTA_CRITERIOS;
  const isPeriodicidad = vista === VISTA_PERIODICIDAD;
  const canCurrent = isCriterios
    ? canCriterios
    : isPeriodicidad
      ? canPeriodicidad
      : canAdvisor;

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
            <p className={styles.subtitle}>{subtitleForVista(vista)}</p>
          </div>
        </div>
        {!isPeriodicidad && (
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
        )}
      </header>

      <nav className={styles.tabs} aria-label="Secciones PARA GANAR">
        {canAdvisor && (
          <button
            type="button"
            className={`${styles.tab} ${isAdvisor ? styles.tabActive : ''}`}
            aria-current={isAdvisor ? 'page' : undefined}
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
        {canPeriodicidad && (
          <button
            type="button"
            className={`${styles.tab} ${isPeriodicidad ? styles.tabActive : ''}`}
            aria-current={isPeriodicidad ? 'page' : undefined}
            onClick={() => setVista(VISTA_PERIODICIDAD)}
          >
            <CalendarClock size={14} aria-hidden />
            Periodicidad
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
          costoUsdMin={cola.costoUsdMinInput}
          costoUsdMax={cola.costoUsdMaxInput}
          incluirTradicionalSync={cola.incluirTradicionalSync}
          onIncluirTradicionalSyncChange={cola.setIncluirTradicionalSync}
          criteriosAplicados={cola.criteriosAplicados}
          onCriteriosAplicadosChange={cola.setCriteriosAplicados}
          onMarcasChange={cola.setMarcas}
          onSubcategoriasChange={cola.setSubcategorias}
          onPmsChange={cola.setPms}
          onTiposPublicacionChange={cola.setTiposPublicacion}
          onPricelistsChange={cola.setPricelists}
          onTiendasChange={cola.setTiendas}
          onEanChange={cola.setEanInput}
          onCatalogProductIdChange={cola.setCatalogInput}
          onCostoUsdMinChange={cola.setCostoUsdMinInput}
          onCostoUsdMaxChange={cola.setCostoUsdMaxInput}
          onClear={cola.clearAlcance}
        />
      )}

      {!isPeriodicidad && (
        <section
          className={styles.toolbar}
          aria-label={isCriterios ? 'Acciones de criterios' : 'Filtros de sugerencias'}
        >
          {isAdvisor && canAdvisor && (
            <>
              <button
                type="button"
                className={styles.bulkBtn}
                disabled={evaluandoFiltro || cola.loading || cola.total <= 0 || !canWriteCriteria}
                title={
                  !canWriteCriteria
                    ? 'Requiere productos.editar_precios'
                    : cola.total <= 0
                      ? 'No hay MLAs en el alcance'
                      : 'Encola refresh de competencia + evaluación P5 (worker ML)'
                }
                onClick={consultarFiltrados}
              >
                {evaluandoFiltro ? 'Encolando…' : 'Consultar filtrados'}
              </button>
              <button
                type="button"
                className={`${styles.chip} ${cola.revisionEstado == null ? styles.chipActive : ''}`}
                onClick={() => cola.setRevisionEstado(null)}
              >
                Todos
              </button>
              <button
                type="button"
                className={`${styles.chip} ${
                  cola.revisionEstado === 'pendiente' ? styles.chipActive : ''
                }`}
                onClick={() => cola.setRevisionEstado('pendiente')}
              >
                Pendiente de revisión
              </button>
              <button
                type="button"
                className={`${styles.chip} ${
                  cola.revisionEstado === 'sin_novedades' ? styles.chipActive : ''
                }`}
                onClick={() => cola.setRevisionEstado('sin_novedades')}
              >
                Sin novedades
              </button>
              <span className={styles.toolbarHint}>
                {cola.total.toLocaleString('es-AR')} publicaciones · estados los marca el motor (P5)
                {evaluarFeedback
                  ? ` · consulta #${evaluarFeedback.job_id} encolada (${Number(evaluarFeedback.total_count || 0).toLocaleString('es-AR')} MLAs)`
                  : ''}
                {evaluarError ? ` · ${evaluarError}` : ''}
              </span>
            </>
          )}
          {isCriterios && canCriterios && (
            <>
              <button
                type="button"
                className={styles.bulkBtn}
                disabled={cola.loading || cola.total <= 0 || !canWriteCriteria}
                title={
                  !canWriteCriteria
                    ? 'Requiere productos.editar_precios'
                    : cola.total <= 0
                      ? 'No hay MLAs en el alcance'
                      : 'Pisa markup/TOP/flags en todas las MLAs del filtro'
                }
                onClick={() => {
                  setMassFeedback(null);
                  setMassOpen(true);
                }}
              >
                Aplicar criterios al filtro
              </button>
              <span className={styles.toolbarHint}>
                {cola.total.toLocaleString('es-AR')} MLAs en alcance
                {massFeedback
                  ? ` · aplicadas ${massFeedback.applied.toLocaleString('es-AR')} (${massFeedback.created} nuevas, ${massFeedback.updated} actualizadas)`
                  : ''}
              </span>
            </>
          )}
        </section>
      )}

      {isCriterios && (
        <ParaGanarMassApplyModal
          isOpen={massOpen}
          onClose={() => setMassOpen(false)}
          scopeTotal={cola.total}
          scopeQueryParams={cola.scopeQueryParams}
          onApplied={(result) => {
            setMassFeedback(result);
            cola.reload();
          }}
        />
      )}

      {canCurrent && isPeriodicidad && (
        <ParaGanarPeriodicidadPanel scopeQueryParams={cola.scopeQueryParams} />
      )}

      {canCurrent && !isPeriodicidad && (
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
            <ParaGanarCriteriosDetail
              selected={cola.selected}
              onCriteriaChanged={cola.reload}
            />
          ) : (
            <ParaGanarAdvisorDetail selected={cola.selected} />
          )}
        </div>
      )}
    </div>
  );
}

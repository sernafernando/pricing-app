import { useState, useEffect } from 'react';
import { useConsultasRanking } from '../hooks/useConsultasRanking';
import { getRankingFacets } from '../services/consultasService';
import RankingFilters from '../components/consultas/RankingFilters';
import RankingTable from '../components/consultas/RankingTable';
import styles from './ConsultasRanking.module.css';

const EMPTY_FACETS = { marcas: [], categorias: [], pms: [], depositos: [] };

function useFacets() {
  const [facets, setFacets] = useState(EMPTY_FACETS);
  const [facetsLoading, setFacetsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setFacetsLoading(true);
    getRankingFacets()
      .then((data) => {
        if (!cancelled) setFacets(data);
      })
      .catch((err) => {
        // Non-fatal: filters fall back to FALLBACK_DEPOSITOS in RankingFilters
        console.error('[ConsultasRanking] Failed to load facets:', err);
      })
      .finally(() => {
        if (!cancelled) setFacetsLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  return { facets, facetsLoading };
}

// Access is enforced by ProtectedRoute permiso="consultas.ver_ranking" in the router.
export default function ConsultasRanking() {
  return <ConsultasRankingContent />;
}

function ConsultasRankingContent() {
  const { facets, facetsLoading } = useFacets();
  const {
    items,
    total,
    loading,
    error,
    marca,
    setMarca,
    categoria,
    setCategoria,
    pm,
    setPm,
    storIds,
    setStorIds,
    ventanaDias,
    setVentanaDias,
    incluirSinStock,
    setIncluirSinStock,
    incluirCombos,
    setIncluirCombos,
    sort,
    toggleSort,
    page,
    pageSize,
    totalPages,
    goToPage,
  } = useConsultasRanking();

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Ranking de productos</h1>
        {total > 0 && !loading && (
          <span className={styles.totalBadge}>
            {total.toLocaleString('es-AR')} productos
          </span>
        )}
      </header>

      <RankingFilters
        marca={marca}
        onMarcaChange={setMarca}
        categoria={categoria}
        onCategoriaChange={setCategoria}
        pm={pm}
        onPmChange={setPm}
        storIds={storIds}
        onStorIdsChange={setStorIds}
        ventanaDias={ventanaDias}
        onVentanaDiasChange={setVentanaDias}
        incluirSinStock={incluirSinStock}
        onIncluirSinStockChange={setIncluirSinStock}
        incluirCombos={incluirCombos}
        onIncluirCombosChange={setIncluirCombos}
        facets={facets}
        facetsLoading={facetsLoading}
      />

      <RankingTable
        items={items}
        loading={loading}
        error={error}
        sort={sort}
        onSort={toggleSort}
        page={page}
        totalPages={totalPages}
        total={total}
        pageSize={pageSize}
        onGoToPage={goToPage}
      />
    </div>
  );
}

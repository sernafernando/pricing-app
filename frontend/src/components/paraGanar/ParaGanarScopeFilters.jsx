import { X } from 'lucide-react';
import { useTiendasOficiales } from '../../hooks/useTiendasOficiales';
import useParaGanarAlcanceOpciones from '../../hooks/useParaGanarAlcanceOpciones';
import { STORE_NONE } from '../../constants/tiendasOficiales';
import ScopeMultiSelect from './ScopeMultiSelect';
import ScopeTextFilter from './ScopeTextFilter';
import styles from './ParaGanarScopeFilters.module.css';

/**
 * Shared scope filters for Advisor and Criterios.
 * Facet options cascade from GET /para-ganar/alcance-opciones with active filters.
 */

export default function ParaGanarScopeFilters({
  marcas,
  subcategorias,
  pms,
  tiposPublicacion,
  pricelists,
  tiendas,
  ean,
  catalogProductId,
  onMarcasChange,
  onSubcategoriasChange,
  onPmsChange,
  onTiposPublicacionChange,
  onPricelistsChange,
  onTiendasChange,
  onEanChange,
  onCatalogProductIdChange,
  onClear,
}) {
  const { opciones, loading, loadError, retry } = useParaGanarAlcanceOpciones({
    marcas,
    subcategorias,
    pms,
    tiposPublicacion,
    pricelists,
    tiendas,
    ean,
    catalogProductId,
    onMarcasChange,
    onSubcategoriasChange,
    onPmsChange,
    onTiposPublicacionChange,
    onPricelistsChange,
  });
  const { grupos: tiendasGrupos } = useTiendasOficiales();
  const tiendaOptions = [
    ...tiendasGrupos,
    { value: STORE_NONE, label: 'Sin tienda oficial', ids: [STORE_NONE] },
  ];

  const hasActive =
    marcas.length > 0 ||
    subcategorias.length > 0 ||
    pms.length > 0 ||
    tiposPublicacion.length > 0 ||
    pricelists.length > 0 ||
    tiendas.length > 0 ||
    Boolean(ean.trim()) ||
    Boolean(catalogProductId.trim());

  const emptyHint = (emptyLabel) => {
    if (loading) return 'Cargando…';
    if (loadError) return loadError;
    return emptyLabel;
  };

  const disabledLists = loading || Boolean(loadError);

  return (
    <div className={styles.bar} aria-label="Filtros de alcance">
      {loadError && (
        <p className={styles.loadError} role="alert">
          {loadError}{' '}
          <button type="button" className={styles.retryBtn} onClick={retry}>
            Reintentar
          </button>
        </p>
      )}
      <ScopeMultiSelect
        label="Tipo"
        options={opciones.tipos_publicacion}
        selected={tiposPublicacion}
        onChange={onTiposPublicacionChange}
        getKey={(row) => row.id}
        getLabel={(row) => row.nombre}
        emptyHint={emptyHint('Sin tipos en el alcance')}
        disabled={disabledLists}
      />
      <ScopeMultiSelect
        label="Lista"
        options={opciones.listas_precios}
        selected={pricelists}
        onChange={onPricelistsChange}
        getKey={(row) => row.id}
        getLabel={(row) => row.nombre}
        emptyHint={emptyHint('Sin listas en el alcance')}
        disabled={disabledLists}
      />
      <ScopeMultiSelect
        label="Tienda"
        options={tiendaOptions}
        selected={tiendas}
        onChange={onTiendasChange}
        getKey={(row) => row.value}
        getLabel={(row) => row.label}
        emptyHint="Sin tiendas oficiales configuradas"
        disabled={false}
      />
      <ScopeMultiSelect
        label="Marca"
        options={opciones.marcas}
        selected={marcas}
        onChange={onMarcasChange}
        getKey={(marca) => marca}
        getLabel={(marca) => marca}
        emptyHint={emptyHint('Sin marcas en el alcance')}
        disabled={disabledLists}
      />
      <ScopeMultiSelect
        label="Subcategoría"
        options={opciones.subcategorias}
        selected={subcategorias}
        onChange={onSubcategoriasChange}
        getKey={(row) => row.id}
        getLabel={(row) => row.nombre}
        emptyHint={emptyHint('Sin subcategorías en el alcance')}
        disabled={disabledLists}
      />
      <ScopeMultiSelect
        label="PM"
        options={opciones.pms}
        selected={pms}
        onChange={onPmsChange}
        getKey={(row) => row.id}
        getLabel={(row) => row.nombre}
        emptyHint={emptyHint('Sin PMs en el alcance')}
        disabled={disabledLists}
      />
      <ScopeTextFilter
        label="EAN"
        value={ean}
        onChange={onEanChange}
        placeholder="EAN / código"
        disabled={false}
      />
      <ScopeTextFilter
        label="MLA catálogo"
        value={catalogProductId}
        onChange={onCatalogProductIdChange}
        placeholder="MLA catálogo"
        disabled={false}
      />
      {hasActive && (
        <button type="button" className={styles.clearAll} onClick={onClear}>
          <X size={14} aria-hidden />
          Limpiar alcance
        </button>
      )}
    </div>
  );
}

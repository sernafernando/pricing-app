import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import api from '../../services/api';
import { useTiendasOficiales } from '../../hooks/useTiendasOficiales';
import { STORE_NONE } from '../../constants/tiendasOficiales';
import ScopeMultiSelect from './ScopeMultiSelect';
import ScopeTextFilter from './ScopeTextFilter';
import styles from './ParaGanarScopeFilters.module.css';

/**
 * Shared scope filters for Advisor and Criterios.
 * Options: GET /para-ganar/alcance-opciones + useTiendasOficiales (Productos).
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
  const [opciones, setOpciones] = useState({
    marcas: [],
    subcategorias: [],
    pms: [],
    tipos_publicacion: [],
    listas_precios: [],
  });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const { grupos: tiendasGrupos } = useTiendasOficiales();
  const tiendaOptions = [
    ...tiendasGrupos,
    { value: STORE_NONE, label: 'Sin tienda oficial', ids: [STORE_NONE] },
  ];

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setLoadError(null);
      try {
        const { data } = await api.get('/para-ganar/alcance-opciones');
        if (cancelled) return;
        setOpciones({
          marcas: data.marcas || [],
          subcategorias: data.subcategorias || [],
          pms: data.pms || [],
          tipos_publicacion: data.tipos_publicacion || [],
          listas_precios: data.listas_precios || [],
        });
      } catch (err) {
        if (cancelled) return;
        setOpciones({
          marcas: [],
          subcategorias: [],
          pms: [],
          tipos_publicacion: [],
          listas_precios: [],
        });
        if (err.response?.status === 403) {
          setLoadError('No tenés permiso para cargar filtros de alcance.');
        } else {
          setLoadError('No se pudieron cargar las opciones de alcance.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

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
          <button
            type="button"
            className={styles.retryBtn}
            onClick={() => setReloadToken((n) => n + 1)}
          >
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
        emptyHint={emptyHint('Sin tipos')}
        disabled={disabledLists}
      />
      <ScopeMultiSelect
        label="Lista"
        options={opciones.listas_precios}
        selected={pricelists}
        onChange={onPricelistsChange}
        getKey={(row) => row.id}
        getLabel={(row) => row.nombre}
        emptyHint={emptyHint('Sin listas en la cola')}
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
        emptyHint={emptyHint('Sin marcas en la cola')}
        disabled={disabledLists}
      />
      <ScopeMultiSelect
        label="Subcategoría"
        options={opciones.subcategorias}
        selected={subcategorias}
        onChange={onSubcategoriasChange}
        getKey={(row) => row.id}
        getLabel={(row) => row.nombre}
        emptyHint={emptyHint('Sin subcategorías en la cola')}
        disabled={disabledLists}
      />
      <ScopeMultiSelect
        label="PM"
        options={opciones.pms}
        selected={pms}
        onChange={onPmsChange}
        getKey={(row) => row.id}
        getLabel={(row) => row.nombre}
        emptyHint={emptyHint('Sin PMs asignados (sandbox)')}
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

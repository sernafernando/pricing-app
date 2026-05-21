import { useState, useEffect } from 'react';
import {
  Download,
  Trash2,
  X,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  SlidersHorizontal,
  Users,
  Check,
  AlertCircle,
} from 'lucide-react';
import { useDebounce } from '../hooks/useDebounce';
import { useQueryFilters } from '../hooks/useQueryFilters';
import styles from './Clientes.module.css';
import api from '../services/api';
import ModalDetalleCliente from '../components/ModalDetalleCliente';
import SearchInput from '../components/SearchInput';

export default function Clientes() {
  const [clientes, setClientes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalClientes, setTotalClientes] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [error, setError] = useState(null);

  // Filtros disponibles
  const [provincias, setProvincias] = useState([]);
  const [condicionesFiscales, setCondicionesFiscales] = useState([]);
  const [sucursales, setSucursales] = useState([]);
  const [vendedores, setVendedores] = useState([]);

  // Advanced filters toggle
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Query params
  const { getFilter, updateFilters } = useQueryFilters({
    search: '',
    page: 1,
    page_size: 50,
    state_id: '',
    fc_id: '',
    bra_id: '',
    sm_id: '',
    solo_activos: true,
    con_ml: '',
    con_email: '',
    con_telefono: '',
    cust_id_desde: '',
    cust_id_hasta: ''
  }, {
    page: 'number',
    page_size: 'number',
    solo_activos: 'boolean'
  });

  const searchInput = getFilter('search');
  const page = getFilter('page');
  const pageSize = getFilter('page_size');
  const filtroProvinciaId = getFilter('state_id');
  const filtroFiscalId = getFilter('fc_id');
  const filtroSucursalId = getFilter('bra_id');
  const filtroVendedorId = getFilter('sm_id');
  const filtroSoloActivos = getFilter('solo_activos');
  const filtroConML = getFilter('con_ml');
  const filtroConEmail = getFilter('con_email');
  const filtroConTelefono = getFilter('con_telefono');
  const filtroCustIdDesde = getFilter('cust_id_desde');
  const filtroCustIdHasta = getFilter('cust_id_hasta');

  // Modal detalle
  const [clienteSeleccionado, setClienteSeleccionado] = useState(null);
  const [mostrarModalDetalle, setMostrarModalDetalle] = useState(false);

  // Exportación
  const [mostrarModalExport, setMostrarModalExport] = useState(false);
  const [camposDisponibles, setCamposDisponibles] = useState([]);
  const [camposSeleccionados, setCamposSeleccionados] = useState([]);
  const [exportando, setExportando] = useState(false);

  const debouncedSearch = useDebounce(searchInput, 500);

  // Cargar filtros iniciales
  useEffect(() => {
    cargarFiltros();
    cargarCamposDisponibles();
  }, []);

  // Cargar clientes cuando cambian los filtros
  useEffect(() => {
    cargarClientes();
    // cargarClientes se recrea cada render — recargar solo cuando cambian paginación/filtros
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, debouncedSearch, filtroProvinciaId, filtroFiscalId, filtroSucursalId, filtroVendedorId, filtroSoloActivos, filtroConML, filtroConEmail, filtroConTelefono, filtroCustIdDesde, filtroCustIdHasta]);

  const cargarFiltros = async () => {
    try {
      const [provRes, fiscalRes, sucRes, vendRes] = await Promise.all([
        api.get('/clientes/filtros/provincias'),
        api.get('/clientes/filtros/condiciones-fiscales'),
        api.get('/clientes/filtros/sucursales'),
        api.get('/clientes/filtros/vendedores')
      ]);

      setProvincias(provRes.data);
      setCondicionesFiscales(fiscalRes.data);
      setSucursales(sucRes.data);
      setVendedores(vendRes.data);
    } catch {
      // Filtros no disponibles — no es crítico
    }
  };

  const cargarCamposDisponibles = async () => {
    try {
      const response = await api.get('/clientes/campos-disponibles');
      setCamposDisponibles(response.data.campos);
      const camposDefault = response.data.campos
        .filter(c => ['cust_id', 'cust_name', 'cust_taxnumber', 'cust_email', 'cust_phone1', 'state_desc', 'fc_desc'].includes(c.key))
        .map(c => c.key);
      setCamposSeleccionados(camposDefault);
    } catch {
      // No es crítico
    }
  };

  const cargarClientes = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString()
      });

      if (debouncedSearch) params.append('search', debouncedSearch);
      if (filtroProvinciaId) params.append('state_id', filtroProvinciaId);
      if (filtroFiscalId) params.append('fc_id', filtroFiscalId);
      if (filtroSucursalId) params.append('bra_id', filtroSucursalId);
      if (filtroVendedorId) params.append('sm_id', filtroVendedorId);
      if (filtroSoloActivos !== '') params.append('solo_activos', filtroSoloActivos.toString());
      if (filtroConML !== '') params.append('con_ml', filtroConML);
      if (filtroConEmail !== '') params.append('con_email', filtroConEmail);
      if (filtroConTelefono !== '') params.append('con_telefono', filtroConTelefono);
      if (filtroCustIdDesde) params.append('cust_id_desde', filtroCustIdDesde);
      if (filtroCustIdHasta) params.append('cust_id_hasta', filtroCustIdHasta);

      const response = await api.get(`/clientes?${params}`);
      setClientes(response.data.clientes);
      setTotalClientes(response.data.total);
      setTotalPages(response.data.total_pages);
    } catch {
      setError('Error al cargar clientes');
    } finally {
      setLoading(false);
    }
  };

  const handleExportar = async () => {
    if (camposSeleccionados.length === 0) return;

    setExportando(true);
    try {
      const payload = {
        campos: camposSeleccionados,
        search: debouncedSearch || null,
        state_id: filtroProvinciaId ? parseInt(filtroProvinciaId) : null,
        fc_id: filtroFiscalId ? parseInt(filtroFiscalId) : null,
        bra_id: filtroSucursalId ? parseInt(filtroSucursalId) : null,
        sm_id: filtroVendedorId ? parseInt(filtroVendedorId) : null,
        solo_activos: filtroSoloActivos !== '' ? filtroSoloActivos : null,
        con_ml: filtroConML !== '' ? (filtroConML === 'true') : null,
        con_email: filtroConEmail !== '' ? (filtroConEmail === 'true') : null,
        con_telefono: filtroConTelefono !== '' ? (filtroConTelefono === 'true') : null,
        cust_id_desde: filtroCustIdDesde ? parseInt(filtroCustIdDesde) : null,
        cust_id_hasta: filtroCustIdHasta ? parseInt(filtroCustIdHasta) : null
      };

      const response = await api.post('/clientes/exportar', payload, {
        responseType: 'blob'
      });

      const url = window.URL.createObjectURL(new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      }));
      const link = document.createElement('a');
      link.href = url;
      const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-');
      link.setAttribute('download', `clientes_${timestamp}.xlsx`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);

      setMostrarModalExport(false);
    } catch {
      setError('Error al exportar clientes');
    } finally {
      setExportando(false);
    }
  };

  const toggleCampo = (key) => {
    setCamposSeleccionados(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
    );
  };

  // Helper para labels de filtros activos
  const getProvinciaLabel = (id) => provincias.find(p => String(p.state_id) === String(id))?.state_desc;
  const getFiscalLabel = (id) => condicionesFiscales.find(c => String(c.fc_id) === String(id))?.fc_desc;
  const getSucursalLabel = (id) => sucursales.find(s => String(s.bra_id) === String(id))?.bra_desc;
  const getVendedorLabel = (id) => vendedores.find(v => String(v.sm_id) === String(id))?.sm_name;

  // Chips de filtros activos
  const activeChips = [];
  if (filtroProvinciaId) activeChips.push({ key: 'state_id', label: getProvinciaLabel(filtroProvinciaId) || filtroProvinciaId });
  if (filtroFiscalId) activeChips.push({ key: 'fc_id', label: getFiscalLabel(filtroFiscalId) || filtroFiscalId });
  if (filtroSucursalId) activeChips.push({ key: 'bra_id', label: getSucursalLabel(filtroSucursalId) || filtroSucursalId });
  if (filtroVendedorId) activeChips.push({ key: 'sm_id', label: getVendedorLabel(filtroVendedorId) || filtroVendedorId });
  if (filtroConML === 'true') activeChips.push({ key: 'con_ml', label: 'Con ML' });
  if (filtroConML === 'false') activeChips.push({ key: 'con_ml', label: 'Sin ML' });
  if (filtroConEmail === 'true') activeChips.push({ key: 'con_email', label: 'Con Email' });
  if (filtroConEmail === 'false') activeChips.push({ key: 'con_email', label: 'Sin Email' });
  if (filtroConTelefono === 'true') activeChips.push({ key: 'con_telefono', label: 'Con Tel' });
  if (filtroConTelefono === 'false') activeChips.push({ key: 'con_telefono', label: 'Sin Tel' });
  if (!filtroSoloActivos) activeChips.push({ key: 'solo_activos', label: 'Incluye inactivos' });
  if (filtroCustIdDesde) activeChips.push({ key: 'cust_id_desde', label: `ID ≥ ${filtroCustIdDesde}` });
  if (filtroCustIdHasta) activeChips.push({ key: 'cust_id_hasta', label: `ID ≤ ${filtroCustIdHasta}` });

  const removeChip = (key) => {
    const resetValue = key === 'solo_activos' ? true : '';
    updateFilters({ [key]: resetValue, page: 1 });
  };

  const limpiarFiltros = () => {
    updateFilters({
      search: '',
      state_id: '',
      fc_id: '',
      bra_id: '',
      sm_id: '',
      solo_activos: true,
      con_ml: '',
      con_email: '',
      con_telefono: '',
      cust_id_desde: '',
      cust_id_hasta: '',
      page: 1
    });
  };

  const handleVerDetalle = async (cliente) => {
    try {
      const response = await api.get(
        `/clientes/${cliente.cust_id}?comp_id=${cliente.comp_id}`
      );
      setClienteSeleccionado(response.data);
      setMostrarModalDetalle(true);
    } catch {
      setError('Error al cargar detalle del cliente');
    }
  };

  const handleActualizarCliente = (clienteActualizado) => {
    setClientes(prev => prev.map(c =>
      c.cust_id === clienteActualizado.cust_id && c.comp_id === clienteActualizado.comp_id
        ? clienteActualizado
        : c
    ));
    setClienteSeleccionado(clienteActualizado);
  };

  const hasAdvancedFilters = filtroConML || filtroConEmail || filtroConTelefono || filtroCustIdDesde || filtroCustIdHasta || !filtroSoloActivos;

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Users size={22} />
          <h1>Clientes</h1>
          {totalClientes > 0 && (
            <span className={styles.totalBadge}>
              {totalClientes.toLocaleString()}
            </span>
          )}
        </div>
        <div className={styles.headerActions}>
          <button
            className={styles.btnExport}
            onClick={() => setMostrarModalExport(true)}
          >
            <Download size={14} />
            Exportar
          </button>
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className={styles.errorMessage}>
          <AlertCircle size={16} />
          {error}
          <button onClick={() => setError(null)} aria-label="Cerrar error">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Main filters bar */}
      <div className={styles.filters}>
        <SearchInput
          value={searchInput}
          onChange={(val) => updateFilters({ search: val, page: 1 })}
          placeholder="Buscar por nombre, CUIT, email, ciudad o N° cliente..."
          className={styles.searchBox}
        />

        <select
          value={filtroProvinciaId}
          onChange={(e) => updateFilters({ state_id: e.target.value, page: 1 })}
          className={styles.filterSelect}
        >
          <option value="">Provincia</option>
          {provincias.map(p => (
            <option key={p.state_id} value={p.state_id}>
              {p.state_desc}
            </option>
          ))}
        </select>

        <select
          value={filtroFiscalId}
          onChange={(e) => updateFilters({ fc_id: e.target.value, page: 1 })}
          className={styles.filterSelect}
        >
          <option value="">Cond. Fiscal</option>
          {condicionesFiscales.map(c => (
            <option key={c.fc_id} value={c.fc_id}>
              {c.fc_desc}
            </option>
          ))}
        </select>

        <select
          value={filtroSucursalId}
          onChange={(e) => updateFilters({ bra_id: e.target.value, page: 1 })}
          className={styles.filterSelect}
        >
          <option value="">Sucursal</option>
          {sucursales.map(s => (
            <option key={s.bra_id} value={s.bra_id}>
              {s.bra_desc}
            </option>
          ))}
        </select>

        <select
          value={filtroVendedorId}
          onChange={(e) => updateFilters({ sm_id: e.target.value, page: 1 })}
          className={styles.filterSelect}
        >
          <option value="">Vendedor</option>
          {vendedores.map(v => (
            <option key={v.sm_id} value={v.sm_id}>
              {v.sm_name}
            </option>
          ))}
        </select>

        <button
          className={styles.btnToggleAdvanced}
          onClick={() => setShowAdvanced(!showAdvanced)}
          title="Filtros avanzados"
        >
          <SlidersHorizontal size={14} />
          {hasAdvancedFilters ? 'Avanzados *' : 'Avanzados'}
        </button>

        {activeChips.length > 0 && (
          <button
            className={styles.btnLimpiar}
            onClick={limpiarFiltros}
          >
            <Trash2 size={14} />
            Limpiar
          </button>
        )}
      </div>

      {/* Advanced filters panel */}
      {showAdvanced && (
        <div className={styles.advancedFilters}>
          <label className={styles.checkboxLabel}>
            <input
              type="checkbox"
              checked={filtroSoloActivos}
              onChange={(e) => updateFilters({ solo_activos: e.target.checked, page: 1 })}
            />
            Solo activos
          </label>

          <div className={styles.separator} />

          <select
            value={filtroConML}
            onChange={(e) => updateFilters({ con_ml: e.target.value, page: 1 })}
            className={styles.filterSelect}
          >
            <option value="">MercadoLibre</option>
            <option value="true">Con ML</option>
            <option value="false">Sin ML</option>
          </select>

          <select
            value={filtroConEmail}
            onChange={(e) => updateFilters({ con_email: e.target.value, page: 1 })}
            className={styles.filterSelect}
          >
            <option value="">Email</option>
            <option value="true">Con Email</option>
            <option value="false">Sin Email</option>
          </select>

          <select
            value={filtroConTelefono}
            onChange={(e) => updateFilters({ con_telefono: e.target.value, page: 1 })}
            className={styles.filterSelect}
          >
            <option value="">Teléfono</option>
            <option value="true">Con Tel</option>
            <option value="false">Sin Tel</option>
          </select>

          <div className={styles.separator} />

          <div className={styles.filterGroup}>
            <label>ID desde:</label>
            <input
              type="number"
              value={filtroCustIdDesde}
              onChange={(e) => updateFilters({ cust_id_desde: e.target.value, page: 1 })}
              className={styles.filterInputSmall}
              placeholder="Min"
            />
          </div>

          <div className={styles.filterGroup}>
            <label>ID hasta:</label>
            <input
              type="number"
              value={filtroCustIdHasta}
              onChange={(e) => updateFilters({ cust_id_hasta: e.target.value, page: 1 })}
              className={styles.filterInputSmall}
              placeholder="Max"
            />
          </div>
        </div>
      )}

      {/* Active filter chips */}
      {activeChips.length > 0 && (
        <div className={styles.activeFilters}>
          {activeChips.map(({ key, label }) => (
            <span key={key} className={styles.chip}>
              {label}
              <button
                className={styles.chipRemove}
                onClick={() => removeChip(key)}
                aria-label={`Quitar filtro ${label}`}
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Table */}
      <div className={styles.tableWrapper}>
        {loading ? (
          <div className={styles.loading}>Cargando clientes...</div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>ID</th>
                <th>Nombre</th>
                <th>CUIT/DNI</th>
                <th>Email</th>
                <th>Teléfono</th>
                <th>Ciudad</th>
                <th>Provincia</th>
                <th>Cond. Fiscal</th>
                <th>Vendedor</th>
                <th>ML</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {clientes.length === 0 ? (
                <tr>
                  <td colSpan="11" className={styles.noData}>
                    No se encontraron clientes
                  </td>
                </tr>
              ) : (
                clientes.map((cliente) => (
                  <tr key={`${cliente.comp_id}-${cliente.cust_id}`}>
                    <td>{cliente.cust_id}</td>
                    <td
                      className={styles.nombre}
                      onClick={() => handleVerDetalle(cliente)}
                      title="Click para ver detalle"
                    >
                      {cliente.cust_name || '-'}
                    </td>
                    <td>{cliente.cust_taxnumber || '-'}</td>
                    <td>{cliente.cust_email || '-'}</td>
                    <td>{cliente.cust_phone1 || cliente.cust_cellphone || '-'}</td>
                    <td>{cliente.cust_city || '-'}</td>
                    <td>{cliente.state_desc || '-'}</td>
                    <td>{cliente.fc_desc || '-'}</td>
                    <td>{cliente.sm_name || '-'}</td>
                    <td>
                      {cliente.cust_mercadolibreid ? (
                        <span className={styles.badgeSuccess} title={cliente.cust_mercadolibrenickname}>
                          <Check size={12} /> ML
                        </span>
                      ) : (
                        <span className={styles.badgeMuted}>-</span>
                      )}
                    </td>
                    <td>
                      {cliente.cust_inactive ? (
                        <span className={styles.badgeDanger}>Inactivo</span>
                      ) : (
                        <span className={styles.badgeSuccess}>Activo</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      <div className={styles.pagination}>
        <div className={styles.paginationInfo}>
          {totalClientes > 0
            ? `${((page - 1) * pageSize) + 1}–${Math.min(page * pageSize, totalClientes)} de ${totalClientes.toLocaleString()}`
            : 'Sin resultados'
          }
        </div>
        <div className={styles.paginationControls}>
          <button
            onClick={() => updateFilters({ page: 1 })}
            disabled={page === 1}
            className={styles.btnPagination}
            aria-label="Primera página"
          >
            <ChevronsLeft size={16} />
          </button>
          <button
            onClick={() => updateFilters({ page: Math.max(1, page - 1) })}
            disabled={page === 1}
            className={styles.btnPagination}
            aria-label="Página anterior"
          >
            <ChevronLeft size={16} />
          </button>
          <span className={styles.pageNumber}>
            {page} / {totalPages}
          </span>
          <button
            onClick={() => updateFilters({ page: Math.min(totalPages, page + 1) })}
            disabled={page === totalPages}
            className={styles.btnPagination}
            aria-label="Página siguiente"
          >
            <ChevronRight size={16} />
          </button>
          <button
            onClick={() => updateFilters({ page: totalPages })}
            disabled={page === totalPages}
            className={styles.btnPagination}
            aria-label="Última página"
          >
            <ChevronsRight size={16} />
          </button>
        </div>
        <div className={styles.pageSizeSelector}>
          <label>
            Por página:
            <select
              value={pageSize}
              onChange={(e) => updateFilters({ page_size: Number(e.target.value), page: 1 })}
              className={styles.pageSizeSelect}
            >
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={200}>200</option>
            </select>
          </label>
        </div>
      </div>

      {/* Export Modal */}
      {mostrarModalExport && (
        <div className={styles.modalOverlay} onClick={() => setMostrarModalExport(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2>Exportar Clientes</h2>
              <button
                className={styles.modalClose}
                onClick={() => setMostrarModalExport(false)}
                aria-label="Cerrar modal"
              >
                <X size={18} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <p className={styles.modalInfo}>
                Seleccioná los campos a incluir. Se exportarán {totalClientes.toLocaleString()} clientes con los filtros aplicados.
              </p>

              <div className={styles.modalActions}>
                <button
                  className={styles.btnSelectAll}
                  onClick={() => setCamposSeleccionados(camposDisponibles.map(c => c.key))}
                >
                  Seleccionar todos
                </button>
                <button
                  className={styles.btnSelectAll}
                  onClick={() => setCamposSeleccionados([])}
                >
                  Deseleccionar todos
                </button>
              </div>

              <div className={styles.camposGrid}>
                {camposDisponibles.map(campo => (
                  <label key={campo.key} className={styles.campoCheckbox}>
                    <input
                      type="checkbox"
                      checked={camposSeleccionados.includes(campo.key)}
                      onChange={() => toggleCampo(campo.key)}
                    />
                    {campo.label}
                  </label>
                ))}
              </div>
            </div>

            <div className={styles.modalFooter}>
              <button
                className={styles.btnCancel}
                onClick={() => setMostrarModalExport(false)}
                disabled={exportando}
              >
                Cancelar
              </button>
              <button
                className={styles.btnPrimary}
                onClick={handleExportar}
                disabled={exportando || camposSeleccionados.length === 0}
              >
                {exportando ? 'Exportando...' : 'Exportar XLSX'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Detalle */}
      {mostrarModalDetalle && clienteSeleccionado && (
        <ModalDetalleCliente
          cliente={clienteSeleccionado}
          onClose={() => setMostrarModalDetalle(false)}
          onActualizar={handleActualizarCliente}
        />
      )}
    </div>
  );
}

import { useState, useEffect, useMemo, useCallback } from 'react';
import { useDebounce } from '../hooks/useDebounce';
import { useQueryFilters } from '../hooks/useQueryFilters';
import styles from './Clientes.module.css';
import axios from 'axios';
import ModalDetalleCliente from '../components/ModalDetalleCliente';

const API_URL = import.meta.env.VITE_API_URL || 'https://pricing.gaussonline.com.ar';

export default function Clientes() {
  const [clientes, setClientes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalClientes, setTotalClientes] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  // Filtros disponibles
  const [provincias, setProvincias] = useState([]);
  const [condicionesFiscales, setCondicionesFiscales] = useState([]);
  const [sucursales, setSucursales] = useState([]);
  const [vendedores, setVendedores] = useState([]);
  const [mostrarFiltrosAvanzados, setMostrarFiltrosAvanzados] = useState(false);

  // Usar query params para todos los filtros
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
    fecha_desde: '',
    fecha_hasta: '',
    cust_id_desde: '',
    cust_id_hasta: ''
  }, {
    page: 'number',
    page_size: 'number',
    solo_activos: 'boolean'
  });

  // Extraer valores de URL
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
  const filtroFechaDesde = getFilter('fecha_desde');
  const filtroFechaHasta = getFilter('fecha_hasta');
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

  // useMemo para evitar loops infinitos
  const searchKey = useMemo(() => searchInput, [searchInput]);
  const debouncedSearch = useDebounce(searchInput, 500);

  // DEBUG: Ver filtros desde URL
  useEffect(() => {
    console.log('[Clientes] Filtros desde URL:', {
      search: searchInput,
      page,
      pageSize,
      filtroProvinciaId,
      filtroSoloActivos
    });
  }, [searchInput, page, pageSize, filtroProvinciaId, filtroSoloActivos]);

  // Cargar filtros iniciales
  useEffect(() => {
    cargarFiltros();
    cargarCamposDisponibles();
  }, []);

  // Cargar clientes cuando cambian los filtros
  useEffect(() => {
    cargarClientes();
  }, [page, pageSize, debouncedSearch, filtroProvinciaId, filtroFiscalId, filtroSucursalId, filtroVendedorId, filtroSoloActivos, filtroConML, filtroConEmail, filtroConTelefono, filtroFechaDesde, filtroFechaHasta, filtroCustIdDesde, filtroCustIdHasta]);

  const cargarFiltros = async () => {
    try {
      const [provRes, fiscalRes, sucRes, vendRes] = await Promise.all([
        axios.get(`${API_URL}/api/clientes/filtros/provincias`),
        axios.get(`${API_URL}/api/clientes/filtros/condiciones-fiscales`),
        axios.get(`${API_URL}/api/clientes/filtros/sucursales`),
        axios.get(`${API_URL}/api/clientes/filtros/vendedores`)
      ]);

      setProvincias(provRes.data);
      setCondicionesFiscales(fiscalRes.data);
      setSucursales(sucRes.data);
      setVendedores(vendRes.data);
    } catch (error) {
      console.error('Error cargando filtros:', error);
    }
  };

  const cargarCamposDisponibles = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/clientes/campos-disponibles`);
      setCamposDisponibles(response.data.campos);
      // Seleccionar algunos campos por defecto
      const camposDefault = response.data.campos
        .filter(c => ['cust_id', 'cust_name', 'cust_taxnumber', 'cust_email', 'cust_phone1', 'state_desc', 'fc_desc'].includes(c.key))
        .map(c => c.key);
      setCamposSeleccionados(camposDefault);
    } catch (error) {
      console.error('Error cargando campos disponibles:', error);
    }
  };

  const cargarClientes = async () => {
    setLoading(true);
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
      if (filtroFechaDesde) params.append('fecha_desde', filtroFechaDesde);
      if (filtroFechaHasta) params.append('fecha_hasta', filtroFechaHasta);
      if (filtroCustIdDesde) params.append('cust_id_desde', filtroCustIdDesde);
      if (filtroCustIdHasta) params.append('cust_id_hasta', filtroCustIdHasta);

      const response = await axios.get(`${API_URL}/api/clientes?${params}`);
      setClientes(response.data.clientes);
      setTotalClientes(response.data.total);
      setTotalPages(response.data.total_pages);
    } catch (error) {
      console.error('Error cargando clientes:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleExportar = async () => {
    if (camposSeleccionados.length === 0) {
      alert('Seleccioná al menos un campo para exportar');
      return;
    }

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
        fecha_desde: filtroFechaDesde || null,
        fecha_hasta: filtroFechaHasta || null,
        cust_id_desde: filtroCustIdDesde ? parseInt(filtroCustIdDesde) : null,
        cust_id_hasta: filtroCustIdHasta ? parseInt(filtroCustIdHasta) : null
      };

      const response = await axios.post(
        `${API_URL}/api/clientes/exportar`,
        payload,
        {
          responseType: 'blob'
        }
      );

      // Descargar archivo XLSX
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
    } catch (error) {
      console.error('Error exportando:', error);
      alert('Error al exportar clientes');
    } finally {
      setExportando(false);
    }
  };

  const toggleCampo = (key) => {
    setCamposSeleccionados(prev => {
      if (prev.includes(key)) {
        return prev.filter(k => k !== key);
      } else {
        return [...prev, key];
      }
    });
  };

  const seleccionarTodosCampos = () => {
    setCamposSeleccionados(camposDisponibles.map(c => c.key));
  };

  const deseleccionarTodosCampos = () => {
    setCamposSeleccionados([]);
  };

  // Helper para actualizar filtros individuales (NO resetean página)
  const setSearchInput = useCallback((value) => {
    console.log('[Clientes] setSearchInput:', value);
    updateFilters({ search: value });
  }, [updateFilters]);
  
  const setPage = useCallback((value) => {
    const newPage = typeof value === 'function' ? value(page) : value;
    console.log('[Clientes] setPage:', newPage);
    updateFilters({ page: newPage });
  }, [updateFilters, page]);
  
  const setPageSize = useCallback((value) => {
    console.log('[Clientes] setPageSize:', value);
    updateFilters({ page_size: value, page: 1 });
  }, [updateFilters]);
  
  const setFiltroProvinciaId = useCallback((value) => {
    console.log('[Clientes] setFiltroProvinciaId:', value);
    updateFilters({ state_id: value });
  }, [updateFilters]);
  
  const setFiltroFiscalId = useCallback((value) => updateFilters({ fc_id: value }), [updateFilters]);
  const setFiltroSucursalId = useCallback((value) => updateFilters({ bra_id: value }), [updateFilters]);
  const setFiltroVendedorId = useCallback((value) => updateFilters({ sm_id: value }), [updateFilters]);
  const setFiltroSoloActivos = useCallback((value) => updateFilters({ solo_activos: value }), [updateFilters]);
  const setFiltroConML = useCallback((value) => updateFilters({ con_ml: value }), [updateFilters]);
  const setFiltroConEmail = useCallback((value) => updateFilters({ con_email: value }), [updateFilters]);
  const setFiltroConTelefono = useCallback((value) => updateFilters({ con_telefono: value }), [updateFilters]);
  const setFiltroFechaDesde = useCallback((value) => updateFilters({ fecha_desde: value }), [updateFilters]);
  const setFiltroFechaHasta = useCallback((value) => updateFilters({ fecha_hasta: value }), [updateFilters]);
  const setFiltroCustIdDesde = useCallback((value) => updateFilters({ cust_id_desde: value }), [updateFilters]);
  const setFiltroCustIdHasta = useCallback((value) => updateFilters({ cust_id_hasta: value }), [updateFilters]);

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
      fecha_desde: '',
      fecha_hasta: '',
      cust_id_desde: '',
      cust_id_hasta: '',
      page: 1
    });
  };

  const handleVerDetalle = async (cliente) => {
    try {
      const response = await axios.get(
        `${API_URL}/api/clientes/${cliente.cust_id}?comp_id=${cliente.comp_id}`
      );
      setClienteSeleccionado(response.data);
      setMostrarModalDetalle(true);
    } catch (error) {
      console.error('Error cargando detalle del cliente:', error);
      alert('Error al cargar detalle del cliente');
    }
  };

  const handleActualizarCliente = (clienteActualizado) => {
    // Actualizar en la lista
    setClientes(clientes.map(c => 
      c.cust_id === clienteActualizado.cust_id && c.comp_id === clienteActualizado.comp_id
        ? clienteActualizado
        : c
    ));
    setClienteSeleccionado(clienteActualizado);
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>Clientes</h1>
        <div className={styles.headerActions}>
          <span className={styles.totalCount}>
            Total: {totalClientes.toLocaleString()} clientes
          </span>
          <button
            className={styles.btnExport}
            onClick={() => setMostrarModalExport(true)}
          >
            📊 Exportar
          </button>
        </div>
      </div>

      {/* Filtros */}
      <div className={styles.filtros}>
        <div className={styles.filtrosRow}>
          <input
            type="text"
            placeholder="Buscar por nombre, CUIT, email o ciudad..."
            value={searchInput}
            onChange={(e) => {
              setSearchInput(e.target.value);
              setPage(1);
            }}
            className={styles.searchInput}
          />

          <select
            value={filtroProvinciaId}
            onChange={(e) => {
              setFiltroProvinciaId(e.target.value);
              setPage(1);
            }}
            className={styles.select}
          >
            <option value="">Todas las provincias</option>
            {provincias.map(p => (
              <option key={p.state_id} value={p.state_id}>
                {p.state_desc}
              </option>
            ))}
          </select>

          <select
            value={filtroFiscalId}
            onChange={(e) => {
              setFiltroFiscalId(e.target.value);
              setPage(1);
            }}
            className={styles.select}
          >
            <option value="">Todas las condiciones fiscales</option>
            {condicionesFiscales.map(c => (
              <option key={c.fc_id} value={c.fc_id}>
                {c.fc_desc}
              </option>
            ))}
          </select>

          <select
            value={filtroSucursalId}
            onChange={(e) => {
              setFiltroSucursalId(e.target.value);
              setPage(1);
            }}
            className={styles.select}
          >
            <option value="">Todas las sucursales</option>
            {sucursales.map(s => (
              <option key={s.bra_id} value={s.bra_id}>
                {s.bra_desc}
              </option>
            ))}
          </select>

          <select
            value={filtroVendedorId}
            onChange={(e) => {
              setFiltroVendedorId(e.target.value);
              setPage(1);
            }}
            className={styles.select}
          >
            <option value="">Todos los vendedores</option>
            {vendedores.map(v => (
              <option key={v.sm_id} value={v.sm_id}>
                {v.sm_name}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.filtrosRow}>
          <label className={styles.checkbox}>
            <input
              type="checkbox"
              checked={filtroSoloActivos}
              onChange={(e) => {
                setFiltroSoloActivos(e.target.checked);
                setPage(1);
              }}
            />
            Solo activos
          </label>

          <select
            value={filtroConML}
            onChange={(e) => {
              setFiltroConML(e.target.value);
              setPage(1);
            }}
            className={styles.select}
          >
            <option value="">Con/sin MercadoLibre</option>
            <option value="true">Con MercadoLibre</option>
            <option value="false">Sin MercadoLibre</option>
          </select>

          <select
            value={filtroConEmail}
            onChange={(e) => {
              setFiltroConEmail(e.target.value);
              setPage(1);
            }}
            className={styles.select}
          >
            <option value="">Con/sin Email</option>
            <option value="true">Con Email</option>
            <option value="false">Sin Email</option>
          </select>

          <select
            value={filtroConTelefono}
            onChange={(e) => {
              setFiltroConTelefono(e.target.value);
              setPage(1);
            }}
            className={styles.select}
          >
            <option value="">Con/sin Teléfono</option>
            <option value="true">Con Teléfono</option>
            <option value="false">Sin Teléfono</option>
          </select>

          <button
            className={styles.btnLimpiar}
            onClick={limpiarFiltros}
          >
            🗑️ Limpiar filtros
          </button>
        </div>
      </div>

      {/* Tabla */}
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
                <th>Condición Fiscal</th>
                <th>Vendedor</th>
                <th>MercadoLibre</th>
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
                          ✓ ML
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

      {/* Paginación */}
      <div className={styles.pagination}>
        <div className={styles.paginationInfo}>
          Mostrando {((page - 1) * pageSize) + 1} - {Math.min(page * pageSize, totalClientes)} de {totalClientes}
        </div>
        <div className={styles.paginationControls}>
          <button
            onClick={() => setPage(1)}
            disabled={page === 1}
            className={styles.btnPagination}
          >
            ««
          </button>
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className={styles.btnPagination}
          >
            «
          </button>
          <span className={styles.pageNumber}>
            Página {page} de {totalPages}
          </span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className={styles.btnPagination}
          >
            »
          </button>
          <button
            onClick={() => setPage(totalPages)}
            disabled={page === totalPages}
            className={styles.btnPagination}
          >
            »»
          </button>
        </div>
        <div className={styles.pageSizeSelector}>
          <label>
            Items por página:
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className={styles.selectSmall}
            >
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={200}>200</option>
            </select>
          </label>
        </div>
      </div>

      {/* Modal de Exportación */}
      {mostrarModalExport && (
        <div className={styles.modalOverlay} onClick={() => setMostrarModalExport(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2>Exportar Clientes</h2>
              <button
                className={styles.modalClose}
                onClick={() => setMostrarModalExport(false)}
              >
                ✕
              </button>
            </div>

            <div className={styles.modalBody}>
              <p className={styles.modalInfo}>
                Seleccioná los campos que querés incluir en la exportación.
                Se exportarán {totalClientes} clientes con los filtros aplicados.
              </p>

              <div className={styles.modalActions}>
                <button
                  className={styles.btnSecondary}
                  onClick={seleccionarTodosCampos}
                >
                  Seleccionar todos
                </button>
                <button
                  className={styles.btnSecondary}
                  onClick={deseleccionarTodosCampos}
                >
                  Deseleccionar todos
                </button>
              </div>

              <div className={styles.camposGrid}>
                {camposDisponibles.map(campo => (
                  <label key={campo.key} className={styles.checkboxLabel}>
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
                {exportando ? 'Exportando...' : 'Exportar CSV'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de Detalle */}
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

import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI } from '../services/api';
import {
  Wallet, Plus, Minus, ArrowLeft, CreditCard, Wrench,
  X, Calendar, RefreshCw, ArrowUpCircle, ArrowDownCircle,
} from 'lucide-react';
import styles from './RRHHCuentaCorriente.module.css';

const formatDate = (dateStr) => {
  if (!dateStr) return '-';
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
};

const formatMonto = (monto) => {
  return new Intl.NumberFormat('es-AR', { style: 'currency', currency: 'ARS' }).format(monto);
};

const getSaldoClass = (saldo) => {
  if (saldo > 0) return styles.saldoPositivo;
  if (saldo < 0) return styles.saldoNegativo;
  return styles.saldoCero;
};

const ESTADO_HERR_CLASSES = {
  asignado: styles.estadoAsignado,
  devuelto: styles.estadoDevuelto,
  perdido: styles.estadoPerdido,
  roto: styles.estadoRoto,
};

export default function RRHHCuentaCorriente() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rrhh.gestionar');

  // ── Tab state ──
  const [activeTab, setActiveTab] = useState('cuentas'); // cuentas | herramientas

  // ── Cuentas list ──
  const [cuentas, setCuentas] = useState([]);
  const [loadingCuentas, setLoadingCuentas] = useState(true);
  const [soloConSaldo, setSoloConSaldo] = useState(false);
  const [searchCuentas, setSearchCuentas] = useState('');

  // ── Detail view ──
  const [detalle, setDetalle] = useState(null);
  const [loadingDetalle, setLoadingDetalle] = useState(false);
  const [detalleEmpleadoId, setDetalleEmpleadoId] = useState(null);
  const [detallePage, setDetallePage] = useState(1);
  const DETAIL_PAGE_SIZE = 30;

  // ── Cargo modal ──
  const [cargoModalOpen, setCargoModalOpen] = useState(false);
  const [cargoForm, setCargoForm] = useState({ monto: '', concepto: '', descripcion: '', cuotas: '1' });
  const [cargoSaving, setCargoSaving] = useState(false);
  const [cargoError, setCargoError] = useState(null);

  // ── Abono modal ──
  const [abonoModalOpen, setAbonoModalOpen] = useState(false);
  const [abonoForm, setAbonoForm] = useState({ monto: '', concepto: '', descripcion: '' });
  const [abonoSaving, setAbonoSaving] = useState(false);
  const [abonoError, setAbonoError] = useState(null);

  // ── Liquidacion modal ──
  const [liquidacionModalOpen, setLiquidacionModalOpen] = useState(false);
  const [liquidacionForm, setLiquidacionForm] = useState({
    mes: String(new Date().getMonth() + 1),
    anio: String(new Date().getFullYear()),
  });
  const [liquidacionSaving, setLiquidacionSaving] = useState(false);
  const [liquidacionError, setLiquidacionError] = useState(null);
  const [liquidacionResult, setLiquidacionResult] = useState(null);

  // ── Herramientas ──
  const [herramientas, setHerramientas] = useState([]);
  const [loadingHerr, setLoadingHerr] = useState(false);
  const [herrEmpleadoId, setHerrEmpleadoId] = useState('');
  const [empleados, setEmpleados] = useState([]);

  // ── Herramienta modal ──
  const [herrModalOpen, setHerrModalOpen] = useState(false);
  const [herrForm, setHerrForm] = useState({
    empleado_id: '',
    descripcion: '',
    codigo_inventario: '',
    cantidad: '1',
    fecha_asignacion: new Date().toISOString().slice(0, 10),
    observaciones: '',
  });
  const [herrSaving, setHerrSaving] = useState(false);
  const [herrError, setHerrError] = useState(null);

  // ── Load empleados (for selects) ──
  useEffect(() => {
    const fetchEmpleados = async () => {
      try {
        const { data } = await rrhhAPI.listarEmpleados({ page_size: 200, estado: 'activo' });
        setEmpleados(Array.isArray(data) ? data : data.items || []);
      } catch {
        setEmpleados([]);
      }
    };
    fetchEmpleados();
  }, []);

  // ── Fetch cuentas ──
  const cargarCuentas = useCallback(async () => {
    setLoadingCuentas(true);
    try {
      const params = {};
      if (soloConSaldo) params.solo_con_saldo = true;
      if (searchCuentas) params.search = searchCuentas;
      const { data } = await rrhhAPI.listarCuentasCorrientes(params);
      setCuentas(Array.isArray(data) ? data : []);
    } catch {
      setCuentas([]);
    } finally {
      setLoadingCuentas(false);
    }
  }, [soloConSaldo, searchCuentas]);

  useEffect(() => {
    if (activeTab === 'cuentas' && !detalleEmpleadoId) {
      cargarCuentas();
    }
  }, [activeTab, detalleEmpleadoId, cargarCuentas]);

  // ── Fetch detail ──
  const cargarDetalle = useCallback(async () => {
    if (!detalleEmpleadoId) return;
    setLoadingDetalle(true);
    try {
      const { data } = await rrhhAPI.detalleCuentaCorriente(detalleEmpleadoId, {
        page: detallePage,
        page_size: DETAIL_PAGE_SIZE,
      });
      setDetalle(data);
    } catch {
      setDetalle(null);
    } finally {
      setLoadingDetalle(false);
    }
  }, [detalleEmpleadoId, detallePage]);

  useEffect(() => {
    cargarDetalle();
  }, [cargarDetalle]);

  // ── Fetch herramientas ──
  const cargarHerramientas = useCallback(async () => {
    if (!herrEmpleadoId) {
      setHerramientas([]);
      return;
    }
    setLoadingHerr(true);
    try {
      const { data } = await rrhhAPI.listarHerramientas(herrEmpleadoId);
      setHerramientas(Array.isArray(data) ? data : []);
    } catch {
      setHerramientas([]);
    } finally {
      setLoadingHerr(false);
    }
  }, [herrEmpleadoId]);

  useEffect(() => {
    if (activeTab === 'herramientas') {
      cargarHerramientas();
    }
  }, [activeTab, cargarHerramientas]);

  // ── Handlers: Cargo ──
  const handleOpenCargo = () => {
    setCargoForm({ monto: '', concepto: '', descripcion: '', cuotas: '1' });
    setCargoError(null);
    setCargoModalOpen(true);
  };

  const handleSubmitCargo = async (e) => {
    e.preventDefault();
    setCargoSaving(true);
    setCargoError(null);
    try {
      await rrhhAPI.registrarCargo(detalleEmpleadoId, {
        monto: parseFloat(cargoForm.monto),
        concepto: cargoForm.concepto,
        descripcion: cargoForm.descripcion || null,
        cuotas: parseInt(cargoForm.cuotas, 10) || 1,
      });
      setCargoModalOpen(false);
      cargarDetalle();
    } catch (err) {
      setCargoError(err.response?.data?.detail || 'Error al registrar cargo');
    } finally {
      setCargoSaving(false);
    }
  };

  // ── Handlers: Abono ──
  const handleOpenAbono = () => {
    setAbonoForm({ monto: '', concepto: '', descripcion: '' });
    setAbonoError(null);
    setAbonoModalOpen(true);
  };

  const handleSubmitAbono = async (e) => {
    e.preventDefault();
    setAbonoSaving(true);
    setAbonoError(null);
    try {
      await rrhhAPI.registrarAbono(detalleEmpleadoId, {
        monto: parseFloat(abonoForm.monto),
        concepto: abonoForm.concepto,
        descripcion: abonoForm.descripcion || null,
      });
      setAbonoModalOpen(false);
      cargarDetalle();
    } catch (err) {
      setAbonoError(err.response?.data?.detail || 'Error al registrar abono');
    } finally {
      setAbonoSaving(false);
    }
  };

  // ── Handlers: Liquidación ──
  const handleSubmitLiquidacion = async (e) => {
    e.preventDefault();
    setLiquidacionSaving(true);
    setLiquidacionError(null);
    setLiquidacionResult(null);
    try {
      const { data } = await rrhhAPI.liquidacionMensual({
        mes: parseInt(liquidacionForm.mes, 10),
        anio: parseInt(liquidacionForm.anio, 10),
      });
      setLiquidacionResult(data);
      cargarCuentas();
    } catch (err) {
      setLiquidacionError(err.response?.data?.detail || 'Error en liquidación');
    } finally {
      setLiquidacionSaving(false);
    }
  };

  // ── Handlers: Herramientas ──
  const handleOpenHerrModal = () => {
    setHerrForm({
      empleado_id: herrEmpleadoId || '',
      descripcion: '',
      codigo_inventario: '',
      cantidad: '1',
      fecha_asignacion: new Date().toISOString().slice(0, 10),
      observaciones: '',
    });
    setHerrError(null);
    setHerrModalOpen(true);
  };

  const handleSubmitHerr = async (e) => {
    e.preventDefault();
    setHerrSaving(true);
    setHerrError(null);
    try {
      await rrhhAPI.asignarHerramienta({
        empleado_id: parseInt(herrForm.empleado_id, 10),
        descripcion: herrForm.descripcion,
        codigo_inventario: herrForm.codigo_inventario || null,
        cantidad: parseInt(herrForm.cantidad, 10) || 1,
        fecha_asignacion: herrForm.fecha_asignacion,
        observaciones: herrForm.observaciones || null,
      });
      setHerrModalOpen(false);
      cargarHerramientas();
    } catch (err) {
      setHerrError(err.response?.data?.detail || 'Error al asignar herramienta');
    } finally {
      setHerrSaving(false);
    }
  };

  const handleDevolverHerr = async (herrId) => {
    try {
      await rrhhAPI.devolverHerramienta(herrId, {});
      cargarHerramientas();
    } catch {
      // silent — user sees no change
    }
  };

  // ── Navigate to detail ──
  const openDetalle = (empleadoId) => {
    setDetalleEmpleadoId(empleadoId);
    setDetallePage(1);
  };

  const closeDetalle = () => {
    setDetalleEmpleadoId(null);
    setDetalle(null);
    cargarCuentas();
  };

  // ── RENDER ──
  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Wallet size={24} />
          <h1>Cuenta Corriente</h1>
        </div>
        <div className={styles.headerActions}>
          {puedeGestionar && activeTab === 'cuentas' && !detalleEmpleadoId && (
            <button
              className={styles.btnPrimary}
              onClick={() => setLiquidacionModalOpen(true)}
            >
              <Calendar size={16} /> Liquidación Mensual
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      {!detalleEmpleadoId && (
        <div className={styles.tabs}>
          <button
            className={`${styles.tab} ${activeTab === 'cuentas' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('cuentas')}
          >
            <CreditCard size={16} /> Cuentas Corrientes
          </button>
          {tienePermiso('rrhh.ver') && (
            <button
              className={`${styles.tab} ${activeTab === 'herramientas' ? styles.tabActive : ''}`}
              onClick={() => setActiveTab('herramientas')}
            >
              <Wrench size={16} /> Herramientas
            </button>
          )}
        </div>
      )}

      {/* ─── TAB: Cuentas ─── */}
      {activeTab === 'cuentas' && !detalleEmpleadoId && (
        <>
          <div className={styles.filters}>
            <input
              className={styles.input}
              type="text"
              placeholder="Buscar por nombre o legajo..."
              value={searchCuentas}
              onChange={(e) => setSearchCuentas(e.target.value)}
            />
            <label className={styles.checkLabel}>
              <input
                type="checkbox"
                checked={soloConSaldo}
                onChange={(e) => setSoloConSaldo(e.target.checked)}
              />
              Solo con saldo
            </label>
            <button className={styles.btnIcon} onClick={cargarCuentas} title="Refrescar">
              <RefreshCw size={16} />
            </button>
          </div>

          {loadingCuentas ? (
            <div className={styles.loading}>Cargando cuentas...</div>
          ) : cuentas.length === 0 ? (
            <div className={styles.empty}>No hay cuentas corrientes registradas</div>
          ) : (
            <div className={styles.tableContainer}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Legajo</th>
                    <th>Empleado</th>
                    <th style={{ textAlign: 'right' }}>Saldo</th>
                    <th>Última actualización</th>
                  </tr>
                </thead>
                <tbody>
                  {cuentas.map((c) => (
                    <tr
                      key={c.id}
                      className={styles.clickableRow}
                      onClick={() => openDetalle(c.empleado_id)}
                    >
                      <td>{c.empleado_legajo}</td>
                      <td>{c.empleado_nombre}</td>
                      <td style={{ textAlign: 'right' }}>
                        <span className={getSaldoClass(c.saldo)}>
                          {formatMonto(c.saldo)}
                        </span>
                      </td>
                      <td>{c.updated_at ? formatDate(c.updated_at.slice(0, 10)) : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ─── DETAIL VIEW ─── */}
      {activeTab === 'cuentas' && detalleEmpleadoId && (
        <>
          <button className={styles.backLink} onClick={closeDetalle}>
            <ArrowLeft size={16} /> Volver a cuentas
          </button>

          {loadingDetalle ? (
            <div className={styles.loading}>Cargando detalle...</div>
          ) : detalle ? (
            <>
              <div className={styles.detailPanel}>
                <div className={styles.detailHeader}>
                  <div className={styles.detailTitle}>
                    <CreditCard size={20} />
                    <h2>{detalle.empleado_nombre}</h2>
                    <span className={styles.badge}>{detalle.empleado_legajo}</span>
                  </div>
                  <div className={`${styles.detailSaldo} ${getSaldoClass(detalle.saldo)}`}>
                    {formatMonto(detalle.saldo)}
                  </div>
                </div>
                {puedeGestionar && (
                  <div className={styles.headerActions}>
                    <button className={styles.btnPrimary} onClick={handleOpenCargo}>
                      <ArrowUpCircle size={16} /> Registrar Cargo
                    </button>
                    <button className={styles.btnSecondary} onClick={handleOpenAbono}>
                      <ArrowDownCircle size={16} /> Registrar Abono
                    </button>
                  </div>
                )}
              </div>

              {/* Movimientos table */}
              <div className={styles.tableContainer}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Fecha</th>
                      <th>Tipo</th>
                      <th>Concepto</th>
                      <th style={{ textAlign: 'right' }}>Monto</th>
                      <th style={{ textAlign: 'right' }}>Saldo</th>
                      <th>Cuota</th>
                      <th>Registrado por</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detalle.movimientos.length === 0 ? (
                      <tr>
                        <td colSpan={7} className={styles.empty}>Sin movimientos</td>
                      </tr>
                    ) : (
                      detalle.movimientos.map((m) => (
                        <tr key={m.id}>
                          <td>{formatDate(m.fecha)}</td>
                          <td>
                            <span className={m.tipo === 'cargo' ? styles.tipoCargo : styles.tipoAbono}>
                              {m.tipo === 'cargo' ? <Plus size={12} /> : <Minus size={12} />}
                              {m.tipo === 'cargo' ? 'Cargo' : 'Abono'}
                            </span>
                          </td>
                          <td>
                            {m.concepto}
                            {m.descripcion && (
                              <div style={{ fontSize: 'var(--font-xs)', color: 'var(--cf-text-tertiary)' }}>
                                {m.descripcion}
                              </div>
                            )}
                          </td>
                          <td style={{ textAlign: 'right' }}>
                            <span className={m.tipo === 'cargo' ? styles.saldoPositivo : styles.saldoNegativo}>
                              {m.tipo === 'cargo' ? '+' : '-'}{formatMonto(m.monto)}
                            </span>
                          </td>
                          <td style={{ textAlign: 'right' }}>
                            <span className={getSaldoClass(m.saldo_posterior)}>
                              {formatMonto(m.saldo_posterior)}
                            </span>
                          </td>
                          <td>
                            {m.cuota_numero && m.cuota_total ? (
                              <span className={styles.cuotaInfo}>
                                {m.cuota_numero}/{m.cuota_total}
                              </span>
                            ) : m.cuota_total && m.cuota_total > 1 ? (
                              <span className={styles.cuotaInfo}>
                                {m.cuota_total} cuotas
                              </span>
                            ) : '-'}
                          </td>
                          <td>{m.registrado_por_nombre}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
                {detalle.total_movimientos > DETAIL_PAGE_SIZE && (
                  <div className={styles.pagination}>
                    <span className={styles.paginationInfo}>
                      Mostrando {Math.min(detallePage * DETAIL_PAGE_SIZE, detalle.total_movimientos)} de {detalle.total_movimientos}
                    </span>
                    <div className={styles.paginationButtons}>
                      <button
                        className={styles.btnSmall}
                        disabled={detallePage <= 1}
                        onClick={() => setDetallePage((p) => p - 1)}
                      >
                        Anterior
                      </button>
                      <button
                        className={styles.btnSmall}
                        disabled={detallePage * DETAIL_PAGE_SIZE >= detalle.total_movimientos}
                        onClick={() => setDetallePage((p) => p + 1)}
                      >
                        Siguiente
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className={styles.error}>Error al cargar detalle</div>
          )}
        </>
      )}

      {/* ─── TAB: Herramientas ─── */}
      {activeTab === 'herramientas' && (
        <>
          <div className={styles.filters}>
            <select
              className={styles.select}
              value={herrEmpleadoId}
              onChange={(e) => setHerrEmpleadoId(e.target.value)}
            >
              <option value="">Seleccionar empleado...</option>
              {empleados.map((emp) => (
                <option key={emp.id} value={emp.id}>
                  {emp.legajo} - {emp.apellido}, {emp.nombre}
                </option>
              ))}
            </select>
            {puedeGestionar && (
              <button className={styles.btnPrimary} onClick={handleOpenHerrModal}>
                <Plus size={16} /> Asignar Herramienta
              </button>
            )}
          </div>

          {!herrEmpleadoId ? (
            <div className={styles.empty}>Seleccione un empleado para ver sus herramientas</div>
          ) : loadingHerr ? (
            <div className={styles.loading}>Cargando herramientas...</div>
          ) : herramientas.length === 0 ? (
            <div className={styles.empty}>El empleado no tiene herramientas asignadas</div>
          ) : (
            <div className={styles.tableContainer}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Descripción</th>
                    <th>Código</th>
                    <th>Cantidad</th>
                    <th>Fecha Asignación</th>
                    <th>Estado</th>
                    <th>Observaciones</th>
                    {puedeGestionar && <th>Acciones</th>}
                  </tr>
                </thead>
                <tbody>
                  {herramientas.map((h) => (
                    <tr key={h.id}>
                      <td>{h.descripcion}</td>
                      <td>{h.codigo_inventario || '-'}</td>
                      <td>{h.cantidad}</td>
                      <td>{formatDate(h.fecha_asignacion)}</td>
                      <td>
                        <span className={ESTADO_HERR_CLASSES[h.estado] || styles.estadoAsignado}>
                          {h.estado}
                        </span>
                      </td>
                      <td>{h.observaciones || '-'}</td>
                      {puedeGestionar && (
                        <td>
                          {h.estado === 'asignado' && (
                            <button
                              className={styles.btnSmall}
                              onClick={() => handleDevolverHerr(h.id)}
                            >
                              Devolver
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ─── MODAL: Cargo ─── */}
      {cargoModalOpen && (
        <div className={styles.modalOverlay} onClick={() => setCargoModalOpen(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>
                <ArrowUpCircle size={20} /> Registrar Cargo
              </span>
              <button className={styles.btnIcon} onClick={() => setCargoModalOpen(false)}>
                <X size={20} />
              </button>
            </div>
            {cargoError && <div className={styles.formError}>{cargoError}</div>}
            <form onSubmit={handleSubmitCargo}>
              <div className={styles.formGroup}>
                <label>Monto ($)</label>
                <input
                  className={styles.input}
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={cargoForm.monto}
                  onChange={(e) => setCargoForm({ ...cargoForm, monto: e.target.value })}
                  required
                />
              </div>
              <div className={styles.formGroup}>
                <label>Concepto</label>
                <input
                  className={styles.input}
                  type="text"
                  maxLength={255}
                  value={cargoForm.concepto}
                  onChange={(e) => setCargoForm({ ...cargoForm, concepto: e.target.value })}
                  placeholder="Compra: Auriculares Sony WH-1000XM5"
                  required
                />
              </div>
              <div className={styles.formGroup}>
                <label>Cuotas</label>
                <input
                  className={styles.input}
                  type="number"
                  min="1"
                  max="48"
                  value={cargoForm.cuotas}
                  onChange={(e) => setCargoForm({ ...cargoForm, cuotas: e.target.value })}
                />
              </div>
              <div className={styles.formGroup}>
                <label>Descripción (opcional)</label>
                <textarea
                  className={styles.textarea}
                  value={cargoForm.descripcion}
                  onChange={(e) => setCargoForm({ ...cargoForm, descripcion: e.target.value })}
                  maxLength={2000}
                />
              </div>
              <div className={styles.formActions}>
                <button
                  type="button"
                  className={styles.btnSecondary}
                  onClick={() => setCargoModalOpen(false)}
                >
                  Cancelar
                </button>
                <button type="submit" className={styles.btnPrimary} disabled={cargoSaving}>
                  {cargoSaving ? 'Guardando...' : 'Registrar Cargo'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ─── MODAL: Abono ─── */}
      {abonoModalOpen && (
        <div className={styles.modalOverlay} onClick={() => setAbonoModalOpen(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>
                <ArrowDownCircle size={20} /> Registrar Abono
              </span>
              <button className={styles.btnIcon} onClick={() => setAbonoModalOpen(false)}>
                <X size={20} />
              </button>
            </div>
            {abonoError && <div className={styles.formError}>{abonoError}</div>}
            <form onSubmit={handleSubmitAbono}>
              <div className={styles.formGroup}>
                <label>Monto ($)</label>
                <input
                  className={styles.input}
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={abonoForm.monto}
                  onChange={(e) => setAbonoForm({ ...abonoForm, monto: e.target.value })}
                  required
                />
              </div>
              <div className={styles.formGroup}>
                <label>Concepto</label>
                <input
                  className={styles.input}
                  type="text"
                  maxLength={255}
                  value={abonoForm.concepto}
                  onChange={(e) => setAbonoForm({ ...abonoForm, concepto: e.target.value })}
                  placeholder="Deducción salarial mes 03/2026"
                  required
                />
              </div>
              <div className={styles.formGroup}>
                <label>Descripción (opcional)</label>
                <textarea
                  className={styles.textarea}
                  value={abonoForm.descripcion}
                  onChange={(e) => setAbonoForm({ ...abonoForm, descripcion: e.target.value })}
                  maxLength={2000}
                />
              </div>
              <div className={styles.formActions}>
                <button
                  type="button"
                  className={styles.btnSecondary}
                  onClick={() => setAbonoModalOpen(false)}
                >
                  Cancelar
                </button>
                <button type="submit" className={styles.btnPrimary} disabled={abonoSaving}>
                  {abonoSaving ? 'Guardando...' : 'Registrar Abono'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ─── MODAL: Liquidación Mensual ─── */}
      {liquidacionModalOpen && (
        <div className={styles.modalOverlay} onClick={() => setLiquidacionModalOpen(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>
                <Calendar size={20} /> Liquidación Mensual
              </span>
              <button className={styles.btnIcon} onClick={() => setLiquidacionModalOpen(false)}>
                <X size={20} />
              </button>
            </div>
            <p style={{ fontSize: 'var(--font-sm)', color: 'var(--cf-text-secondary)', marginBottom: 'var(--spacing-md)' }}>
              Genera abonos automáticos para empleados con cuotas pendientes.
            </p>
            {liquidacionError && <div className={styles.formError}>{liquidacionError}</div>}
            <form onSubmit={handleSubmitLiquidacion}>
              <div className={styles.formGroup}>
                <label>Mes</label>
                <select
                  className={styles.select}
                  value={liquidacionForm.mes}
                  onChange={(e) => setLiquidacionForm({ ...liquidacionForm, mes: e.target.value })}
                >
                  {Array.from({ length: 12 }, (_, i) => (
                    <option key={i + 1} value={i + 1}>
                      {new Date(2026, i).toLocaleDateString('es-AR', { month: 'long' })}
                    </option>
                  ))}
                </select>
              </div>
              <div className={styles.formGroup}>
                <label>Año</label>
                <input
                  className={styles.input}
                  type="number"
                  min="2020"
                  max="2100"
                  value={liquidacionForm.anio}
                  onChange={(e) => setLiquidacionForm({ ...liquidacionForm, anio: e.target.value })}
                  required
                />
              </div>
              {liquidacionResult && (
                <div className={styles.liquidacionResult}>
                  <p><strong>Cargos procesados:</strong> {liquidacionResult.procesados}</p>
                  <p><strong>Abonos generados:</strong> {liquidacionResult.abonos_generados}</p>
                  <p><strong>Monto total:</strong> {formatMonto(liquidacionResult.monto_total)}</p>
                </div>
              )}
              <div className={styles.formActions}>
                <button
                  type="button"
                  className={styles.btnSecondary}
                  onClick={() => {
                    setLiquidacionModalOpen(false);
                    setLiquidacionResult(null);
                  }}
                >
                  Cerrar
                </button>
                <button type="submit" className={styles.btnPrimary} disabled={liquidacionSaving}>
                  {liquidacionSaving ? 'Procesando...' : 'Ejecutar Liquidación'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ─── MODAL: Asignar Herramienta ─── */}
      {herrModalOpen && (
        <div className={styles.modalOverlay} onClick={() => setHerrModalOpen(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>
                <Wrench size={20} /> Asignar Herramienta
              </span>
              <button className={styles.btnIcon} onClick={() => setHerrModalOpen(false)}>
                <X size={20} />
              </button>
            </div>
            {herrError && <div className={styles.formError}>{herrError}</div>}
            <form onSubmit={handleSubmitHerr}>
              <div className={styles.formGroup}>
                <label>Empleado</label>
                <select
                  className={styles.select}
                  value={herrForm.empleado_id}
                  onChange={(e) => setHerrForm({ ...herrForm, empleado_id: e.target.value })}
                  required
                >
                  <option value="">Seleccionar...</option>
                  {empleados.map((emp) => (
                    <option key={emp.id} value={emp.id}>
                      {emp.legajo} - {emp.apellido}, {emp.nombre}
                    </option>
                  ))}
                </select>
              </div>
              <div className={styles.formGroup}>
                <label>Descripción</label>
                <input
                  className={styles.input}
                  type="text"
                  maxLength={255}
                  value={herrForm.descripcion}
                  onChange={(e) => setHerrForm({ ...herrForm, descripcion: e.target.value })}
                  placeholder="Notebook Lenovo T14"
                  required
                />
              </div>
              <div className={styles.formGroup}>
                <label>Código inventario (opcional)</label>
                <input
                  className={styles.input}
                  type="text"
                  maxLength={100}
                  value={herrForm.codigo_inventario}
                  onChange={(e) => setHerrForm({ ...herrForm, codigo_inventario: e.target.value })}
                />
              </div>
              <div className={styles.formGroup}>
                <label>Cantidad</label>
                <input
                  className={styles.input}
                  type="number"
                  min="1"
                  value={herrForm.cantidad}
                  onChange={(e) => setHerrForm({ ...herrForm, cantidad: e.target.value })}
                />
              </div>
              <div className={styles.formGroup}>
                <label>Fecha de asignación</label>
                <input
                  className={styles.input}
                  type="date"
                  value={herrForm.fecha_asignacion}
                  onChange={(e) => setHerrForm({ ...herrForm, fecha_asignacion: e.target.value })}
                  required
                />
              </div>
              <div className={styles.formGroup}>
                <label>Observaciones (opcional)</label>
                <textarea
                  className={styles.textarea}
                  value={herrForm.observaciones}
                  onChange={(e) => setHerrForm({ ...herrForm, observaciones: e.target.value })}
                  maxLength={2000}
                />
              </div>
              <div className={styles.formActions}>
                <button
                  type="button"
                  className={styles.btnSecondary}
                  onClick={() => setHerrModalOpen(false)}
                >
                  Cancelar
                </button>
                <button type="submit" className={styles.btnPrimary} disabled={herrSaving}>
                  {herrSaving ? 'Guardando...' : 'Asignar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

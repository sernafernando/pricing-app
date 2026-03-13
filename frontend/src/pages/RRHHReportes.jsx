import { useState, useCallback, Fragment } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI } from '../services/api';
import {
  BarChart3, Calendar, Shield, Umbrella, Wallet, Clock,
  Download, RefreshCw, ChevronDown, ChevronUp, AlertTriangle,
} from 'lucide-react';
import styles from './RRHHReportes.module.css';

const currentYear = new Date().getFullYear();
const currentMonth = new Date().getMonth() + 1;

const TABS = [
  { id: 'presentismo', label: 'Presentismo', icon: Calendar },
  { id: 'sanciones', label: 'Sanciones', icon: Shield },
  { id: 'vacaciones', label: 'Vacaciones', icon: Umbrella },
  { id: 'cuenta-corriente', label: 'Cuenta Corriente', icon: Wallet },
  { id: 'horas', label: 'Horas Trabajadas', icon: Clock },
];

const formatCurrency = (value) => {
  if (value == null) return '$0,00';
  return new Intl.NumberFormat('es-AR', { style: 'currency', currency: 'ARS' }).format(value);
};

export default function RRHHReportes() {
  const { tienePermiso } = usePermisos();

  const [activeTab, setActiveTab] = useState('presentismo');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [exporting, setExporting] = useState(false);

  // ── Presentismo state ──
  const [presMes, setPresMes] = useState(currentMonth);
  const [presAnio, setPresAnio] = useState(currentYear);
  const [presArea, setPresArea] = useState('');
  const [presData, setPresData] = useState(null);

  // ── Sanciones state ──
  const [sancDesde, setSancDesde] = useState(
    new Date(currentYear, 0, 1).toISOString().slice(0, 10)
  );
  const [sancHasta, setSancHasta] = useState(
    new Date().toISOString().slice(0, 10)
  );
  const [sancData, setSancData] = useState(null);

  // ── Vacaciones state ──
  const [vacAnio, setVacAnio] = useState(currentYear);
  const [vacData, setVacData] = useState(null);

  // ── Cuenta Corriente state ──
  const [ccData, setCcData] = useState(null);

  // ── Horas state ──
  const [horasMes, setHorasMes] = useState(currentMonth);
  const [horasAnio, setHorasAnio] = useState(currentYear);
  const [horasData, setHorasData] = useState(null);
  const [expandedHoras, setExpandedHoras] = useState({});

  // ── Loaders ──
  const cargarPresentismo = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { mes: presMes, anio: presAnio };
      if (presArea) params.area = presArea;
      const { data } = await rrhhAPI.reportePresentismoMensual(params);
      setPresData(data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar presentismo');
    } finally {
      setLoading(false);
    }
  }, [presMes, presAnio, presArea]);

  const cargarSanciones = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await rrhhAPI.reporteSancionesPeriodo({
        fecha_desde: sancDesde,
        fecha_hasta: sancHasta,
      });
      setSancData(data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar sanciones');
    } finally {
      setLoading(false);
    }
  }, [sancDesde, sancHasta]);

  const cargarVacaciones = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await rrhhAPI.reporteVacacionesResumen({ anio: vacAnio });
      setVacData(data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar vacaciones');
    } finally {
      setLoading(false);
    }
  }, [vacAnio]);

  const cargarCuentaCorriente = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await rrhhAPI.reporteCuentaCorrienteResumen();
      setCcData(data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar cuenta corriente');
    } finally {
      setLoading(false);
    }
  }, []);

  const cargarHoras = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await rrhhAPI.reporteHorasTrabajadas({
        mes: horasMes, anio: horasAnio,
      });
      setHorasData(data);
      setExpandedHoras({});
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar horas');
    } finally {
      setLoading(false);
    }
  }, [horasMes, horasAnio]);

  const handleGenerar = () => {
    if (activeTab === 'presentismo') cargarPresentismo();
    else if (activeTab === 'sanciones') cargarSanciones();
    else if (activeTab === 'vacaciones') cargarVacaciones();
    else if (activeTab === 'cuenta-corriente') cargarCuentaCorriente();
    else if (activeTab === 'horas') cargarHoras();
  };

  // ── Export ──
  const handleExportar = async () => {
    setExporting(true);
    try {
      let params = {};
      let tipo = '';
      if (activeTab === 'presentismo') {
        tipo = 'presentismo-mensual';
        params = { mes: presMes, anio: presAnio };
        if (presArea) params.area = presArea;
      } else if (activeTab === 'sanciones') {
        tipo = 'sanciones-periodo';
        params = { fecha_desde: sancDesde, fecha_hasta: sancHasta };
      } else if (activeTab === 'vacaciones') {
        tipo = 'vacaciones-resumen';
        params = { anio: vacAnio };
      } else if (activeTab === 'cuenta-corriente') {
        tipo = 'cuenta-corriente-resumen';
      } else if (activeTab === 'horas') {
        tipo = 'horas-trabajadas';
        params = { mes: horasMes, anio: horasAnio };
      }

      const { data } = await rrhhAPI.exportarReporte(tipo, params);
      const blob = new Blob([data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `rrhh_${tipo}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al exportar');
    } finally {
      setExporting(false);
    }
  };

  const hasData = () => {
    if (activeTab === 'presentismo') return presData !== null;
    if (activeTab === 'sanciones') return sancData !== null;
    if (activeTab === 'vacaciones') return vacData !== null;
    if (activeTab === 'cuenta-corriente') return ccData !== null;
    if (activeTab === 'horas') return horasData !== null;
    return false;
  };

  const toggleHorasDetalle = (empleadoId) => {
    setExpandedHoras((prev) => ({
      ...prev,
      [empleadoId]: !prev[empleadoId],
    }));
  };

  // ── Renders ──
  const renderFilters = () => {
    if (activeTab === 'presentismo') {
      return (
        <>
          <select
            className={styles.select}
            value={presMes}
            onChange={(e) => setPresMes(Number(e.target.value))}
          >
            {Array.from({ length: 12 }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                {new Date(2026, i).toLocaleString('es-AR', { month: 'long' })}
              </option>
            ))}
          </select>
          <input
            type="number"
            className={styles.input}
            value={presAnio}
            onChange={(e) => setPresAnio(Number(e.target.value))}
            min={2020}
            max={2100}
            style={{ width: 90 }}
          />
          <input
            type="text"
            className={styles.input}
            placeholder="Filtrar por área..."
            value={presArea}
            onChange={(e) => setPresArea(e.target.value)}
            style={{ width: 160 }}
          />
        </>
      );
    }
    if (activeTab === 'sanciones') {
      return (
        <>
          <label style={{ fontSize: 'var(--font-sm)', color: 'var(--cf-text-secondary)' }}>Desde:</label>
          <input
            type="date"
            className={styles.input}
            value={sancDesde}
            onChange={(e) => setSancDesde(e.target.value)}
          />
          <label style={{ fontSize: 'var(--font-sm)', color: 'var(--cf-text-secondary)' }}>Hasta:</label>
          <input
            type="date"
            className={styles.input}
            value={sancHasta}
            onChange={(e) => setSancHasta(e.target.value)}
          />
        </>
      );
    }
    if (activeTab === 'vacaciones') {
      return (
        <input
          type="number"
          className={styles.input}
          value={vacAnio}
          onChange={(e) => setVacAnio(Number(e.target.value))}
          min={2020}
          max={2100}
          style={{ width: 90 }}
        />
      );
    }
    if (activeTab === 'cuenta-corriente') {
      return null;
    }
    if (activeTab === 'horas') {
      return (
        <>
          <select
            className={styles.select}
            value={horasMes}
            onChange={(e) => setHorasMes(Number(e.target.value))}
          >
            {Array.from({ length: 12 }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                {new Date(2026, i).toLocaleString('es-AR', { month: 'long' })}
              </option>
            ))}
          </select>
          <input
            type="number"
            className={styles.input}
            value={horasAnio}
            onChange={(e) => setHorasAnio(Number(e.target.value))}
            min={2020}
            max={2100}
            style={{ width: 90 }}
          />
        </>
      );
    }
    return null;
  };

  const renderPresentismo = () => {
    if (!presData) return <div className={styles.empty}>Seleccioná mes/año y hacé clic en Generar</div>;

    const { items, total_empleados } = presData;

    return (
      <>
        <div className={styles.summaryCards}>
          <div className={styles.summaryCard}>
            <div className={styles.summaryBlue}>{total_empleados}</div>
            <div className={styles.summaryLabel}>Empleados</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryGreen}>
              {items.reduce((s, i) => s + (i.presente || 0), 0)}
            </div>
            <div className={styles.summaryLabel}>Presentes</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryRed}>
              {items.reduce((s, i) => s + (i.ausente || 0), 0)}
            </div>
            <div className={styles.summaryLabel}>Ausencias</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryOrange}>
              {items.reduce((s, i) => s + (i.home_office || 0), 0)}
            </div>
            <div className={styles.summaryLabel}>Home Office</div>
          </div>
        </div>

        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Empleado</th>
                <th>Legajo</th>
                <th>Área</th>
                <th className={styles.textCenter}>Presente</th>
                <th className={styles.textCenter}>Ausente</th>
                <th className={styles.textCenter}>H.O.</th>
                <th className={styles.textCenter}>Vacaciones</th>
                <th className={styles.textCenter}>ART</th>
                <th className={styles.textCenter}>Licencia</th>
                <th className={styles.textCenter}>Franco</th>
                <th className={styles.textCenter}>Feriado</th>
                <th className={styles.textCenter}>Total</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr><td colSpan={12} className={styles.empty}>Sin datos para este período</td></tr>
              )}
              {items.map((row) => (
                <tr key={row.empleado_id} className={row.ausente > 3 ? styles.rowWarning : undefined}>
                  <td>{row.nombre}</td>
                  <td>{row.legajo}</td>
                  <td>{row.area}</td>
                  <td className={styles.textCenter}>{row.presente || 0}</td>
                  <td className={styles.textCenter}>
                    {row.ausente > 0 ? (
                      <span className={styles.badgeRed}>{row.ausente}</span>
                    ) : '0'}
                  </td>
                  <td className={styles.textCenter}>{row.home_office || 0}</td>
                  <td className={styles.textCenter}>{row.vacaciones || 0}</td>
                  <td className={styles.textCenter}>{row.art || 0}</td>
                  <td className={styles.textCenter}>{row.licencia || 0}</td>
                  <td className={styles.textCenter}>{row.franco || 0}</td>
                  <td className={styles.textCenter}>{row.feriado || 0}</td>
                  <td className={styles.textCenter}><strong>{row.total_registrado || 0}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>
    );
  };

  const renderSanciones = () => {
    if (!sancData) return <div className={styles.empty}>Seleccioná rango de fechas y hacé clic en Generar</div>;

    const { items, total_vigentes, total_anuladas, por_tipo, por_empleado } = sancData;

    return (
      <>
        <div className={styles.summaryCards}>
          <div className={styles.summaryCard}>
            <div className={styles.summaryBlue}>{items.length}</div>
            <div className={styles.summaryLabel}>Total</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryRed}>{total_vigentes}</div>
            <div className={styles.summaryLabel}>Vigentes</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryOrange}>{total_anuladas}</div>
            <div className={styles.summaryLabel}>Anuladas</div>
          </div>
        </div>

        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Empleado</th>
                <th>Tipo</th>
                <th>Fecha</th>
                <th>Motivo</th>
                <th>Estado</th>
                <th>Desde</th>
                <th>Hasta</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr><td colSpan={7} className={styles.empty}>Sin sanciones en este período</td></tr>
              )}
              {items.map((s) => (
                <tr key={s.id}>
                  <td>{s.empleado_nombre}</td>
                  <td>{s.tipo}</td>
                  <td>{s.fecha}</td>
                  <td>{s.motivo}</td>
                  <td>
                    {s.anulada ? (
                      <span className={styles.badgeOrange}>Anulada</span>
                    ) : (
                      <span className={styles.badgeRed}>Vigente</span>
                    )}
                  </td>
                  <td>{s.fecha_desde || '-'}</td>
                  <td>{s.fecha_hasta || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {(por_tipo.length > 0 || por_empleado.length > 0) && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--spacing-lg)', marginTop: 'var(--spacing-lg)' }}>
            {por_tipo.length > 0 && (
              <div className={styles.subSection}>
                <h3>Por tipo</h3>
                <table className={styles.table}>
                  <thead>
                    <tr><th>Tipo</th><th className={styles.textRight}>Cantidad</th></tr>
                  </thead>
                  <tbody>
                    {por_tipo.map((t) => (
                      <tr key={t.tipo}>
                        <td>{t.tipo}</td>
                        <td className={styles.textRight}>{t.cantidad}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {por_empleado.length > 0 && (
              <div className={styles.subSection}>
                <h3>Por empleado</h3>
                <table className={styles.table}>
                  <thead>
                    <tr><th>Empleado</th><th className={styles.textRight}>Cantidad</th></tr>
                  </thead>
                  <tbody>
                    {por_empleado.map((e) => (
                      <tr key={e.empleado}>
                        <td>{e.empleado}</td>
                        <td className={styles.textRight}>{e.cantidad}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </>
    );
  };

  const renderVacaciones = () => {
    if (!vacData) return <div className={styles.empty}>Seleccioná año y hacé clic en Generar</div>;

    const {
      items, total_empleados, total_dias_correspondientes,
      total_dias_gozados, total_dias_pendientes,
    } = vacData;

    return (
      <>
        <div className={styles.summaryCards}>
          <div className={styles.summaryCard}>
            <div className={styles.summaryBlue}>{total_empleados}</div>
            <div className={styles.summaryLabel}>Empleados</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryValue}>{total_dias_correspondientes}</div>
            <div className={styles.summaryLabel}>Días Correspondientes</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryGreen}>{total_dias_gozados}</div>
            <div className={styles.summaryLabel}>Días Gozados</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryOrange}>{total_dias_pendientes}</div>
            <div className={styles.summaryLabel}>Días Pendientes</div>
          </div>
        </div>

        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Empleado</th>
                <th>Legajo</th>
                <th>Área</th>
                <th className={styles.textCenter}>Antigüedad</th>
                <th className={styles.textCenter}>Correspondientes</th>
                <th className={styles.textCenter}>Gozados</th>
                <th className={styles.textCenter}>Pendientes</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr><td colSpan={7} className={styles.empty}>Sin períodos generados para este año</td></tr>
              )}
              {items.map((row) => (
                <tr key={row.empleado_id}>
                  <td>{row.nombre}</td>
                  <td>{row.legajo}</td>
                  <td>{row.area}</td>
                  <td className={styles.textCenter}>{row.antiguedad_anios} años</td>
                  <td className={styles.textCenter}>{row.dias_correspondientes}</td>
                  <td className={styles.textCenter}>
                    <span className={styles.badgeGreen}>{row.dias_gozados}</span>
                  </td>
                  <td className={styles.textCenter}>
                    {row.dias_pendientes > 0 ? (
                      <span className={styles.badgeOrange}>{row.dias_pendientes}</span>
                    ) : (
                      <span className={styles.badgeGreen}>0</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>
    );
  };

  const renderCuentaCorriente = () => {
    if (!ccData) return <div className={styles.empty}>Hacé clic en Generar para ver el resumen</div>;

    const { items, total_cuentas, total_saldo, con_deuda, sin_saldo } = ccData;

    return (
      <>
        <div className={styles.summaryCards}>
          <div className={styles.summaryCard}>
            <div className={styles.summaryBlue}>{total_cuentas}</div>
            <div className={styles.summaryLabel}>Cuentas</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={total_saldo > 0 ? styles.summaryRed : styles.summaryGreen}>
              {formatCurrency(total_saldo)}
            </div>
            <div className={styles.summaryLabel}>Saldo Total</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryRed}>{con_deuda}</div>
            <div className={styles.summaryLabel}>Con Deuda</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryGreen}>{sin_saldo}</div>
            <div className={styles.summaryLabel}>Sin Saldo</div>
          </div>
        </div>

        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Empleado</th>
                <th>Legajo</th>
                <th>Área</th>
                <th className={styles.textRight}>Saldo</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr><td colSpan={5} className={styles.empty}>Sin cuentas corrientes</td></tr>
              )}
              {items.map((row) => (
                <tr key={row.empleado_id} className={row.saldo > 0 ? styles.rowWarning : undefined}>
                  <td>{row.nombre}</td>
                  <td>{row.legajo}</td>
                  <td>{row.area}</td>
                  <td className={styles.textRight}>
                    <strong>{formatCurrency(row.saldo)}</strong>
                  </td>
                  <td>
                    {row.saldo > 0 ? (
                      <span className={styles.badgeRed}>Debe</span>
                    ) : row.saldo < 0 ? (
                      <span className={styles.badgeBlue}>Crédito</span>
                    ) : (
                      <span className={styles.badgeGreen}>Sin saldo</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>
    );
  };

  const renderHoras = () => {
    if (!horasData) return <div className={styles.empty}>Seleccioná mes/año y hacé clic en Generar</div>;

    const { items, total_empleados } = horasData;

    return (
      <>
        <div className={styles.summaryCards}>
          <div className={styles.summaryCard}>
            <div className={styles.summaryBlue}>{total_empleados}</div>
            <div className={styles.summaryLabel}>Empleados</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryGreen}>
              {items.reduce((s, i) => s + i.total_horas, 0).toFixed(1)}
            </div>
            <div className={styles.summaryLabel}>Total Horas</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryOrange}>
              {items.reduce((s, i) => s + i.dias_incompletos, 0)}
            </div>
            <div className={styles.summaryLabel}>Días Incompletos</div>
          </div>
        </div>

        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Empleado</th>
                <th>Legajo</th>
                <th className={styles.textRight}>Horas</th>
                <th className={styles.textCenter}>Días</th>
                <th className={styles.textCenter}>Completos</th>
                <th className={styles.textCenter}>Incompletos</th>
                <th className={styles.textCenter}>Detalle</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr><td colSpan={7} className={styles.empty}>Sin fichadas en este período</td></tr>
              )}
              {items.map((row) => (
                <Fragment key={row.empleado_id}>
                  <tr>
                    <td>{row.nombre}</td>
                    <td>{row.legajo}</td>
                    <td className={styles.textRight}><strong>{row.total_horas.toFixed(1)}h</strong></td>
                    <td className={styles.textCenter}>{row.dias_trabajados}</td>
                    <td className={styles.textCenter}>
                      <span className={styles.badgeGreen}>{row.dias_completos}</span>
                    </td>
                    <td className={styles.textCenter}>
                      {row.dias_incompletos > 0 ? (
                        <span className={styles.badgeOrange}>{row.dias_incompletos}</span>
                      ) : '0'}
                    </td>
                    <td className={styles.textCenter}>
                      {row.detalle && row.detalle.length > 0 && (
                        <button
                          className={styles.detailToggle}
                          onClick={() => toggleHorasDetalle(row.empleado_id)}
                        >
                          {expandedHoras[row.empleado_id] ? (
                            <ChevronUp size={14} />
                          ) : (
                            <ChevronDown size={14} />
                          )}
                        </button>
                      )}
                    </td>
                  </tr>
                  {expandedHoras[row.empleado_id] && row.detalle && (
                    <tr className={styles.detailRow}>
                      <td colSpan={7}>
                        <table className={styles.miniTable}>
                          <thead>
                            <tr>
                              <th>Fecha</th>
                              <th>Fichadas</th>
                              <th>Horas</th>
                              <th>Estado</th>
                            </tr>
                          </thead>
                          <tbody>
                            {row.detalle.map((d) => (
                              <tr key={d.fecha}>
                                <td>{d.fecha}</td>
                                <td>{d.fichadas}</td>
                                <td>{d.horas.toFixed(1)}h</td>
                                <td>
                                  {d.completo ? (
                                    <span className={styles.badgeGreen}>Completo</span>
                                  ) : (
                                    <span className={styles.badgeOrange}>
                                      <AlertTriangle size={10} /> Incompleto
                                    </span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </>
    );
  };

  const renderContent = () => {
    if (loading) return <div className={styles.loading}>Cargando reporte...</div>;

    if (activeTab === 'presentismo') return renderPresentismo();
    if (activeTab === 'sanciones') return renderSanciones();
    if (activeTab === 'vacaciones') return renderVacaciones();
    if (activeTab === 'cuenta-corriente') return renderCuentaCorriente();
    if (activeTab === 'horas') return renderHoras();
    return null;
  };

  if (!tienePermiso('rrhh.ver')) {
    return (
      <div className={styles.container}>
        <div className={styles.empty}>No tenés permiso para ver reportes RRHH</div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <BarChart3 size={24} />
          <h1>Reportes RRHH</h1>
        </div>
      </div>

      {/* Tabs */}
      <div className={styles.tabs}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={activeTab === tab.id ? styles.tabActive : styles.tab}
            onClick={() => setActiveTab(tab.id)}
          >
            <tab.icon size={16} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Filters + Actions */}
      <div className={styles.filters}>
        {renderFilters()}
        <button
          className={styles.btnPrimary}
          onClick={handleGenerar}
          disabled={loading}
        >
          <RefreshCw size={14} />
          {loading ? 'Cargando...' : 'Generar'}
        </button>
        {hasData() && (
          <button
            className={styles.btnExport}
            onClick={handleExportar}
            disabled={exporting}
          >
            <Download size={14} />
            {exporting ? 'Exportando...' : 'Exportar Excel'}
          </button>
        )}
      </div>

      {/* Error */}
      {error && <div className={styles.error}>{error}</div>}

      {/* Content */}
      {renderContent()}
    </div>
  );
}

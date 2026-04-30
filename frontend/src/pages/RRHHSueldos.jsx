import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI, horasExtrasApi } from '../services/api';
import {
  DollarSign,
  Download,
  RotateCcw,
  AlertTriangle,
  Clock,
  FileSpreadsheet,
  Eye,
} from 'lucide-react';
import * as XLSX from 'xlsx';
import SearchInput from '../components/SearchInput';
import styles from './RRHHSueldos.module.css';

/**
 * RRHHSueldos.jsx — Pantalla de "Sueldos".
 *
 * Contiene dos secciones:
 *  1. Datos bancarios (sin cambios desde Batch 0).
 *  2. Horas Extras del período liquidado (Batch 7 — T-7.2).
 *
 * NOTA columnas Excel HE → flujo de liquidación de sueldos (T-7.3):
 *   El export que dispara `horasExtrasApi.exportarXlsx({ periodo })` retorna
 *   estas columnas en castellano rioplatense (DD/MM/YYYY, decimal con coma):
 *     Legajo · Apellido y Nombre · CUIL · Fecha · Tipo de día ·
 *     Minutos extra · % Recargo · Estado · Observaciones · Motivo de rechazo.
 *   La tabla agregada en pantalla muestra: Legajo · Apellido y Nombre ·
 *   Total Horas 50% · Total Horas 100% · Total Horas Equivalentes (con recargo).
 *   Convención horas equivalentes = horas_50% * 1.5 + horas_100% * 2.0.
 *   IMPORTANTE: este formato debe revisarse con el equipo de sueldos antes
 *   del primer uso productivo. Si requieren CUIL en la grilla, separar
 *   "Apellido" y "Nombre" en columnas distintas, o cualquier otro ajuste,
 *   se modifica el endpoint backend (router `rrhh_horas_extras.exportar_excel`).
 */

const HE_PAGE_SIZE_CAP = 1000; // soft cap T-7.2 (>1000 → loopear o pedir endpoint agregado).

// Período por defecto: mes anterior al actual.
function periodoMesAnterior() {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth(); // 0-indexed; mes anterior es `m` directamente, salvo enero.
  const yy = m === 0 ? y - 1 : y;
  const mm = m === 0 ? 12 : m;
  return `${yy}${String(mm).padStart(2, '0')}`;
}

// Convierte 'YYYYMM' a 'YYYY-MM' (formato del input type="month").
function periodoToMonthInput(periodo) {
  if (!/^\d{6}$/.test(periodo)) return '';
  return `${periodo.slice(0, 4)}-${periodo.slice(4)}`;
}

// Convierte 'YYYY-MM' (input type="month") a 'YYYYMM'.
function monthInputToPeriodo(value) {
  if (!/^\d{4}-\d{2}$/.test(value)) return '';
  return value.replace('-', '');
}

// Formatea minutos a "Hh Mm" (ej: 95 → "1h 35m"). Si 0 → "0h".
function formatMinutos(minutos) {
  if (!minutos || minutos <= 0) return '0h';
  const h = Math.floor(minutos / 60);
  const m = minutos % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

// Formatea un número con separador decimal coma (es-AR).
function formatNumeroAR(num, decimales = 2) {
  if (num === null || num === undefined || Number.isNaN(num)) return '0';
  return num.toLocaleString('es-AR', {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
}

export default function RRHHSueldos() {
  const { tienePermiso } = usePermisos();
  const navigate = useNavigate();

  // ── Datos bancarios (sección existente, sin cambios funcionales) ──
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');

  // ── Horas Extras del período (Batch 7 — T-7.2) ────────────────────
  const puedeVerHE = tienePermiso('rrhh.ver_horas_extras');
  const [periodoHE, setPeriodoHE] = useState(periodoMesAnterior);
  const [bloquesHE, setBloquesHE] = useState([]);
  const [loadingHE, setLoadingHE] = useState(false);
  const [errorHE, setErrorHE] = useState(null);
  const [exportandoHE, setExportandoHE] = useState(false);
  const [truncadoHE, setTruncadoHE] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await rrhhAPI.listarDatosBancarios();
      setData(res.data || []);
    } catch {
      setError('Error al cargar datos bancarios');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // ── Fetch HE liquidadas del período seleccionado ──────────────────
  const fetchHorasExtras = useCallback(async () => {
    if (!puedeVerHE) return;
    if (!/^\d{6}$/.test(periodoHE)) {
      setBloquesHE([]);
      setErrorHE(null);
      return;
    }
    setLoadingHE(true);
    setErrorHE(null);
    setTruncadoHE(false);
    try {
      const { data: resp } = await horasExtrasApi.list({
        estado: 'liquidada',
        periodo: periodoHE,
        page: 1,
        page_size: HE_PAGE_SIZE_CAP,
      });
      const items = Array.isArray(resp?.items) ? resp.items : [];
      const total = typeof resp?.total === 'number' ? resp.total : items.length;
      setBloquesHE(items);
      // Si el total reportado excede lo recibido → indicamos truncado.
      if (total > items.length) {
        setTruncadoHE(true);
      }
    } catch (err) {
      setErrorHE(err?.response?.data?.detail || 'Error al cargar horas extras del período');
      setBloquesHE([]);
    } finally {
      setLoadingHE(false);
    }
  }, [puedeVerHE, periodoHE]);

  useEffect(() => {
    fetchHorasExtras();
  }, [fetchHorasExtras]);

  // ── Aggregación por empleado de los bloques HE liquidados ─────────
  // Acumula minutos al 50% (tipo_dia === 'habil_50') y al 100%
  // (tipo_dia ∈ {'sabado_100', 'domingo_100', 'feriado_100'}).
  // 'manual' se cuenta según porcentaje_recargo: <100 → 50%, ≥100 → 100%.
  // NOTA: estos useMemo deben declararse ANTES del early return de permisos
  // para no violar rules-of-hooks (orden estable de hooks por render).
  const empleadosHE = useMemo(() => {
    const acc = new Map();
    for (const b of bloquesHE) {
      const empId = b.empleado_id;
      if (!acc.has(empId)) {
        acc.set(empId, {
          empleado_id: empId,
          legajo: b.legajo || '-',
          apellido_nombre: b.empleado_nombre || `#${empId}`,
          minutos_50: 0,
          minutos_100: 0,
        });
      }
      const ref = acc.get(empId);
      const minutos = Number(b.minutos_extra ?? b.extras_minutos ?? 0) || 0;
      const tipo = b.tipo_dia;
      if (tipo === 'habil_50') {
        ref.minutos_50 += minutos;
      } else if (tipo === 'sabado_100' || tipo === 'domingo_100' || tipo === 'feriado_100') {
        ref.minutos_100 += minutos;
      } else {
        // 'manual' u otro: clasificamos por porcentaje_recargo.
        const pct = Number(b.porcentaje_recargo ?? 0) || 0;
        if (pct >= 100) {
          ref.minutos_100 += minutos;
        } else {
          ref.minutos_50 += minutos;
        }
      }
    }
    return Array.from(acc.values()).sort((a, b) =>
      String(a.apellido_nombre).localeCompare(String(b.apellido_nombre), 'es')
    );
  }, [bloquesHE]);

  const resumenHE = useMemo(() => {
    const totalEmpleados = empleadosHE.length;
    const totalMin50 = empleadosHE.reduce((s, e) => s + e.minutos_50, 0);
    const totalMin100 = empleadosHE.reduce((s, e) => s + e.minutos_100, 0);
    return {
      totalEmpleados,
      totalHoras50: totalMin50 / 60,
      totalHoras100: totalMin100 / 60,
    };
  }, [empleadosHE]);

  if (!tienePermiso('rrhh.ver')) {
    return <div className={styles.container}>No tienes permiso para ver esta sección.</div>;
  }

  const normalizedSearch = searchTerm.toLowerCase().trim();
  const filteredData = normalizedSearch
    ? data.filter((e) => {
        const fullName = `${e.apellido} ${e.nombre}`.toLowerCase();
        const legajo = String(e.legajo || '').toLowerCase();
        const cuil = String(e.cuil || '').toLowerCase();
        return fullName.includes(normalizedSearch) || legajo.includes(normalizedSearch) || cuil.includes(normalizedSearch);
      })
    : data;

  const incompleteCount = filteredData.filter((e) => !e.banco_cbu).length;

  const handleExportXLSX = () => {
    const wsData = filteredData.map((e) => ({
      Legajo: e.legajo,
      Apellido: e.apellido,
      Nombre: e.nombre,
      CUIL: e.cuil || '',
      Empresa: e.empresa_nombre || '',
      Banco: e.banco_nombre || '',
      'Tipo Cuenta': e.banco_tipo_cuenta || '',
      CBU: e.banco_cbu || '',
      'Alias CBU': e.banco_alias || '',
      'Nro Cuenta': e.banco_nro_cuenta || '',
    }));
    const ws = XLSX.utils.json_to_sheet(wsData);
    // Auto-width columns
    const colWidths = Object.keys(wsData[0] || {}).map((key) => ({
      wch: Math.max(key.length, ...wsData.map((r) => String(r[key] || '').length)) + 2,
    }));
    ws['!cols'] = colWidths;
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Datos Bancarios');
    XLSX.writeFile(wb, `datos_bancarios_${new Date().toISOString().slice(0, 10)}.xlsx`);
  };

  const handleVerDetalleHE = () => {
    if (!/^\d{6}$/.test(periodoHE)) return;
    navigate(`/rrhh/horas-extras?periodo=${periodoHE}&estado=liquidada`);
  };

  const handleDescargarExcelHE = async () => {
    if (!/^\d{6}$/.test(periodoHE)) {
      setErrorHE('Seleccioná un período válido (YYYYMM) para exportar.');
      return;
    }
    setExportandoHE(true);
    setErrorHE(null);
    try {
      const res = await horasExtrasApi.exportarXlsx({ periodo: periodoHE });
      const blob = new Blob([res.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `horas_extras_${periodoHE}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setErrorHE(err?.response?.data?.detail || 'Error al exportar Excel de horas extras');
    } finally {
      setExportandoHE(false);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <DollarSign size={24} />
          <h1>Sueldos — Datos Bancarios</h1>
        </div>
        <div className={styles.headerActions}>
          <button className={styles.btnExport} onClick={handleExportXLSX} disabled={filteredData.length === 0}>
            <Download size={14} />
            Exportar CSV
          </button>
          <button className={styles.btnRefresh} onClick={fetchData} aria-label="Refrescar datos">
            <RotateCcw size={14} />
          </button>
        </div>
      </div>

      {incompleteCount > 0 && (
        <div className={styles.warningBanner}>
          <AlertTriangle size={16} />
          {incompleteCount} empleado{incompleteCount !== 1 ? 's' : ''} sin datos bancarios cargados
        </div>
      )}

      <SearchInput
        value={searchTerm}
        onChange={setSearchTerm}
        placeholder="Buscar por nombre, legajo o CUIL..."
        className={styles.filters}
      />

      {loading && <div className={styles.loading}>Cargando datos bancarios...</div>}
      {error && <div className={styles.error}>{error}</div>}

      {!loading && !error && (
        <div className={styles.tableContainer}>
          {filteredData.length === 0 ? (
            <div className={styles.empty}>No se encontraron empleados</div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Legajo</th>
                  <th>Apellido</th>
                  <th>Nombre</th>
                  <th>CUIL</th>
                  <th>Empresa</th>
                  <th>Banco</th>
                  <th>Tipo Cuenta</th>
                  <th>CBU</th>
                  <th>Alias</th>
                  <th>Nro. Cuenta</th>
                </tr>
              </thead>
              <tbody>
                {filteredData.map((e) => (
                  <tr key={e.id || e.legajo} className={!e.banco_cbu ? styles.rowIncomplete : undefined}>
                    <td>{e.legajo}</td>
                    <td>{e.apellido}</td>
                    <td>{e.nombre}</td>
                    <td>{e.cuil || '-'}</td>
                    <td>{e.empresa_nombre || '-'}</td>
                    <td>{e.banco_nombre || '-'}</td>
                    <td>{e.banco_tipo_cuenta || '-'}</td>
                    <td>{e.banco_cbu || '-'}</td>
                    <td>{e.banco_alias || '-'}</td>
                    <td>{e.banco_nro_cuenta || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Sección: Horas Extras del período (Batch 7 — T-7.2) ── */}
      {puedeVerHE && (
        <section className={styles.heSection} aria-labelledby="he-section-title">
          <div className={styles.heHeader}>
            <div className={styles.headerTitle}>
              <Clock size={22} />
              <h2 id="he-section-title" className={styles.heTitle}>
                Horas Extras del Período
              </h2>
            </div>
            <div className={styles.heHeaderActions}>
              <label className={styles.heLabel} htmlFor="he-periodo-input">
                Período
              </label>
              <input
                id="he-periodo-input"
                type="month"
                className={styles.input}
                value={periodoToMonthInput(periodoHE)}
                onChange={(e) => setPeriodoHE(monthInputToPeriodo(e.target.value))}
                aria-label="Período de liquidación (mes/año)"
              />
              <button
                className={styles.btnRefresh}
                onClick={fetchHorasExtras}
                aria-label="Refrescar horas extras"
                disabled={loadingHE}
              >
                <RotateCcw size={14} />
              </button>
            </div>
          </div>

          {/* Resumen agregado */}
          <div className={styles.heStats} role="group" aria-label="Resumen de horas extras del período">
            <div className={styles.heStatCard}>
              <span className={styles.heStatLabel}>Empleados con HE</span>
              <span className={styles.heStatValue}>{resumenHE.totalEmpleados}</span>
            </div>
            <div className={styles.heStatCard}>
              <span className={styles.heStatLabel}>Total horas 50%</span>
              <span className={styles.heStatValue}>{formatNumeroAR(resumenHE.totalHoras50)}</span>
            </div>
            <div className={styles.heStatCard}>
              <span className={styles.heStatLabel}>Total horas 100%</span>
              <span className={styles.heStatValue}>{formatNumeroAR(resumenHE.totalHoras100)}</span>
            </div>
            <div className={styles.heStatActions}>
              <button
                className={styles.btnSecondary}
                onClick={handleVerDetalleHE}
                disabled={!/^\d{6}$/.test(periodoHE)}
                title="Ver detalle en módulo Horas Extras"
              >
                <Eye size={14} />
                Ver detalle
              </button>
              <button
                className={styles.btnExport}
                onClick={handleDescargarExcelHE}
                disabled={exportandoHE || !/^\d{6}$/.test(periodoHE)}
                title="Descargar Excel del período"
              >
                <FileSpreadsheet size={14} />
                {exportandoHE ? 'Descargando…' : 'Descargar Excel'}
              </button>
            </div>
          </div>

          {truncadoHE && (
            <div className={styles.warningBanner}>
              <AlertTriangle size={16} />
              Se mostraron los primeros {HE_PAGE_SIZE_CAP} bloques. El total del período supera ese límite —
              usá "Ver detalle" o "Descargar Excel" para obtener el set completo.
            </div>
          )}

          {errorHE && <div className={styles.error}>{errorHE}</div>}

          {loadingHE && <div className={styles.loading}>Cargando horas extras del período...</div>}

          {!loadingHE && !errorHE && (
            <div className={styles.tableContainer}>
              {empleadosHE.length === 0 ? (
                <div className={styles.empty}>
                  No hay horas extras liquidadas para el período {periodoHE || '—'}.
                </div>
              ) : (
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Legajo</th>
                      <th>Apellido y Nombre</th>
                      <th className={styles.colNumeric}>Horas 50%</th>
                      <th className={styles.colNumeric}>Horas 100%</th>
                      <th className={styles.colNumeric}>Horas equivalentes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {empleadosHE.map((e) => {
                      const horas50 = e.minutos_50 / 60;
                      const horas100 = e.minutos_100 / 60;
                      // Convención: horas equivalentes = h50 * 1.5 + h100 * 2.0.
                      const horasEq = horas50 * 1.5 + horas100 * 2.0;
                      return (
                        <tr key={e.empleado_id}>
                          <td>{e.legajo}</td>
                          <td>{e.apellido_nombre}</td>
                          <td className={styles.colNumeric} title={formatMinutos(e.minutos_50)}>
                            {formatNumeroAR(horas50)}
                          </td>
                          <td className={styles.colNumeric} title={formatMinutos(e.minutos_100)}>
                            {formatNumeroAR(horas100)}
                          </td>
                          <td className={styles.colNumeric}>{formatNumeroAR(horasEq)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

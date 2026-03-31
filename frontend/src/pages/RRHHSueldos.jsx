import { useState, useEffect } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI } from '../services/api';
import { DollarSign, Download, Search, RotateCcw, AlertTriangle } from 'lucide-react';
import * as XLSX from 'xlsx';
import styles from './RRHHSueldos.module.css';

export default function RRHHSueldos() {
  const { tienePermiso } = usePermisos();
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');

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

      <div className={styles.filters}>
        <Search size={16} style={{ color: 'var(--cf-text-tertiary)' }} />
        <input
          type="text"
          className={styles.input}
          placeholder="Buscar por nombre, legajo o CUIL..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
      </div>

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
    </div>
  );
}

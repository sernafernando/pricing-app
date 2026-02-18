import { useState, useEffect, useCallback, useRef } from 'react';
import { Upload, MapPin, ExternalLink, RefreshCw, AlertCircle, CheckCircle } from 'lucide-react';
import api from '../services/api';
import styles from './TabCodigosPostales.module.css';

const CORDONES = ['CABA', 'Cordón 1', 'Cordón 2', 'Cordón 3'];

export default function TabCodigosPostales() {
  const [codigosPostales, setCodigosPostales] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filtros
  const [search, setSearch] = useState('');
  const [filtroCordon, setFiltroCordon] = useState('');
  const [soloSinAsignar, setSoloSinAsignar] = useState(false);

  // Upload
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const fileInputRef = useRef(null);

  // Actualizando cordón
  const [actualizando, setActualizando] = useState(new Set());

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (search) params.append('search', search);
      if (filtroCordon) params.append('cordon', filtroCordon);
      if (soloSinAsignar) params.append('sin_asignar', 'true');

      const [cpResponse, statsResponse] = await Promise.all([
        api.get(`/codigos-postales?${params}`),
        api.get('/codigos-postales/estadisticas'),
      ]);

      setCodigosPostales(cpResponse.data);
      setEstadisticas(statsResponse.data);
    } catch (err) {
      setError('Error cargando códigos postales');
    } finally {
      setLoading(false);
    }
  }, [search, filtroCordon, soloSinAsignar]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  const actualizarCordon = async (codigoPostal, nuevoCordon) => {
    setActualizando(prev => new Set([...prev, codigoPostal]));

    try {
      const cordonValue = nuevoCordon === '' ? null : nuevoCordon;
      await api.put(`/codigos-postales/${codigoPostal}/cordon`, {
        cordon: cordonValue,
      });

      // Actualizar localmente
      setCodigosPostales(prev =>
        prev.map(cp =>
          cp.codigo_postal === codigoPostal
            ? { ...cp, cordon: cordonValue }
            : cp
        )
      );

      // Refrescar estadísticas
      const statsResponse = await api.get('/codigos-postales/estadisticas');
      setEstadisticas(statsResponse.data);
    } catch (err) {
      alert(`Error actualizando cordón: ${err.response?.data?.detail || err.message}`);
    } finally {
      setActualizando(prev => {
        const next = new Set(prev);
        next.delete(codigoPostal);
        return next;
      });
    }
  };

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadResult(null);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await api.post('/codigos-postales/import-xlsx', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      setUploadResult(response.data);
      // Refrescar datos
      cargarDatos();
    } catch (err) {
      setUploadResult({
        errores: 1,
        detalle_errores: [err.response?.data?.detail || err.message],
      });
    } finally {
      setUploading(false);
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const getCordonBadgeClass = (cordon) => {
    if (!cordon) return styles.cordonSinAsignar;
    switch (cordon) {
      case 'CABA': return styles.cordonCaba;
      case 'Cordón 1': return styles.cordonUno;
      case 'Cordón 2': return styles.cordonDos;
      case 'Cordón 3': return styles.cordonTres;
      default: return styles.cordonSinAsignar;
    }
  };

  return (
    <div className={styles.container}>
      {/* Estadísticas */}
      {estadisticas && (
        <div className={styles.statsGrid}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{estadisticas.total_cps}</div>
            <div className={styles.statLabel}>CPs totales</div>
          </div>
          <div className={styles.statCard}>
            <div className={`${styles.statValue} ${styles.sinAsignarValue}`}>
              {estadisticas.sin_asignar}
            </div>
            <div className={styles.statLabel}>Sin asignar</div>
          </div>
          {Object.entries(estadisticas.por_cordon).map(([cordon, cantidad]) => (
            <div key={cordon} className={styles.statCard}>
              <div className={styles.statValue}>{cantidad}</div>
              <div className={styles.statLabel}>{cordon}</div>
            </div>
          ))}
        </div>
      )}

      {/* Controles */}
      <div className={styles.controls}>
        <div className={styles.filtros}>
          <input
            type="text"
            placeholder="Buscar CP o localidad..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={styles.searchInput}
          />

          <select
            value={filtroCordon}
            onChange={(e) => setFiltroCordon(e.target.value)}
            className={styles.select}
          >
            <option value="">Todos los cordones</option>
            {CORDONES.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          <button
            onClick={() => setSoloSinAsignar(!soloSinAsignar)}
            className={`btn-tesla sm ${soloSinAsignar ? 'outline-subtle-primary toggle-active' : 'secondary'}`}
          >
            {soloSinAsignar ? '✓ ' : ''}Sin asignar
          </button>
        </div>

        <div className={styles.actions}>
          <button
            onClick={cargarDatos}
            className={styles.btnRefresh}
            disabled={loading}
            aria-label="Actualizar lista"
          >
            <RefreshCw size={16} />
            Actualizar
          </button>

          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls"
            onChange={handleUpload}
            className={styles.fileInputHidden}
            id="xlsx-upload"
          />
          <label
            htmlFor="xlsx-upload"
            className={`${styles.btnUpload} ${uploading ? styles.btnDisabled : ''}`}
          >
            <Upload size={16} />
            {uploading ? 'Importando...' : 'Importar XLSX'}
          </label>
        </div>
      </div>

      {/* Resultado de upload */}
      {uploadResult && (
        <div className={uploadResult.errores > 0 && !uploadResult.creados ? styles.uploadError : styles.uploadSuccess}>
          {uploadResult.creados !== undefined && (
            <div className={styles.uploadStats}>
              <CheckCircle size={16} />
              <span>
                {uploadResult.creados} creados, {uploadResult.actualizados} actualizados
                {uploadResult.errores > 0 && `, ${uploadResult.errores} errores`}
              </span>
            </div>
          )}
          {uploadResult.detalle_errores?.length > 0 && (
            <div className={styles.uploadErrors}>
              <AlertCircle size={16} />
              <ul>
                {uploadResult.detalle_errores.slice(0, 5).map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </div>
          )}
          <button
            className={styles.btnDismiss}
            onClick={() => setUploadResult(null)}
            aria-label="Cerrar mensaje"
          >
            Cerrar
          </button>
        </div>
      )}

      {/* Tabla */}
      {loading ? (
        <div className={styles.loading}>Cargando códigos postales...</div>
      ) : error ? (
        <div className={styles.error}>{error}</div>
      ) : (
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Código Postal</th>
                <th>Localidad</th>
                <th>Cordón</th>
                <th>Envíos</th>
              </tr>
            </thead>
            <tbody>
              {codigosPostales.length === 0 ? (
                <tr>
                  <td colSpan={4} className={styles.empty}>
                    No hay códigos postales para mostrar
                  </td>
                </tr>
              ) : (
                codigosPostales.map((cp) => (
                  <tr key={cp.codigo_postal}>
                    <td>
                      <a
                        href={`https://www.google.com/maps/search/${cp.codigo_postal}+${cp.localidad || 'Buenos Aires'}+Argentina`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={styles.cpLink}
                        title={`Ver CP ${cp.codigo_postal} en Google Maps`}
                      >
                        <MapPin size={14} className={styles.cpIcon} />
                        <strong>{cp.codigo_postal}</strong>
                        <ExternalLink size={12} className={styles.externalIcon} />
                      </a>
                    </td>
                    <td className={styles.localidad}>
                      {cp.localidad || '-'}
                    </td>
                    <td>
                      <select
                        value={cp.cordon || ''}
                        onChange={(e) => actualizarCordon(cp.codigo_postal, e.target.value)}
                        disabled={actualizando.has(cp.codigo_postal)}
                        className={`${styles.cordonSelect} ${getCordonBadgeClass(cp.cordon)}`}
                      >
                        <option value="">Sin Asignar</option>
                        {CORDONES.map(c => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                    </td>
                    <td className={styles.cantidadEnvios}>
                      {cp.cantidad_envios}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer */}
      <div className={styles.footer}>
        <span>Mostrando {codigosPostales.length} códigos postales</span>
      </div>
    </div>
  );
}

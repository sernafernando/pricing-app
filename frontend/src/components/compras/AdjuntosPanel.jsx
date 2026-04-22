import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Upload,
  FileText,
  Trash2,
  Loader2,
  AlertCircle,
  Download,
} from 'lucide-react';
import api from '../../services/api';
import styles from './AdjuntosPanel.module.css';

const MAX_SIZE_MB = 20;
const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024;

const ACCEPT_MIME = [
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/webp',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/msword',
  'application/vnd.ms-excel',
].join(',');

const formatBytes = (bytes) => {
  if (bytes === null || bytes === undefined) return '—';
  const num = Number(bytes);
  if (Number.isNaN(num)) return '—';
  if (num < 1024) return `${num} B`;
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`;
  return `${(num / (1024 * 1024)).toFixed(2)} MB`;
};

const formatDate = (isoStr) => {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    return d.toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return isoStr;
  }
};

/**
 * AdjuntosPanel — panel reusable de adjuntos con drag & drop para
 * pedidos de compra y OPs.
 *
 * Props:
 *   - entidadTipo: 'pedido_compra' | 'orden_pago'
 *   - entidadId: number
 *   - canManage: boolean — si true, permite subir y eliminar
 */
export default function AdjuntosPanel({ entidadTipo, entidadId, canManage = false }) {
  const [adjuntos, setAdjuntos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  const basePath = entidadTipo === 'pedido_compra' ? 'pedidos' : 'ordenes-pago';

  const fetchAdjuntos = useCallback(async () => {
    if (!entidadId) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get(
        `/administracion/compras/${basePath}/${entidadId}/adjuntos`
      );
      setAdjuntos(data || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar adjuntos.');
    } finally {
      setLoading(false);
    }
  }, [basePath, entidadId]);

  useEffect(() => {
    fetchAdjuntos();
  }, [fetchAdjuntos]);

  const handleFiles = useCallback(
    async (files) => {
      const file = files?.[0];
      if (!file) return;
      if (file.size > MAX_SIZE_BYTES) {
        setError(`Archivo demasiado grande. Máximo ${MAX_SIZE_MB} MB.`);
        return;
      }
      const formData = new FormData();
      formData.append('file', file);
      try {
        setUploading(true);
        setError(null);
        await api.post(
          `/administracion/compras/${basePath}/${entidadId}/adjuntos`,
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' } }
        );
        await fetchAdjuntos();
      } catch (err) {
        setError(err.response?.data?.detail || 'Error al subir archivo.');
      } finally {
        setUploading(false);
        if (fileInputRef.current) fileInputRef.current.value = '';
      }
    },
    [basePath, entidadId, fetchAdjuntos]
  );

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    if (!canManage) return;
    handleFiles(Array.from(e.dataTransfer.files));
  };

  const handleEliminar = async (adjuntoId) => {
    try {
      setError(null);
      await api.delete(`/administracion/compras/adjuntos/${adjuntoId}`);
      await fetchAdjuntos();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al eliminar adjunto.');
    }
  };

  const downloadUrl = (adjuntoId) =>
    `${import.meta.env.VITE_API_URL}/administracion/compras/adjuntos/${adjuntoId}/descargar`;

  return (
    <div className={styles.adjuntosPanel}>
      {canManage && (
        <>
          <div
            className={`${styles.dropZone} ${dragOver ? styles.dropZoneActive : ''}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click();
            }}
            aria-label="Subir adjunto"
          >
            <Upload size={22} className={styles.dropIcon} />
            <span className={styles.dropPrimary}>
              Arrastrá un archivo acá o hacé click para seleccionar
            </span>
            <span className={styles.dropHint}>
              PDF, JPG, PNG, WebP, DOCX, XLSX · máx {MAX_SIZE_MB} MB
            </span>
            <input
              ref={fileInputRef}
              type="file"
              hidden
              accept={ACCEPT_MIME}
              onChange={(e) => handleFiles(Array.from(e.target.files))}
            />
          </div>
          {uploading && (
            <div className={styles.statusUploading}>
              <Loader2 size={14} className={styles.spin} /> Subiendo…
            </div>
          )}
        </>
      )}

      {error && (
        <div className={styles.errorBanner}>
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {loading ? (
        <div className={styles.empty}>
          <Loader2 size={14} className={styles.spin} /> Cargando adjuntos…
        </div>
      ) : adjuntos.length === 0 ? (
        <div className={styles.empty}>Sin archivos adjuntos.</div>
      ) : (
        <ul className={styles.lista}>
          {adjuntos.map((a) => (
            <li key={a.id} className={styles.adjuntoRow}>
              <FileText size={16} className={styles.fileIcon} />
              <div className={styles.adjuntoInfo}>
                <a
                  href={downloadUrl(a.id)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.adjuntoNombre}
                >
                  {a.nombre_archivo}
                </a>
                <span className={styles.adjuntoMeta}>
                  {formatBytes(a.tamano_bytes)} · {formatDate(a.created_at)}
                  {a.subido_por_nombre ? ` · ${a.subido_por_nombre}` : ''}
                  {a.tipo ? ` · ${a.tipo}` : ''}
                </span>
              </div>
              <div className={styles.adjuntoActions}>
                <a
                  href={downloadUrl(a.id)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.btnIcon}
                  aria-label="Descargar"
                  title="Descargar"
                >
                  <Download size={14} />
                </a>
                {canManage && (
                  <button
                    type="button"
                    className={`${styles.btnIcon} ${styles.btnDanger}`}
                    onClick={() => handleEliminar(a.id)}
                    aria-label="Eliminar adjunto"
                    title="Eliminar"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

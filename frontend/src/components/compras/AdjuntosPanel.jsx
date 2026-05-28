import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Upload,
  FileText,
  Trash2,
  Loader2,
  AlertCircle,
  Download,
  Eye,
  Check,
  X,
} from 'lucide-react';
import api from '../../services/api';
import styles from './AdjuntosPanel.module.css';

const MAX_SIZE_MB = 20;
const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024;
const MAX_FILES_PER_BATCH = 10;

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

const ACCEPTED_EXT = new Set([
  'pdf', 'jpg', 'jpeg', 'png', 'webp', 'docx', 'xlsx', 'doc', 'xls',
]);

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

const getExtension = (filename) => {
  if (!filename) return '';
  const idx = filename.lastIndexOf('.');
  if (idx < 0) return '';
  return filename.slice(idx + 1).toLowerCase();
};

/**
 * Pre-valida en el cliente (tamaño + extensión). El backend revalida con
 * magic bytes — este chequeo es solo para dar feedback rápido al usuario.
 * Retorna null si es válido, string con razón si no.
 */
const preValidarArchivo = (file) => {
  if (file.size > MAX_SIZE_BYTES) {
    return `Supera el máximo de ${MAX_SIZE_MB} MB`;
  }
  const ext = getExtension(file.name);
  if (ext && !ACCEPTED_EXT.has(ext)) {
    return `Formato .${ext} no permitido`;
  }
  return null;
};

/**
 * AdjuntosPanel — panel reusable de adjuntos con drag & drop multi-archivo
 * para pedidos de compra y OPs.
 *
 * Props:
 *   - entidadTipo: 'pedido_compra' | 'orden_pago'
 *   - entidadId: number
 *   - canManage: boolean — si true, permite subir y eliminar
 *
 * Upload behavior:
 *   - Hasta 10 archivos por batch (MAX_FILES_PER_BATCH).
 *   - Se suben uno por uno para tener feedback granular (pending → uploading → ok/error).
 *   - Si UN archivo falla, los otros siguen subiendo. El usuario ve el estado
 *     individual de cada uno en una lista inline.
 */
export default function AdjuntosPanel({ entidadTipo, entidadId, canManage = false }) {
  const [adjuntos, setAdjuntos] = useState([]);
  const [loading, setLoading] = useState(false);
  // uploads: array de { id, name, size, status: 'pending'|'uploading'|'ok'|'error', error?: string }
  const [uploads, setUploads] = useState([]);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  const BASE_PATH_MAP = {
    pedido_compra: 'pedidos',
    orden_pago: 'ordenes-pago',
    nota_credito_local: 'ncs-locales',
  };
  const basePath = BASE_PATH_MAP[entidadTipo] ?? 'pedidos';

  const fetchAdjuntos = useCallback(async () => {
    if (!entidadId) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get(
        `/administracion/compras/${basePath}/${entidadId}/adjuntos`,
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

  const subirUno = useCallback(
    async (uploadId, file) => {
      const formData = new FormData();
      formData.append('file', file);
      try {
        setUploads((prev) =>
          prev.map((u) => (u.id === uploadId ? { ...u, status: 'uploading' } : u)),
        );
        await api.post(
          `/administracion/compras/${basePath}/${entidadId}/adjuntos`,
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' } },
        );
        setUploads((prev) =>
          prev.map((u) => (u.id === uploadId ? { ...u, status: 'ok' } : u)),
        );
        return { ok: true };
      } catch (err) {
        const msg = err.response?.data?.detail || 'Error al subir archivo.';
        setUploads((prev) =>
          prev.map((u) =>
            u.id === uploadId ? { ...u, status: 'error', error: msg } : u,
          ),
        );
        return { ok: false };
      }
    },
    [basePath, entidadId],
  );

  const handleFiles = useCallback(
    async (files) => {
      if (!files || files.length === 0) return;
      setError(null);

      // Límite de batch
      let batch = Array.from(files);
      if (batch.length > MAX_FILES_PER_BATCH) {
        setError(
          `Máximo ${MAX_FILES_PER_BATCH} archivos por vez. Se procesarán los primeros ${MAX_FILES_PER_BATCH}.`,
        );
        batch = batch.slice(0, MAX_FILES_PER_BATCH);
      }

      // Pre-validar y crear entradas de uploads
      const nuevos = batch.map((file, idx) => {
        const razon = preValidarArchivo(file);
        return {
          id: `${Date.now()}-${idx}-${file.name}`,
          name: file.name,
          size: file.size,
          file,
          status: razon ? 'error' : 'pending',
          error: razon,
        };
      });

      setUploads((prev) => [...prev, ...nuevos]);

      // Subir secuencialmente los válidos (secuencial = feedback claro,
      // menos presión al server que paralelo masivo)
      const validos = nuevos.filter((u) => u.status === 'pending');
      let subidosOk = 0;
      for (const u of validos) {
        const res = await subirUno(u.id, u.file);
        if (res.ok) subidosOk += 1;
      }

      // Refetch solo una vez al final si hubo éxitos
      if (subidosOk > 0) {
        await fetchAdjuntos();
      }
    },
    [fetchAdjuntos, subirUno],
  );

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    if (!canManage) return;
    handleFiles(Array.from(e.dataTransfer.files));
  };

  const handleSelectFiles = (e) => {
    handleFiles(Array.from(e.target.files || []));
    // Reset para poder seleccionar el mismo archivo dos veces si se quiere
    if (fileInputRef.current) fileInputRef.current.value = '';
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

  const removerDeLista = (uploadId) => {
    setUploads((prev) => prev.filter((u) => u.id !== uploadId));
  };

  const limpiarCompletos = () => {
    setUploads((prev) => prev.filter((u) => u.status !== 'ok'));
  };

  /**
   * Descarga el adjunto como blob (con token de auth en header via axios).
   * Crea un object URL temporal y lo revoca después de disparar el click.
   */
  const handleDescargar = async (adjunto) => {
    try {
      const response = await api.get(
        `/administracion/compras/adjuntos/${adjunto.id}/descargar`,
        { responseType: 'blob' },
      );
      const blobUrl = URL.createObjectURL(response.data);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = adjunto.nombre_archivo;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al descargar el archivo.');
    }
  };

  /**
   * Vista previa inline: obtiene el blob con auth y lo abre en una pestaña
   * nueva como object URL. El navegador renderiza PDFs e imágenes directamente.
   */
  const handleVerInline = async (adjunto) => {
    try {
      const response = await api.get(
        `/administracion/compras/adjuntos/${adjunto.id}/descargar?inline=true`,
        { responseType: 'blob' },
      );
      const blobUrl = URL.createObjectURL(response.data);
      window.open(blobUrl, '_blank', 'noopener,noreferrer');
      // No revocamos inmediatamente: el navegador necesita el URL mientras
      // carga la pestaña. Se libera cuando el documento se descarga.
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al previsualizar el archivo.');
    }
  };

  const uploadsEnProgreso = uploads.some((u) => u.status === 'uploading' || u.status === 'pending');
  const hayCompletos = uploads.some((u) => u.status === 'ok');

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
            aria-label="Subir adjuntos"
          >
            <Upload size={22} className={styles.dropIcon} />
            <span className={styles.dropPrimary}>
              Arrastrá archivos acá o hacé click para seleccionar
            </span>
            <span className={styles.dropHint}>
              PDF, JPG, PNG, WebP, DOCX, XLSX · máx {MAX_SIZE_MB} MB · hasta {MAX_FILES_PER_BATCH} por vez
            </span>
            <input
              ref={fileInputRef}
              type="file"
              hidden
              multiple
              accept={ACCEPT_MIME}
              onChange={handleSelectFiles}
            />
          </div>

          {uploads.length > 0 && (
            <div className={styles.uploadsList}>
              <div className={styles.uploadsHeader}>
                <span>
                  {uploads.filter((u) => u.status === 'ok').length} de {uploads.length} subidos
                </span>
                {hayCompletos && !uploadsEnProgreso && (
                  <button
                    type="button"
                    className={styles.btnLink}
                    onClick={limpiarCompletos}
                    aria-label="Limpiar subidos"
                  >
                    Limpiar
                  </button>
                )}
              </div>
              <ul className={styles.uploadsItems}>
                {uploads.map((u) => (
                  <li key={u.id} className={styles.uploadRow}>
                    <div className={styles.uploadStatus}>
                      {u.status === 'pending' && (
                        <Loader2 size={14} className={styles.spinMuted} />
                      )}
                      {u.status === 'uploading' && (
                        <Loader2 size={14} className={styles.spin} />
                      )}
                      {u.status === 'ok' && (
                        <Check size={14} className={styles.iconOk} />
                      )}
                      {u.status === 'error' && (
                        <AlertCircle size={14} className={styles.iconError} />
                      )}
                    </div>
                    <div className={styles.uploadInfo}>
                      <span className={styles.uploadName}>{u.name}</span>
                      <span className={styles.uploadMeta}>
                        {formatBytes(u.size)}
                        {u.error ? ` · ${u.error}` : ''}
                      </span>
                    </div>
                    <button
                      type="button"
                      className={styles.btnIconSmall}
                      onClick={() => removerDeLista(u.id)}
                      disabled={u.status === 'uploading'}
                      aria-label="Quitar de la lista"
                      title={u.status === 'uploading' ? 'Subiendo…' : 'Quitar'}
                    >
                      <X size={12} />
                    </button>
                  </li>
                ))}
              </ul>
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
                <button
                  type="button"
                  className={styles.adjuntoNombreBtn}
                  onClick={() => handleVerInline(a)}
                  title="Ver archivo"
                >
                  {a.nombre_archivo}
                </button>
                <span className={styles.adjuntoMeta}>
                  {formatBytes(a.tamano_bytes)} · {formatDate(a.created_at)}
                  {a.subido_por_nombre ? ` · ${a.subido_por_nombre}` : ''}
                  {a.tipo ? ` · ${a.tipo}` : ''}
                </span>
              </div>
              <div className={styles.adjuntoActions}>
                <button
                  type="button"
                  className={styles.btnIcon}
                  onClick={() => handleVerInline(a)}
                  aria-label="Ver archivo"
                  title="Ver"
                >
                  <Eye size={14} />
                </button>
                <button
                  type="button"
                  className={styles.btnIcon}
                  onClick={() => handleDescargar(a)}
                  aria-label="Descargar archivo"
                  title="Descargar"
                >
                  <Download size={14} />
                </button>
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

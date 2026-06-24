import { useState, useEffect } from 'react';
import { Upload, FileText, Download, AlertTriangle, CheckCircle2, Loader2, X } from 'lucide-react';
import api from '../services/api';
import styles from './ReescribirLHModal.module.css';

export default function ReescribirLHModal({ onClose }) {
  const [file, setFile] = useState(null);
  const [targetY, setTargetY] = useState('450');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [feedback, setFeedback] = useState(null);

  const isTargetYValid = targetY !== '' && Number.isInteger(Number(targetY)) && Number(targetY) >= 0;

  // Close on Escape key — but not while processing
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && !loading) {
        onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [loading, onClose]);

  const handleFileChange = (e) => {
    setFile(e.target.files[0] || null);
    setError(null);
    setFeedback(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!file) {
      setError('Seleccioná un archivo .txt o .zip antes de procesar.');
      return;
    }

    if (!isTargetYValid) {
      setError('El offset Y debe ser un número entero >= 0.');
      return;
    }

    setLoading(true);
    setError(null);
    setFeedback(null);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('target_y', String(Number(targetY)));

    try {
      const response = await api.post('/etiquetas-envio/reescribir-lh', formData, {
        responseType: 'blob',
      });

      // Read feedback headers (axios lowercases keys)
      const detectadas = response.headers['x-etiquetas-detectadas'];
      const modificados = response.headers['x-lh-modificados'];
      const heterogeneo = response.headers['x-lh-heterogeneo'];
      const llWarning = response.headers['x-ll-warning'];

      // Derive filename from Content-Disposition or fallback
      let downloadName = 'etiqueta_corregido.txt';
      const disposition = response.headers['content-disposition'];
      if (disposition) {
        const match = disposition.match(/filename="?([^"]+)"?/);
        if (match) downloadName = match[1];
      }

      // Trigger download
      const blob = new Blob([response.data], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = downloadName;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);

      setFeedback({
        detectadas: detectadas ?? '?',
        modificados: modificados ?? '?',
        heterogeneo: heterogeneo === 'true',
        llWarning: llWarning || '',
        filename: downloadName,
      });
    } catch (err) {
      // Blob error bodies require .text() + JSON.parse to surface detail
      let detail = 'Error al procesar el archivo.';
      try {
        const text = await err.response?.data?.text?.();
        if (text) {
          const parsed = JSON.parse(text);
          detail = parsed?.detail || parsed?.error?.message || detail;
        }
      } catch {
        // ignore parse errors, keep default message
      }
      setError(detail);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        {/* Header */}
        <div className={styles.modalHeader}>
          <div className={styles.headerTitleGroup}>
            <FileText size={18} className={styles.headerIcon} />
            <div>
              <h3 className={styles.modalTitle}>Corregir etiquetas ^LH</h3>
              <p className={styles.modalSubtitle}>
                Corrige el offset vertical (^LH y) de etiquetas ZPL de Mercado Libre
              </p>
            </div>
          </div>
          <button
            className={styles.modalClose}
            onClick={onClose}
            aria-label="Cerrar modal"
            disabled={loading}
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className={styles.modalBody}>
          <form onSubmit={handleSubmit} className={styles.form}>
            {/* File picker */}
            <div className={styles.field}>
              <label className={styles.label} htmlFor="zpl-file-modal">
                Archivo de etiquetas
              </label>
              <div className={styles.fileInputWrapper}>
                <input
                  id="zpl-file-modal"
                  type="file"
                  accept=".txt,.zip"
                  onChange={handleFileChange}
                  className={styles.fileInput}
                  disabled={loading}
                />
                <div className={styles.fileInputDisplay}>
                  <Upload size={16} className={styles.uploadIcon} />
                  <span className={styles.fileInputText}>
                    {file ? file.name : 'Seleccionar archivo .txt o .zip'}
                  </span>
                </div>
              </div>
              <p className={styles.hint}>
                Archivos .txt (ZPL) o .zip con un archivo Envio-*.txt
              </p>
            </div>

            {/* Y offset input */}
            <div className={styles.field}>
              <label className={styles.label} htmlFor="target-y-modal">
                Offset Y (^LH y)
              </label>
              <input
                id="target-y-modal"
                type="number"
                min="0"
                step="1"
                value={targetY}
                onChange={(e) => setTargetY(e.target.value)}
                className={`${styles.input} ${!isTargetYValid && targetY !== '' ? styles.inputError : ''}`}
                disabled={loading}
                placeholder="450"
              />
              {!isTargetYValid && targetY !== '' && (
                <p className={styles.fieldError}>Debe ser un entero mayor o igual a 0.</p>
              )}
              <p className={styles.hint}>Valor por defecto: 450</p>
            </div>

            {/* Error state */}
            {error && (
              <div className={styles.errorBanner}>
                <AlertTriangle size={16} />
                <span>{error}</span>
              </div>
            )}

            {/* Success feedback */}
            {feedback && (
              <div className={styles.successSection}>
                <div className={styles.successBanner}>
                  <CheckCircle2 size={16} />
                  <span>
                    {feedback.detectadas} etiquetas, {feedback.modificados} corregidas —{' '}
                    <strong>{feedback.filename}</strong> descargado
                  </span>
                </div>

                {feedback.heterogeneo && (
                  <div className={styles.warningBanner}>
                    <AlertTriangle size={16} />
                    <span>
                      Los valores ^LH y eran heterogéneos en el archivo. Todos se normalizaron
                      al offset {targetY}.
                    </span>
                  </div>
                )}

                {feedback.llWarning && (
                  <div className={styles.warningBanner}>
                    <AlertTriangle size={16} />
                    <span>{feedback.llWarning}</span>
                  </div>
                )}
              </div>
            )}

            {/* Footer actions */}
            <div className={styles.footerActions}>
              <button
                type="button"
                className={styles.cancelButton}
                onClick={onClose}
                disabled={loading}
              >
                Cerrar
              </button>
              <button
                type="submit"
                className={styles.submitButton}
                disabled={loading || !file || !isTargetYValid}
              >
                {loading ? (
                  <>
                    <Loader2 size={16} className={styles.spinIcon} />
                    Procesando...
                  </>
                ) : (
                  <>
                    <Download size={16} />
                    Procesar y descargar
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

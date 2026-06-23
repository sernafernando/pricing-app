import { useState } from 'react';
import { Upload, FileText, Download, AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import api from '../services/api';
import styles from './ReescribirLH.module.css';

export default function ReescribirLH() {
  const [file, setFile] = useState(null);
  const [targetY, setTargetY] = useState('450');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [feedback, setFeedback] = useState(null);

  const isTargetYValid = targetY !== '' && Number.isInteger(Number(targetY)) && Number(targetY) >= 0;

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
    <div className={styles.page}>
      <div className={styles.header}>
        <FileText size={20} className={styles.headerIcon} />
        <div>
          <h1 className={styles.title}>Reescribir ^LH</h1>
          <p className={styles.subtitle}>
            Corrige el offset vertical (^LH y) de etiquetas ZPL de Mercado Libre
          </p>
        </div>
      </div>

      <div className={styles.card}>
        <form onSubmit={handleSubmit} className={styles.form}>
          {/* File picker */}
          <div className={styles.field}>
            <label className={styles.label} htmlFor="zpl-file">
              Archivo de etiquetas
            </label>
            <div className={styles.fileInputWrapper}>
              <input
                id="zpl-file"
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
            <label className={styles.label} htmlFor="target-y">
              Offset Y (^LH y)
            </label>
            <input
              id="target-y"
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

          {/* Submit button */}
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
        </form>

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
      </div>
    </div>
  );
}

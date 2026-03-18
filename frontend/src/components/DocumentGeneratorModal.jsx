/**
 * DocumentGeneratorModal - Modal reutilizable para generar PDFs.
 * Se monta en cualquier página que tenga un contexto de documentos.
 * 
 * Props:
 *   isOpen - boolean
 *   onClose - function
 *   contexto - string (pedidos, rrhh, envios, etc.)
 *   entityData - object (datos crudos de la entidad actual)
 */
import { useEffect } from 'react';
import { useDocumentGenerator } from '../hooks/useDocumentGenerator';
import { FileText, Loader2, AlertCircle, FileDown } from 'lucide-react';
import ModalTesla from './ModalTesla';
import styles from './DocumentGeneratorModal.module.css';

export default function DocumentGeneratorModal({ isOpen, onClose, contexto, entityData }) {
  const {
    templates,
    loading,
    generating,
    error,
    fetchTemplates,
    generatePdf,
  } = useDocumentGenerator(contexto);

  // Fetch templates when modal opens
  useEffect(() => {
    if (isOpen && contexto) {
      fetchTemplates();
    }
  }, [isOpen, contexto, fetchTemplates]);

  const handleGenerate = (templateId) => {
    generatePdf(templateId, entityData);
  };

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title="Generar documento"
      subtitle={`Contexto: ${contexto}`}
      size="md"
    >
      <div className={styles.container}>
        {/* Error */}
        {error && (
          <div className={styles.error}>
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        {/* Generating overlay */}
        {generating && (
          <div className={styles.generating}>
            <Loader2 size={24} className={styles.spin} />
            <span>Generando PDF...</span>
          </div>
        )}

        {/* Loading */}
        {loading ? (
          <div className={styles.loading}>
            <Loader2 size={20} className={styles.spin} />
            <span>Cargando templates...</span>
          </div>
        ) : templates.length === 0 ? (
          <div className={styles.empty}>
            <FileText size={32} />
            <p>No hay templates disponibles para este contexto.</p>
            <p className={styles.emptyHint}>
              Un usuario con permiso de diseño debe crear templates para &quot;{contexto}&quot;.
            </p>
          </div>
        ) : (
          <ul className={styles.templateList}>
            {templates.map((t) => (
              <li key={t.id} className={styles.templateItem}>
                <div className={styles.templateInfo}>
                  <FileText size={16} className={styles.templateIcon} />
                  <div className={styles.templateText}>
                    <span className={styles.templateName}>{t.nombre}</span>
                    {t.descripcion && (
                      <span className={styles.templateDesc}>{t.descripcion}</span>
                    )}
                  </div>
                </div>
                <button
                  className="btn-tesla outline-subtle-primary sm"
                  onClick={() => handleGenerate(t.id)}
                  disabled={generating}
                >
                  <FileDown size={14} />
                  Generar
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </ModalTesla>
  );
}

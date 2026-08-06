import { useState, useEffect, useRef } from 'react';
import { sectoresAPI, ticketsAPI } from '../services/api';
import ModalTesla, { ModalFooterButtons } from './ModalTesla';
import { Paperclip, X, ImagePlus, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react';
import styles from './TicketCreateModal.module.css';

const PRIORIDADES = [
  { value: 'baja', label: 'Baja' },
  { value: 'media', label: 'Media' },
  { value: 'alta', label: 'Alta' },
  { value: 'critica', label: 'Crítica' },
];

/**
 * Renders a dynamic form field based on the schema_campos definition.
 */
const DynamicField = ({ fieldKey, fieldDef, value, onChange }) => {
  const { tipo, label, requerido, opciones, descripcion } = fieldDef;

  const handleChange = (val) => onChange(fieldKey, val);

  switch (tipo) {
    case 'text':
      return (
        <div className={styles.formGroup}>
          <label className={requerido ? styles.required : ''}>{label || fieldKey}</label>
          <textarea
            className={styles.textarea}
            value={value || ''}
            onChange={(e) => handleChange(e.target.value)}
            placeholder={descripcion || ''}
            rows={3}
          />
        </div>
      );
    case 'string':
      return (
        <div className={styles.formGroup}>
          <label className={requerido ? styles.required : ''}>{label || fieldKey}</label>
          <input
            type="text"
            className={styles.input}
            value={value || ''}
            onChange={(e) => handleChange(e.target.value)}
            placeholder={descripcion || ''}
          />
        </div>
      );
    case 'integer':
      return (
        <div className={styles.formGroup}>
          <label className={requerido ? styles.required : ''}>{label || fieldKey}</label>
          <input
            type="number"
            className={styles.input}
            value={value ?? ''}
            onChange={(e) => handleChange(e.target.value ? parseInt(e.target.value, 10) : null)}
            placeholder={descripcion || ''}
            step="1"
          />
        </div>
      );
    case 'decimal':
      return (
        <div className={styles.formGroup}>
          <label className={requerido ? styles.required : ''}>{label || fieldKey}</label>
          <input
            type="number"
            className={styles.input}
            value={value ?? ''}
            onChange={(e) => handleChange(e.target.value ? parseFloat(e.target.value) : null)}
            placeholder={descripcion || ''}
            step="0.01"
          />
        </div>
      );
    case 'select':
      return (
        <div className={styles.formGroup}>
          <label className={requerido ? styles.required : ''}>{label || fieldKey}</label>
          <select
            className={styles.select}
            value={value || ''}
            onChange={(e) => handleChange(e.target.value)}
          >
            <option value="">Seleccionar...</option>
            {(opciones || []).map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>
      );
    case 'boolean':
      return (
        <div className={styles.checkboxGroup}>
          <input
            type="checkbox"
            id={`field_${fieldKey}`}
            checked={!!value}
            onChange={(e) => handleChange(e.target.checked)}
          />
          <label htmlFor={`field_${fieldKey}`}>{label || fieldKey}</label>
        </div>
      );
    default:
      return (
        <div className={styles.formGroup}>
          <label className={requerido ? styles.required : ''}>{label || fieldKey}</label>
          <input
            type="text"
            className={styles.input}
            value={value || ''}
            onChange={(e) => handleChange(e.target.value)}
            placeholder={descripcion || ''}
          />
        </div>
      );
  }
};

/**
 * Uploads a single attachment, returning a failure descriptor instead of
 * throwing so the caller can surface it inline and offer a retry — the
 * ticket already exists by the time this runs, so a failed upload must
 * never look like the whole operation failed.
 */
const uploadFile = async (ticketId, file) => {
  try {
    await ticketsAPI.subirAdjunto(ticketId, file);
    return null;
  } catch (err) {
    // `subir_adjunto` raises plain HTTPException(detail=...) — FastAPI
    // serializes that as {"detail": "..."}, not the {"error":{"message"}}
    // envelope other endpoints in this app use. Check both shapes.
    const message =
      err.response?.data?.detail ||
      err.response?.data?.error?.message ||
      `No se pudo subir "${file.name}"`;
    return { file, message };
  }
};

export default function TicketCreateModal({ isOpen, onClose, onCreated }) {
  const fileInputRef = useRef(null);

  // Options (advanced path only)
  const [sectores, setSectores] = useState([]);
  const [tiposTicket, setTiposTicket] = useState([]);
  const [loadingTipos, setLoadingTipos] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Form state — texto is the single required field; everything else is
  // optional and defaults to the Bandeja de entrada (Inbox) on the backend.
  const [texto, setTexto] = useState('');
  const [sectorId, setSectorId] = useState('');
  const [tipoTicketId, setTipoTicketId] = useState('');
  const [titulo, setTitulo] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [prioridad, setPrioridad] = useState('media');
  const [metadata, setMetadata] = useState({});
  const [droppedFields, setDroppedFields] = useState(null);
  const [files, setFiles] = useState([]);

  // UI state
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [createdTicket, setCreatedTicket] = useState(null);
  const [failedUploads, setFailedUploads] = useState([]);

  // Reset on open + load sectores. This modal is normally unmounted and
  // remounted fresh by the parent (`{createModalOpen && <TicketCreateModal
  // .../>}` in Tickets.jsx), which already gives clean state on every open —
  // this reset is defensive, protecting a future caller that instead keeps
  // the component alive and just toggles `isOpen`.
  useEffect(() => {
    if (!isOpen) return;
    setTexto('');
    setSectorId('');
    setTipoTicketId('');
    setTitulo('');
    setDescripcion('');
    setPrioridad('media');
    setMetadata({});
    setDroppedFields(null);
    setFiles([]);
    setShowAdvanced(false);
    setError(null);
    setCreatedTicket(null);
    setFailedUploads([]);

    const fetchSectores = async () => {
      try {
        const { data } = await sectoresAPI.listar();
        setSectores(Array.isArray(data) ? data : []);
      } catch {
        setSectores([]);
      }
    };
    fetchSectores();
  }, [isOpen]);

  // Fetch tipos_ticket whenever sector changes. Clearing tipoTicketId/
  // metadata for the new sector is handleSectorChange's job (imperative,
  // same drop-preserving logic as handleTipoChange) — this effect only
  // fetches.
  useEffect(() => {
    if (!sectorId) {
      setTiposTicket([]);
      return;
    }

    const fetchTipos = async () => {
      setLoadingTipos(true);
      try {
        const { data } = await sectoresAPI.listarTiposTicket(sectorId);
        setTiposTicket(Array.isArray(data) ? data : []);
      } catch {
        setTiposTicket([]);
      } finally {
        setLoadingTipos(false);
      }
    };
    fetchTipos();
  }, [sectorId]);

  const selectedTipo = tiposTicket.find((t) => String(t.id) === String(tipoTicketId));
  const schemaCampos = selectedTipo?.schema_campos || {};
  const hasDynamicFields = Object.keys(schemaCampos).length > 0;

  const handleMetadataChange = (key, value) => {
    setMetadata((prev) => ({ ...prev, [key]: value }));
  };

  // Keeps metadata keys present in `nuevoSchema`, drops the rest, and shows
  // an inline notice listing what was dropped — instead of a confirm()
  // modal (banned by AGENTS.md). Shared by both handleSectorChange and
  // handleTipoChange so metadata loss is never silent on EITHER path.
  const aplicarMetadataParaSchema = (nuevoSchema) => {
    const conservados = {};
    const perdidos = [];
    for (const [key, value] of Object.entries(metadata)) {
      if (key in nuevoSchema) {
        conservados[key] = value;
      } else {
        perdidos.push(schemaCampos[key]?.label || key);
      }
    }
    setDroppedFields(perdidos.length > 0 ? perdidos : null);
    setMetadata(conservados);
  };

  // Changing sector invalidates the current tipo entirely — treat it as a
  // drop against an empty schema so any metadata gets the same
  // preserve/notify treatment as a tipo change (previously this wiped
  // metadata unconditionally and silently, the exact bug this slice fixes).
  const handleSectorChange = (newSectorId) => {
    aplicarMetadataParaSchema({});
    setTipoTicketId('');
    setSectorId(newSectorId);
  };

  const handleTipoChange = (newTipoId) => {
    const nuevoTipo = tiposTicket.find((t) => String(t.id) === String(newTipoId));
    aplicarMetadataParaSchema(nuevoTipo?.schema_campos || {});
    setTipoTicketId(newTipoId);
  };

  const handleFileSelect = (e) => {
    const selected = Array.from(e.target.files || []);
    setFiles((prev) => [...prev, ...selected]);
    // Reset input so the same file can be re-selected
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleRemoveFile = (index) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleRetryUpload = async (failedFile) => {
    if (!createdTicket) return;
    const failure = await uploadFile(createdTicket.id, failedFile);
    setFailedUploads((prev) => {
      const resto = prev.filter((f) => f.file !== failedFile);
      return failure ? [...resto, failure] : resto;
    });
  };

  const validateForm = () => {
    if (!texto || texto.trim().length < 5) return 'El texto debe tener al menos 5 caracteres';
    if (sectorId && !tipoTicketId) return 'Selecciona un tipo de ticket';

    // Validate required dynamic fields
    for (const [key, def] of Object.entries(schemaCampos)) {
      if (def.requerido) {
        const val = metadata[key];
        if (val === undefined || val === null || val === '') {
          return `El campo "${def.label || key}" es requerido`;
        }
      }
    }
    return null;
  };

  const handleSubmit = async () => {
    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSaving(true);
    setError(null);

    try {
      // sector_id/tipo_ticket_id/titulo are only sent when the user picked
      // them explicitly — omitted, the backend defaults to the Bandeja de
      // entrada and derives titulo from texto.
      const payload = { texto: texto.trim(), prioridad, campos_metadata: metadata };
      if (sectorId) payload.sector_id = parseInt(sectorId, 10);
      if (tipoTicketId) payload.tipo_ticket_id = parseInt(tipoTicketId, 10);
      if (titulo.trim()) payload.titulo = titulo.trim();
      if (descripcion.trim()) payload.descripcion = descripcion.trim();

      const { data: ticket } = await ticketsAPI.crear(payload);
      setCreatedTicket(ticket);

      const fallas = [];
      for (const file of files) {
        const falla = await uploadFile(ticket.id, file);
        if (falla) fallas.push(falla);
      }
      setFailedUploads(fallas);

      if (fallas.length === 0) {
        onCreated?.(ticket);
      }
    } catch (err) {
      const msg = err.response?.data?.error?.message || err.response?.data?.detail || 'Error al crear el ticket';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setSaving(false);
    }
  };

  const handleFinish = () => {
    onCreated?.(createdTicket);
  };

  const footer = createdTicket ? (
    // The ticket already exists once we reach this state — both "Cerrar"
    // and "Listo" must notify the parent so its list refreshes, even if
    // the user closes without retrying a failed attachment upload.
    <ModalFooterButtons
      onCancel={handleFinish}
      onConfirm={handleFinish}
      confirmText="Listo"
      cancelText="Cerrar"
    />
  ) : (
    <ModalFooterButtons
      onCancel={onClose}
      onConfirm={handleSubmit}
      confirmText={saving ? 'Creando...' : 'Crear Ticket'}
      confirmLoading={saving}
      confirmDisabled={saving}
    />
  );

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title="Nuevo Ticket"
      size="lg"
      footer={footer}
    >
      <div className={styles.formGrid}>
        {error && <div className={styles.formError}>{error}</div>}

        {failedUploads.length > 0 && (
          <div className={styles.uploadErrors}>
            {failedUploads.map(({ file, message }, idx) => (
              // index, not file.name: two attachments can share a name
              // (e.g. "captura.png" from two different screenshots).
              <div key={idx} className={styles.uploadError}>
                <span>{message}</span>
                <button
                  type="button"
                  className={styles.btnRetry}
                  onClick={() => handleRetryUpload(file)}
                >
                  <RefreshCw size={12} />
                  Reintentar
                </button>
              </div>
            ))}
          </div>
        )}

        <div className={styles.formGroup}>
          <label className={styles.required}>Contanos qué necesitás</label>
          <textarea
            className={styles.textarea}
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            placeholder="Describí el problema o la solicitud (mínimo 5 caracteres)..."
            rows={5}
            disabled={!!createdTicket}
          />
        </div>

        <button
          type="button"
          className={styles.btnToggleAdvanced}
          onClick={() => setShowAdvanced((prev) => !prev)}
          disabled={!!createdTicket}
        >
          {showAdvanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          Opciones avanzadas
        </button>

        {showAdvanced && (
          <>
            <div className={styles.formRow}>
              <div className={styles.formGroup}>
                <label>Sector</label>
                <select
                  className={styles.select}
                  value={sectorId}
                  onChange={(e) => handleSectorChange(e.target.value)}
                >
                  <option value="">Bandeja de entrada (automático)</option>
                  {sectores.map((s) => (
                    <option key={s.id} value={s.id}>{s.nombre}</option>
                  ))}
                </select>
              </div>

              <div className={styles.formGroup}>
                <label>Tipo</label>
                {loadingTipos ? (
                  <span className={styles.loadingHint}>Cargando tipos...</span>
                ) : (
                  <select
                    className={styles.select}
                    value={tipoTicketId}
                    onChange={(e) => handleTipoChange(e.target.value)}
                    disabled={!sectorId}
                  >
                    <option value="">Seleccionar tipo...</option>
                    {tiposTicket.map((t) => (
                      <option key={t.id} value={t.id}>{t.nombre}</option>
                    ))}
                  </select>
                )}
              </div>
            </div>

            {droppedFields && (
              <div className={styles.notice}>
                Se perdieron estos campos al cambiar sector o tipo: {droppedFields.join(', ')}
              </div>
            )}

            <div className={styles.formGroup}>
              <label>Título (opcional)</label>
              <input
                type="text"
                className={styles.input}
                value={titulo}
                onChange={(e) => setTitulo(e.target.value)}
                placeholder="Si lo dejás vacío, se genera automáticamente"
                maxLength={255}
              />
            </div>

            <div className={styles.formGroup}>
              <label>Descripción</label>
              <textarea
                className={styles.textarea}
                value={descripcion}
                onChange={(e) => setDescripcion(e.target.value)}
                placeholder="Detalle adicional (opcional)..."
                rows={3}
              />
            </div>

            <div className={styles.formGroup}>
              <label>Prioridad</label>
              <select
                className={styles.select}
                value={prioridad}
                onChange={(e) => setPrioridad(e.target.value)}
              >
                {PRIORIDADES.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>

            {/* Dynamic fields from tipo_ticket.schema_campos */}
            {hasDynamicFields && (
              <div className={styles.dynamicFields}>
                <div className={styles.dynamicFieldsTitle}>Campos adicionales</div>
                {Object.entries(schemaCampos).map(([key, def]) => (
                  <DynamicField
                    key={key}
                    fieldKey={key}
                    fieldDef={def}
                    value={metadata[key]}
                    onChange={handleMetadataChange}
                  />
                ))}
              </div>
            )}
          </>
        )}

        {/* File upload */}
        <div className={styles.fileSection}>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            onChange={handleFileSelect}
            className={styles.fileInput}
          />
          <button
            type="button"
            className={styles.btnUpload}
            onClick={() => fileInputRef.current?.click()}
            disabled={!!createdTicket}
          >
            <ImagePlus size={14} />
            Adjuntar captura
          </button>

          {files.length > 0 && (
            <div className={styles.fileList}>
              {files.map((file, idx) => (
                <div key={idx} className={styles.fileItem}>
                  <span className={styles.fileName}>
                    <Paperclip size={12} />
                    {file.name}
                  </span>
                  <button
                    type="button"
                    className={styles.btnRemoveFile}
                    onClick={() => handleRemoveFile(idx)}
                    aria-label="Quitar archivo"
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </ModalTesla>
  );
}

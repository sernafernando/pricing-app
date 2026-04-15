/**
 * DocumentDesigner - Página completa con pdfme WYSIWYG Designer.
 * Lazy-loaded desde App.jsx para no afectar el bundle inicial.
 * Requiere permiso: documentos.disenar
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { documentTemplatesAPI } from '../services/api';
import { FileText, Save, Plus, Trash2, ChevronDown, Loader2, AlertCircle } from 'lucide-react';
import ModalTesla from '../components/ModalTesla';
import styles from './DocumentDesigner.module.css';

const BLANK_PDF =
  'data:application/pdf;base64,JVBERi0xLjcKCjEgMCBvYmoKPDwKL1R5cGUgL0NhdGFsb2cKL1BhZ2VzIDIgMCBSCj4+CmVuZG9iagoKMiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0tpZHMgWzMgMCBSXQovQ291bnQgMQo+PgplbmRvYmoKCjMgMCBvYmoKPDwKL1R5cGUgL1BhZ2UKL1BhcmVudCAyIDAgUgovTWVkaWFCb3ggWzAgMCA1OTUuMjggODQxLjg5XQo+PgplbmRvYmoKCnhyZWYKMCA0CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAwOSAwMDAwMCBuIAowMDAwMDAwMDU4IDAwMDAwIG4gCjAwMDAwMDAxMTUgMDAwMDAgbiAKCnRyYWlsZXIKPDwKL1NpemUgNAovUm9vdCAxIDAgUgo+PgpzdGFydHhyZWYKMjA2CiUlRU9GCg==';

export default function DocumentDesigner() {
  const designerRef = useRef(null);
  const containerRef = useRef(null);


  // Templates state
  const [templates, setTemplates] = useState([]);
  const [currentTemplate, setCurrentTemplate] = useState(null);
  const [contextos, setContextos] = useState([]);
  const [variables, setVariables] = useState([]);

  // Form state
  const [nombre, setNombre] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [contexto, setContexto] = useState('');

  // UI state
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Load contextos on mount
  useEffect(() => {
    const fetchContextos = async () => {
      try {
        const { data } = await documentTemplatesAPI.contextos();
        setContextos(data);
        if (data.length > 0) setContexto(data[0]);
      } catch {
        setError('Error al cargar contextos');
      }
    };
    fetchContextos();
  }, []);

  // Load templates when contexto changes
  useEffect(() => {
    if (!contexto) return;
    const fetchTemplates = async () => {
      setLoading(true);
      try {
        const { data } = await documentTemplatesAPI.listar({ contexto, activo: null });
        setTemplates(data);
      } catch {
        setError('Error al cargar templates');
      } finally {
        setLoading(false);
      }
    };
    fetchTemplates();
  }, [contexto]);

  // Load variables when contexto changes
  useEffect(() => {
    if (!contexto) return;
    const fetchVariables = async () => {
      try {
        const { data } = await documentTemplatesAPI.variables(contexto);
        setVariables(data.variables || []);
      } catch {
        setVariables([]);
      }
    };
    fetchVariables();
  }, [contexto]);

  // Track template ID separately to avoid re-initializing Designer on every
  // currentTemplate object reference change (e.g., after save refreshes the list).
  const currentTemplateId = currentTemplate?.id ?? null;
  const currentTemplateJson = currentTemplate?.template_json ?? null;

  // Designer initialization state
  const [designerLoading, setDesignerLoading] = useState(false);

  // Initialize/update pdfme Designer
  useEffect(() => {
    if (!containerRef.current || !contexto) return;

    let cancelled = false;

    const initDesigner = async () => {
      setDesignerLoading(true);
      setError(null);

      try {
        const [{ Designer }, { plugins }, { getFont }] = await Promise.all([
          import('@pdfme/ui'),
          import('../utils/pdfmePlugins'),
          import('../utils/pdfmeFonts'),
        ]);

        const font = await getFont();

        // Bail out if effect was cleaned up during async work
        if (cancelled || !containerRef.current) return;

        const template = currentTemplateJson || {
          basePdf: BLANK_PDF,
          schemas: [[]],
        };

        // Destroy previous instance
        if (designerRef.current) {
          designerRef.current.destroy();
          designerRef.current = null;
        }

        // Clear container
        containerRef.current.innerHTML = '';

        designerRef.current = new Designer({
          domContainer: containerRef.current,
          template,
          plugins,
          options: { font },
        });
      } catch (err) {
        if (!cancelled) {
          console.error('[DocumentDesigner] init failed:', err);
          setError(`Error al inicializar el Designer: ${err.message}`);
        }
      } finally {
        if (!cancelled) setDesignerLoading(false);
      }
    };

    initDesigner();

    return () => {
      cancelled = true;
      if (designerRef.current) {
        designerRef.current.destroy();
        designerRef.current = null;
      }
    };
  }, [contexto, currentTemplateId, currentTemplateJson]);

  // Save handler
  const handleSave = useCallback(async () => {
    if (!designerRef.current) return;
    if (!nombre.trim()) {
      setError('El nombre del template es obligatorio');
      return;
    }

    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const templateJson = designerRef.current.getTemplate();
      const payload = {
        nombre: nombre.trim(),
        descripcion: descripcion.trim() || null,
        contexto,
        template_json: templateJson,
      };

      let result;
      if (currentTemplate) {
        const { data } = await documentTemplatesAPI.actualizar(currentTemplate.id, payload);
        result = data;
      } else {
        const { data } = await documentTemplatesAPI.crear(payload);
        result = data;
      }

      setCurrentTemplate(result);
      setSuccess(currentTemplate ? 'Template actualizado' : 'Template creado');

      // Refresh list
      const { data: updated } = await documentTemplatesAPI.listar({ contexto, activo: null });
      setTemplates(updated);

      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Error al guardar');
    } finally {
      setSaving(false);
    }
  }, [nombre, descripcion, contexto, currentTemplate]);

  // Ctrl+S handler
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        handleSave();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleSave]);

  // Load existing template
  const handleLoadTemplate = useCallback(async (tmpl) => {
    setLoading(true);
    try {
      const { data } = await documentTemplatesAPI.obtener(tmpl.id);
      setCurrentTemplate(data);
      setNombre(data.nombre);
      setDescripcion(data.descripcion || '');
      setError(null);
    } catch {
      setError('Error al cargar template');
    } finally {
      setLoading(false);
    }
  }, []);

  // New template
  const handleNew = useCallback(() => {
    setCurrentTemplate(null);
    setNombre('');
    setDescripcion('');
    setError(null);
    setSuccess(null);
  }, []);

  // Delete template
  const handleDelete = useCallback(async () => {
    if (!currentTemplate) return;
    try {
      await documentTemplatesAPI.eliminar(currentTemplate.id);
      setShowDeleteConfirm(false);
      handleNew();
      // Refresh list
      const { data: updated } = await documentTemplatesAPI.listar({ contexto, activo: null });
      setTemplates(updated);
      setSuccess('Template eliminado');
      setTimeout(() => setSuccess(null), 3000);
    } catch {
      setError('Error al eliminar template');
    }
  }, [currentTemplate, contexto, handleNew]);

  // Copy variable name to clipboard
  const handleCopyVariable = useCallback((varName) => {
    navigator.clipboard.writeText(`{${varName}}`).then(() => {
      setSuccess(`Variable {${varName}} copiada`);
      setTimeout(() => setSuccess(null), 2000);
    });
  }, []);

  return (
    <div className={styles.container}>
      {/* Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <FileText size={20} />
          <h1 className={styles.title}>Document Designer</h1>
        </div>

        <div className={styles.toolbarCenter}>
          {/* Context selector */}
          <div className={styles.fieldGroup}>
            <label className={styles.label}>Contexto</label>
            <div className={styles.selectWrapper}>
              <select
                className={styles.select}
                value={contexto}
                onChange={(e) => {
                  setContexto(e.target.value);
                  handleNew();
                }}
              >
                {contextos.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <ChevronDown size={14} className={styles.selectIcon} />
            </div>
          </div>

          {/* Template name */}
          <div className={styles.fieldGroup}>
            <label className={styles.label}>Nombre</label>
            <input
              className={styles.input}
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              placeholder="Nombre del template..."
            />
          </div>

          {/* Description */}
          <div className={styles.fieldGroup}>
            <label className={styles.label}>Descripción</label>
            <input
              className={styles.input}
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              placeholder="Descripción opcional..."
            />
          </div>
        </div>

        <div className={styles.toolbarRight}>
          <button
            className="btn-tesla outline-subtle-primary sm"
            onClick={handleNew}
            title="Nuevo template"
          >
            <Plus size={16} />
            Nuevo
          </button>
          <button
            className="btn-tesla outline-subtle-success sm"
            onClick={handleSave}
            disabled={saving}
            title="Guardar (Ctrl+S)"
          >
            {saving ? <Loader2 size={16} className={styles.spin} /> : <Save size={16} />}
            {saving ? 'Guardando...' : 'Guardar'}
          </button>
          {currentTemplate && (
            <button
              className="btn-tesla outline-subtle-danger sm icon-only"
              onClick={() => setShowDeleteConfirm(true)}
              title="Eliminar template"
              aria-label="Eliminar template"
            >
              <Trash2 size={16} />
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      {error && (
        <div className={styles.errorBanner}>
          <AlertCircle size={16} />
          {error}
          <button onClick={() => setError(null)} className={styles.dismissBtn}>x</button>
        </div>
      )}
      {success && (
        <div className={styles.successBanner}>
          {success}
        </div>
      )}

      {/* Main area */}
      <div className={styles.mainArea}>
        {/* Sidebar: templates + variables */}
        <div className={styles.sidebar}>
          {/* Template list */}
          <div className={styles.sidebarSection}>
            <h3 className={styles.sidebarTitle}>Templates ({templates.length})</h3>
            {loading ? (
              <div className={styles.sidebarLoader}><Loader2 size={16} className={styles.spin} /> Cargando...</div>
            ) : templates.length === 0 ? (
              <p className={styles.sidebarEmpty}>No hay templates para este contexto</p>
            ) : (
              <ul className={styles.templateList}>
                {templates.map((t) => (
                  <li key={t.id}>
                    <button
                      type="button"
                      className={`${styles.templateItem} ${currentTemplate?.id === t.id ? styles.templateItemActive : ''} ${!t.activo ? styles.templateItemInactive : ''}`}
                      onClick={() => handleLoadTemplate(t)}
                    >
                      <span className={styles.templateName}>{t.nombre}</span>
                      {!t.activo && <span className={styles.inactiveBadge}>inactivo</span>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Variables palette */}
          <div className={styles.sidebarSection}>
            <h3 className={styles.sidebarTitle}>Variables disponibles</h3>
            <p className={styles.sidebarHint}>Click para copiar. Usar como nombre de campo en el Designer.</p>
            <ul className={styles.variableList}>
              {variables.map((v) => (
                <li key={v.nombre}>
                  <button
                    type="button"
                    className={styles.variableItem}
                    onClick={() => handleCopyVariable(v.nombre)}
                    title={`${v.descripcion} (${v.tipo}) — Ejemplo: ${v.ejemplo || 'N/A'}`}
                  >
                    <code className={styles.variableCode}>{v.nombre}</code>
                    <span className={styles.variableDesc}>{v.descripcion}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Designer canvas */}
        <div className={styles.designerContainer} ref={containerRef}>
          {designerLoading && (
            <div className={styles.designerLoader}>
              <Loader2 size={24} className={styles.spin} />
              <span>Cargando Designer...</span>
            </div>
          )}
        </div>
      </div>

      {/* Delete confirmation modal */}
      <ModalTesla
        isOpen={showDeleteConfirm}
        onClose={() => setShowDeleteConfirm(false)}
        title="Eliminar template"
        size="sm"
        footer={
          <div className={styles.modalFooter}>
            <button className="btn-tesla secondary sm" onClick={() => setShowDeleteConfirm(false)}>
              Cancelar
            </button>
            <button className="btn-tesla outline-subtle-danger sm" onClick={handleDelete}>
              Eliminar
            </button>
          </div>
        }
      >
        <p>¿Estás seguro de eliminar el template &quot;{currentTemplate?.nombre}&quot;?</p>
        <p className={styles.deleteNote}>El template se desactivará (soft-delete), no se pierde data.</p>
      </ModalTesla>
    </div>
  );
}

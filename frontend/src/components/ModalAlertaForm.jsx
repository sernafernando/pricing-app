import { useState, useEffect } from 'react';
import api from '../services/api';
import styles from './ModalAlertaForm.module.css';
import AlertBanner from './AlertBanner';

export default function ModalAlertaForm({ alerta, onClose }) {
  const isEdit = !!alerta;

  // Form state
  const [formData, setFormData] = useState({
    titulo: '',
    mensaje: '',
    variant: 'info',
    action_label: '',
    action_url: '',
    dismissible: true,
    persistent: false,
    roles_destinatarios: [],
    usuarios_destinatarios_ids: [],
    activo: false,
    fecha_desde: new Date().toISOString().slice(0, 16),
    fecha_hasta: '',
    prioridad: 0,
    duracion_segundos: 5
  });

  const [roles, setRoles] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    cargarRoles();
    cargarUsuarios();

    if (isEdit) {
      setFormData({
        titulo: alerta.titulo || '',
        mensaje: alerta.mensaje || '',
        variant: alerta.variant || 'info',
        action_label: alerta.action_label || '',
        action_url: alerta.action_url || '',
        dismissible: alerta.dismissible !== undefined ? alerta.dismissible : true,
        persistent: alerta.persistent !== undefined ? alerta.persistent : false,
        roles_destinatarios: alerta.roles_destinatarios || [],
        usuarios_destinatarios_ids: alerta.usuarios_destinatarios?.map(u => u.id) || [],
        activo: alerta.activo !== undefined ? alerta.activo : false,
        fecha_desde: alerta.fecha_desde ? new Date(alerta.fecha_desde).toISOString().slice(0, 16) : new Date().toISOString().slice(0, 16),
        fecha_hasta: alerta.fecha_hasta ? new Date(alerta.fecha_hasta).toISOString().slice(0, 16) : '',
        prioridad: alerta.prioridad ?? 0,
        duracion_segundos: alerta.duracion_segundos ?? 5
      });
    }
  }, [alerta, isEdit]);

  // Cerrar modal con ESC
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape') {
        onClose(false);
      }
    };

    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [onClose]);

  const cargarRoles = async () => {
    try {
      const response = await api.get('/roles');
      setRoles(response.data);
    } catch (error) {
      console.error('Error al cargar roles:', error);
    }
  };

  const cargarUsuarios = async () => {
    try {
      const response = await api.get('/usuarios');
      setUsuarios(response.data);
    } catch (error) {
      console.error('Error al cargar usuarios:', error);
    }
  };

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  const handleRolesChange = (e) => {
    const options = Array.from(e.target.selectedOptions);
    const values = options.map(opt => opt.value);
    setFormData(prev => ({
      ...prev,
      roles_destinatarios: values
    }));
  };

  const handleUsuariosChange = (e) => {
    const options = Array.from(e.target.selectedOptions);
    const values = options.map(opt => parseInt(opt.value));
    setFormData(prev => ({
      ...prev,
      usuarios_destinatarios_ids: values
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!formData.titulo || !formData.mensaje) {
      alert('Título y mensaje son obligatorios');
      return;
    }

    if (formData.roles_destinatarios.length === 0 && formData.usuarios_destinatarios_ids.length === 0) {
      alert('Debe seleccionar al menos un rol o usuario destinatario');
      return;
    }

    try {
      setLoading(true);

      // Convertir fechas desde datetime-local (sin timezone) a ISO con UTC
      // El input datetime-local NO incluye timezone, entonces interpretamos como UTC directamente
      const payload = {
        ...formData,
        fecha_desde: formData.fecha_desde ? formData.fecha_desde + ':00.000Z' : new Date().toISOString(),
        fecha_hasta: formData.fecha_hasta ? formData.fecha_hasta + ':00.000Z' : null
      };

      if (isEdit) {
        await api.put(`/alertas/${alerta.id}`, payload);
        alert('✅ Alerta actualizada');
      } else {
        await api.post('/alertas', payload);
        alert('✅ Alerta creada');
      }

      onClose(true); // true = actualizado
    } catch (error) {
      console.error('Error al guardar alerta:', error);
      alert('Error al guardar alerta: ' + (error.response?.data?.detail || error.message));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay-tesla">
      <div className="modal-tesla lg">
        <div className="modal-header-tesla">
          <h2 className="modal-title-tesla">{isEdit ? 'Editar Alerta' : 'Nueva Alerta'}</h2>
          <button className="btn-close-tesla" onClick={() => onClose(false)}>✕</button>
        </div>

        <form onSubmit={handleSubmit} className="modal-body-tesla">
          {/* Título */}
          <div className={styles.formGroup}>
            <label htmlFor="titulo">Título *</label>
            <input
              type="text"
              id="titulo"
              name="titulo"
              value={formData.titulo}
              onChange={handleChange}
              maxLength={200}
              required
              className={styles.input}
            />
          </div>

          {/* Mensaje */}
          <div className={styles.formGroup}>
            <label htmlFor="mensaje">Mensaje *</label>
            <textarea
              id="mensaje"
              name="mensaje"
              value={formData.mensaje}
              onChange={handleChange}
              rows={3}
              required
              className={styles.textarea}
            />
          </div>

          {/* Variant */}
          <div className={styles.formGroup}>
            <label htmlFor="variant">Tipo de Alerta</label>
            <select
              id="variant"
              name="variant"
              value={formData.variant}
              onChange={handleChange}
              className={styles.select}
            >
              <option value="info">Info (Azul)</option>
              <option value="warning">Warning (Naranja)</option>
              <option value="success">Success (Verde)</option>
              <option value="error">Error (Rojo)</option>
            </select>
          </div>

          {/* Acción (botón opcional) */}
          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label htmlFor="action_label">Texto del Botón (opcional)</label>
              <input
                type="text"
                id="action_label"
                name="action_label"
                value={formData.action_label}
                onChange={handleChange}
                maxLength={100}
                className={styles.input}
                placeholder="Ver ahora"
              />
            </div>
            <div className={styles.formGroup}>
              <label htmlFor="action_url">URL del Botón (opcional)</label>
              <input
                type="text"
                id="action_url"
                name="action_url"
                value={formData.action_url}
                onChange={handleChange}
                maxLength={500}
                className={styles.input}
                placeholder="/dashboard"
              />
            </div>
          </div>

          {/* Checkboxes */}
          <div className={styles.checkboxGroup}>
            <label>
              <input
                type="checkbox"
                name="dismissible"
                checked={formData.dismissible}
                onChange={handleChange}
              />
              <span>Se puede cerrar</span>
            </label>
            <label>
              <input
                type="checkbox"
                name="persistent"
                checked={formData.persistent}
                onChange={handleChange}
              />
              <span>Persistente (aparece siempre)</span>
            </label>
            <label>
              <input
                type="checkbox"
                name="activo"
                checked={formData.activo}
                onChange={handleChange}
              />
              <span>Activo (publicar ahora)</span>
            </label>
          </div>

          {/* Destinatarios - Roles */}
          <div className={styles.formGroup}>
            <label htmlFor="roles">Roles Destinatarios *</label>
            <select
              id="roles"
              name="roles"
              multiple
              value={formData.roles_destinatarios}
              onChange={handleRolesChange}
              className={styles.selectMultiple}
              size={5}
            >
              <option value="*">* Todos los usuarios</option>
              {roles.map(rol => (
                <option key={rol.id} value={rol.codigo}>
                  {rol.nombre} ({rol.codigo})
                </option>
              ))}
            </select>
            <small className={styles.hint}>Mantén Ctrl/Cmd para seleccionar múltiples</small>
          </div>

          {/* Destinatarios - Usuarios específicos */}
          <div className={styles.formGroup}>
            <label htmlFor="usuarios">Usuarios Específicos (opcional)</label>
            <select
              id="usuarios"
              name="usuarios"
              multiple
              value={formData.usuarios_destinatarios_ids}
              onChange={handleUsuariosChange}
              className={styles.selectMultiple}
              size={5}
            >
              {usuarios.map(usuario => (
                <option key={usuario.id} value={usuario.id}>
                  {usuario.nombre} - {usuario.email || usuario.username}
                </option>
              ))}
            </select>
            <small className={styles.hint}>Además de los roles, enviar a usuarios específicos</small>
          </div>

          {/* Vigencia */}
          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label htmlFor="fecha_desde">Fecha Desde *</label>
              <input
                type="datetime-local"
                id="fecha_desde"
                name="fecha_desde"
                value={formData.fecha_desde}
                onChange={handleChange}
                required
                className={styles.input}
              />
            </div>
            <div className={styles.formGroup}>
              <label htmlFor="fecha_hasta">Fecha Hasta (opcional)</label>
              <input
                type="datetime-local"
                id="fecha_hasta"
                name="fecha_hasta"
                value={formData.fecha_hasta}
                onChange={handleChange}
                className={styles.input}
              />
              <small className={styles.hint}>Dejar vacío para indefinido</small>
            </div>
          </div>

          {/* Prioridad y Duración */}
          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label htmlFor="prioridad">Prioridad (mayor = más arriba)</label>
              <input
                type="number"
                id="prioridad"
                name="prioridad"
                value={formData.prioridad}
                onChange={handleChange}
                className={styles.input}
                min={0}
                max={100}
              />
            </div>

            <div className={styles.formGroup}>
              <label htmlFor="duracion_segundos">Duración de Rotación</label>
              <select
                id="duracion_segundos"
                name="duracion_segundos"
                value={formData.duracion_segundos}
                onChange={handleChange}
                className={styles.select}
              >
                <option value={0}>Sticky (no rota)</option>
                <option value={3}>3 segundos</option>
                <option value={5}>5 segundos (default)</option>
                <option value={10}>10 segundos</option>
                <option value={15}>15 segundos</option>
                <option value={30}>30 segundos</option>
                <option value={60}>60 segundos</option>
              </select>
              <small className={styles.hint}>0 = siempre visible (sticky)</small>
            </div>
          </div>

          {/* Preview */}
          <div className={styles.previewSection}>
            <button
              type="button"
              className="btn-tesla secondary sm"
              onClick={() => setShowPreview(!showPreview)}
            >
              {showPreview ? '🙈 Ocultar Preview' : '👁️ Ver Preview'}
            </button>

            {showPreview && (
              <div className={styles.previewContainer}>
                <h4>Preview:</h4>
                <AlertBanner
                  id="preview"
                  variant={formData.variant}
                  message={formData.mensaje}
                  action={formData.action_label && formData.action_url ? {
                    label: formData.action_label,
                    onClick: () => alert('Preview: redirigiría a ' + formData.action_url)
                  } : null}
                  dismissible={formData.dismissible}
                  persistent={false} // En preview nunca es persistent
                />
              </div>
            )}
          </div>

          {/* Botones */}
          <div className="modal-footer-tesla">
            <button
              type="button"
              className="btn-tesla secondary"
              onClick={() => onClose(false)}
              disabled={loading}
            >
              Cancelar
            </button>
            <button
              type="submit"
              className="btn-tesla outline-subtle-primary"
              disabled={loading}
            >
              {loading ? 'Guardando...' : (isEdit ? 'Actualizar' : 'Crear')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

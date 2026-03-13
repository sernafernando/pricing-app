import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI } from '../services/api';
import { Shield, Plus, RotateCcw, Ban, Eye } from 'lucide-react';
import styles from './RRHHSanciones.module.css';

const INITIAL_FORM = {
  empleado_id: '',
  tipo_sancion_id: '',
  fecha: new Date().toISOString().slice(0, 10),
  motivo: '',
  descripcion: '',
  fecha_desde: '',
  fecha_hasta: '',
};

const formatDate = (dateStr) => {
  if (!dateStr) return '-';
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
};

export default function RRHHSanciones() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rrhh.gestionar');

  // ── List state ──
  const [sanciones, setSanciones] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;

  // ── Filter state ──
  const [filtroEmpleado, setFiltroEmpleado] = useState('');
  const [filtroTipo, setFiltroTipo] = useState('');
  const [filtroDesde, setFiltroDesde] = useState('');
  const [filtroHasta, setFiltroHasta] = useState('');
  const [mostrarAnuladas, setMostrarAnuladas] = useState(false);

  // ── Tipos sancion (for select) ──
  const [tiposSancion, setTiposSancion] = useState([]);

  // ── Create modal ──
  const [crearModalOpen, setCrearModalOpen] = useState(false);
  const [crearForm, setCrearForm] = useState(INITIAL_FORM);
  const [crearSaving, setCrearSaving] = useState(false);
  const [crearError, setCrearError] = useState(null);

  // ── Anular modal ──
  const [anularTarget, setAnularTarget] = useState(null);
  const [anularMotivo, setAnularMotivo] = useState('');
  const [anularSaving, setAnularSaving] = useState(false);
  const [anularError, setAnularError] = useState(null);

  // ── Detail view ──
  const [detalleOpen, setDetalleOpen] = useState(null);

  // ── Load tipos sancion on mount ──
  useEffect(() => {
    const fetchTipos = async () => {
      try {
        const { data } = await rrhhAPI.listarTiposSancion();
        setTiposSancion(Array.isArray(data) ? data : data.items || []);
      } catch {
        setTiposSancion([]);
      }
    };
    fetchTipos();
  }, []);

  // ── Fetch sanciones ──
  const cargarSanciones = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: PAGE_SIZE };
      if (filtroEmpleado) params.empleado_id = Number(filtroEmpleado);
      if (filtroTipo) params.tipo_sancion_id = Number(filtroTipo);
      if (filtroDesde) params.fecha_desde = filtroDesde;
      if (filtroHasta) params.fecha_hasta = filtroHasta;
      if (!mostrarAnuladas) params.incluir_anuladas = false;

      const { data } = await rrhhAPI.listarSanciones(params);
      setSanciones(data.items || []);
      setTotal(data.total || 0);
    } catch {
      setSanciones([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, filtroEmpleado, filtroTipo, filtroDesde, filtroHasta, mostrarAnuladas]);

  useEffect(() => {
    cargarSanciones();
  }, [cargarSanciones]);

  // ── Create sancion ──
  const handleCrear = async () => {
    if (!crearForm.empleado_id || !crearForm.tipo_sancion_id) {
      setCrearError('Empleado y tipo de sanción son obligatorios');
      return;
    }
    if (!crearForm.motivo.trim()) {
      setCrearError('El motivo es obligatorio');
      return;
    }
    setCrearSaving(true);
    setCrearError(null);
    try {
      const payload = {
        empleado_id: Number(crearForm.empleado_id),
        tipo_sancion_id: Number(crearForm.tipo_sancion_id),
        fecha: crearForm.fecha,
        motivo: crearForm.motivo.trim(),
      };
      if (crearForm.descripcion.trim()) {
        payload.descripcion = crearForm.descripcion.trim();
      }
      if (crearForm.fecha_desde) payload.fecha_desde = crearForm.fecha_desde;
      if (crearForm.fecha_hasta) payload.fecha_hasta = crearForm.fecha_hasta;

      await rrhhAPI.crearSancion(payload);
      setCrearModalOpen(false);
      setCrearForm(INITIAL_FORM);
      cargarSanciones();
    } catch (err) {
      setCrearError(err.response?.data?.detail || 'Error al crear la sancion');
    } finally {
      setCrearSaving(false);
    }
  };

  // ── Anular sancion ──
  const handleAnular = async () => {
    if (!anularMotivo.trim()) {
      setAnularError('El motivo de anulacion es obligatorio');
      return;
    }
    setAnularSaving(true);
    setAnularError(null);
    try {
      await rrhhAPI.anularSancion(anularTarget.id, { motivo: anularMotivo.trim() });
      setAnularTarget(null);
      setAnularMotivo('');
      cargarSanciones();
    } catch (err) {
      setAnularError(err.response?.data?.detail || 'Error al anular la sancion');
    } finally {
      setAnularSaving(false);
    }
  };

  // ── Open create modal ──
  const openCrear = () => {
    setCrearForm({ ...INITIAL_FORM, fecha: new Date().toISOString().slice(0, 10) });
    setCrearError(null);
    setCrearModalOpen(true);
  };

  // ── Open anular modal ──
  const openAnular = (sancion) => {
    setAnularTarget(sancion);
    setAnularMotivo('');
    setAnularError(null);
  };

  // ── Helpers ──
  const getTipoNombre = (tipoId) => {
    const tipo = tiposSancion.find((t) => t.id === tipoId);
    return tipo ? tipo.nombre : `#${tipoId}`;
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Shield size={24} />
          <h1>Sanciones</h1>
          {total > 0 && <span className={styles.badge}>{total}</span>}
        </div>
        {puedeGestionar && (
          <button className={styles.btnCreate} onClick={openCrear}>
            <Plus size={16} /> Nueva sancion
          </button>
        )}
      </div>

      {/* Filters */}
      <div className={styles.filters}>
        <input
          type="number"
          className={styles.input}
          placeholder="ID Empleado"
          value={filtroEmpleado}
          onChange={(e) => { setFiltroEmpleado(e.target.value); setPage(1); }}
          min="1"
        />
        <select
          className={styles.select}
          value={filtroTipo}
          onChange={(e) => { setFiltroTipo(e.target.value); setPage(1); }}
        >
          <option value="">Todos los tipos</option>
          {tiposSancion.map((t) => (
            <option key={t.id} value={t.id}>{t.nombre}</option>
          ))}
        </select>
        <input
          type="date"
          className={styles.input}
          value={filtroDesde}
          onChange={(e) => { setFiltroDesde(e.target.value); setPage(1); }}
          title="Fecha desde"
        />
        <input
          type="date"
          className={styles.input}
          value={filtroHasta}
          onChange={(e) => { setFiltroHasta(e.target.value); setPage(1); }}
          title="Fecha hasta"
        />
        <label className={styles.checkboxLabel}>
          <input
            type="checkbox"
            checked={mostrarAnuladas}
            onChange={(e) => { setMostrarAnuladas(e.target.checked); setPage(1); }}
          />
          Mostrar anuladas
        </label>
        <button className={styles.btnRefresh} onClick={() => { setPage(1); cargarSanciones(); }} title="Recargar">
          <RotateCcw size={14} />
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <div className={styles.loading}>Cargando sanciones...</div>
      ) : sanciones.length === 0 ? (
        <div className={styles.empty}>No se encontraron sanciones</div>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Empleado</th>
              <th>Tipo sancion</th>
              <th>Motivo</th>
              <th>Suspension</th>
              <th>Estado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {sanciones.map((s) => (
              <tr key={s.id}>
                <td>{formatDate(s.fecha)}</td>
                <td>{s.empleado_nombre || `#${s.empleado_id}`}</td>
                <td>{getTipoNombre(s.tipo_sancion_id)}</td>
                <td>{s.motivo}</td>
                <td>
                  {s.fecha_desde
                    ? `${formatDate(s.fecha_desde)} - ${formatDate(s.fecha_hasta)}`
                    : '-'}
                </td>
                <td>
                  {s.anulada ? (
                    <span className={styles.statusAnulada}>Anulada</span>
                  ) : (
                    <span className={styles.statusActiva}>Activa</span>
                  )}
                </td>
                <td>
                  <div className={styles.actions}>
                    <button
                      className={styles.btnView}
                      onClick={() => setDetalleOpen(s)}
                      title="Ver detalle"
                    >
                      <Eye size={14} />
                    </button>
                    {puedeGestionar && !s.anulada && (
                      <button
                        className={styles.btnAnular}
                        onClick={() => openAnular(s)}
                        title="Anular sancion"
                      >
                        <Ban size={14} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className={styles.filters} style={{ marginTop: 'var(--spacing-md)', justifyContent: 'center' }}>
          <button
            className={styles.btnCancel}
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            Anterior
          </button>
          <span style={{ fontSize: 'var(--font-sm)', color: 'var(--cf-text-secondary)' }}>
            Pagina {page} de {totalPages}
          </span>
          <button
            className={styles.btnCancel}
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Siguiente
          </button>
        </div>
      )}

      {/* Create modal */}
      {crearModalOpen && (
        <div className="modal-overlay-tesla" onClick={() => setCrearModalOpen(false)}>
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Nueva sancion</h2>
              <button className="btn-close-tesla" onClick={() => setCrearModalOpen(false)} aria-label="Cerrar modal">✕</button>
            </div>
            <div className="modal-body-tesla">
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Empleado ID</label>
                  <input
                    type="number"
                    className={styles.input}
                    value={crearForm.empleado_id}
                    onChange={(e) => setCrearForm({ ...crearForm, empleado_id: e.target.value })}
                    min="1"
                    required
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Tipo de sancion</label>
                  <select
                    className={styles.select}
                    value={crearForm.tipo_sancion_id}
                    onChange={(e) => setCrearForm({ ...crearForm, tipo_sancion_id: e.target.value })}
                    required
                  >
                    <option value="">Seleccionar...</option>
                    {tiposSancion.map((t) => (
                      <option key={t.id} value={t.id}>{t.nombre}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className={styles.formGroup}>
                <label>Fecha</label>
                <input
                  type="date"
                  className={styles.input}
                  value={crearForm.fecha}
                  onChange={(e) => setCrearForm({ ...crearForm, fecha: e.target.value })}
                  required
                />
              </div>
              <div className={styles.formGroup}>
                <label>Motivo (obligatorio)</label>
                <textarea
                  className={styles.textarea}
                  value={crearForm.motivo}
                  onChange={(e) => setCrearForm({ ...crearForm, motivo: e.target.value })}
                  required
                />
              </div>
              <div className={styles.formGroup}>
                <label>Descripcion adicional</label>
                <textarea
                  className={styles.textarea}
                  value={crearForm.descripcion}
                  onChange={(e) => setCrearForm({ ...crearForm, descripcion: e.target.value })}
                />
              </div>
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Suspension desde</label>
                  <input
                    type="date"
                    className={styles.input}
                    value={crearForm.fecha_desde}
                    onChange={(e) => setCrearForm({ ...crearForm, fecha_desde: e.target.value })}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Suspension hasta</label>
                  <input
                    type="date"
                    className={styles.input}
                    value={crearForm.fecha_hasta}
                    onChange={(e) => setCrearForm({ ...crearForm, fecha_hasta: e.target.value })}
                  />
                </div>
              </div>
              {crearError && <div className={styles.formError}>{crearError}</div>}
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setCrearModalOpen(false)}>
                Cancelar
              </button>
              <button className={styles.btnSave} onClick={handleCrear} disabled={crearSaving}>
                {crearSaving ? 'Guardando...' : 'Crear sancion'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Anular modal */}
      {anularTarget && (
        <div className="modal-overlay-tesla" onClick={() => setAnularTarget(null)}>
          <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Anular sancion</h2>
              <button className="btn-close-tesla" onClick={() => setAnularTarget(null)} aria-label="Cerrar modal">✕</button>
            </div>
            <div className="modal-body-tesla">
              <p style={{ color: 'var(--cf-text-secondary)', fontSize: 'var(--font-sm)', marginBottom: 'var(--spacing-md)' }}>
                Se anulara la sancion del empleado {anularTarget.empleado_nombre || `#${anularTarget.empleado_id}`}.
                Esta accion no se puede deshacer.
              </p>
              <div className={styles.formGroup}>
                <label>Motivo de anulacion (obligatorio)</label>
                <textarea
                  className={styles.textarea}
                  value={anularMotivo}
                  onChange={(e) => setAnularMotivo(e.target.value)}
                  required
                />
              </div>
              {anularError && <div style={{ color: 'var(--cf-accent-red)', fontSize: 'var(--font-xs)' }}>{anularError}</div>}
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setAnularTarget(null)}>
                Cancelar
              </button>
              <button className={styles.btnAnular} onClick={handleAnular} disabled={anularSaving}>
                {anularSaving ? 'Anulando...' : 'Confirmar anulacion'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Detail modal */}
      {detalleOpen && (
        <div className="modal-overlay-tesla" onClick={() => setDetalleOpen(null)}>
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Detalle de sancion</h2>
              <button className="btn-close-tesla" onClick={() => setDetalleOpen(null)} aria-label="Cerrar modal">✕</button>
            </div>
            <div className="modal-body-tesla">
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Empleado</label>
                  <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                    {detalleOpen.empleado_nombre || `#${detalleOpen.empleado_id}`}
                  </div>
                </div>
                <div className={styles.formGroup}>
                  <label>Tipo</label>
                  <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                    {getTipoNombre(detalleOpen.tipo_sancion_id)}
                  </div>
                </div>
              </div>
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Fecha</label>
                  <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                    {formatDate(detalleOpen.fecha)}
                  </div>
                </div>
                <div className={styles.formGroup}>
                  <label>Estado</label>
                  <div>
                    {detalleOpen.anulada ? (
                      <span className={styles.statusAnulada}>Anulada</span>
                    ) : (
                      <span className={styles.statusActiva}>Activa</span>
                    )}
                  </div>
                </div>
              </div>
              <div className={styles.formGroup}>
                <label>Motivo</label>
                <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                  {detalleOpen.motivo}
                </div>
              </div>
              {detalleOpen.descripcion && (
                <div className={styles.formGroup}>
                  <label>Descripcion</label>
                  <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                    {detalleOpen.descripcion}
                  </div>
                </div>
              )}
              {detalleOpen.fecha_desde && (
                <div className={styles.formRow}>
                  <div className={styles.formGroup}>
                    <label>Suspension desde</label>
                    <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                      {formatDate(detalleOpen.fecha_desde)}
                    </div>
                  </div>
                  <div className={styles.formGroup}>
                    <label>Suspension hasta</label>
                    <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                      {formatDate(detalleOpen.fecha_hasta)}
                    </div>
                  </div>
                </div>
              )}
              {detalleOpen.anulada && detalleOpen.anulada_motivo && (
                <div className={styles.formGroup}>
                  <label>Motivo de anulacion</label>
                  <div style={{ color: 'var(--cf-accent-red)', fontSize: 'var(--font-sm)' }}>
                    {detalleOpen.anulada_motivo}
                  </div>
                </div>
              )}
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setDetalleOpen(null)}>
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

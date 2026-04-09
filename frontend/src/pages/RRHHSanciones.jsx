import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI } from '../services/api';
import { Shield, Plus, RotateCcw, Ban, Eye, FileDown, X, Settings } from 'lucide-react';
import DocumentGeneratorModal from '../components/DocumentGeneratorModal';
import SancionesConfigModal from '../components/SancionesConfigModal';
import CrearSancionModal from '../components/CrearSancionModal';
import usePlaceholders from '../hooks/usePlaceholders';
import useSancionesConfig from '../hooks/useSancionesConfig';
import styles from './RRHHSanciones.module.css';

const PAGE_SIZE = 50;

const formatDate = (dateStr) => {
  if (!dateStr) return '-';
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
};

export default function RRHHSanciones() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rrhh.gestionar');
  const puedeConfig = tienePermiso('rrhh.config');

  // ── List state ──
  const [sanciones, setSanciones] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [loadError, setLoadError] = useState(null);

  // ── Filter state ──
  const [filtroEmpleado, setFiltroEmpleado] = useState('');
  const [filtroTipo, setFiltroTipo] = useState('');
  const [filtroDesde, setFiltroDesde] = useState('');
  const [filtroHasta, setFiltroHasta] = useState('');
  const [mostrarAnuladas, setMostrarAnuladas] = useState(false);

  // ── Modal state ──
  const [crearModalOpen, setCrearModalOpen] = useState(false);
  const [anularTarget, setAnularTarget] = useState(null);
  const [anularMotivo, setAnularMotivo] = useState('');
  const [anularSaving, setAnularSaving] = useState(false);
  const [anularError, setAnularError] = useState(null);
  const [detalleOpen, setDetalleOpen] = useState(null);
  const [pdfTarget, setPdfTarget] = useState(null);

  // ── Empleados for selector ──
  const [empleados, setEmpleados] = useState([]);

  // ── Hooks ──
  const config = useSancionesConfig();
  const placeholders = usePlaceholders({ empleados, tiposSancion: config.tiposSancion });

  // ── Load empleados on mount ──
  useEffect(() => {
    const fetchEmpleados = async () => {
      try {
        const { data } = await rrhhAPI.listarEmpleados({ page_size: 9999, estado: 'activo' });
        setEmpleados(Array.isArray(data) ? data : data.items || []);
      } catch {
        setEmpleados([]);
        setLoadError('Error al cargar empleados');
      }
    };
    fetchEmpleados();
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

  const openAnular = (sancion) => {
    setAnularTarget(sancion);
    setAnularMotivo('');
    setAnularError(null);
  };

  const getTipoNombre = (tipoId) => {
    const tipo = config.tiposSancion.find((t) => t.id === tipoId);
    return tipo ? tipo.nombre : `#${tipoId}`;
  };

  const handleCreated = () => {
    setCrearModalOpen(false);
    placeholders.reset();
    cargarSanciones();
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
        <div className={styles.headerActions}>
          {puedeConfig && (
            <button className={styles.btnConfig} onClick={() => config.setConfigModalOpen(true)}>
              <Settings size={16} /> Tipos
            </button>
          )}
          {puedeGestionar && (
            <button className={styles.btnCreate} onClick={() => { placeholders.reset(); setCrearModalOpen(true); }}>
              <Plus size={16} /> Nueva sancion
            </button>
          )}
        </div>
      </div>

      {loadError && <div className={styles.formError}>{loadError}</div>}

      {/* Filters */}
      <div className={styles.filters}>
        <input type="number" className={styles.input} placeholder="Legajo o ID empleado" value={filtroEmpleado} onChange={(e) => { setFiltroEmpleado(e.target.value); setPage(1); }} min="1" />
        <select className={styles.select} value={filtroTipo} onChange={(e) => { setFiltroTipo(e.target.value); setPage(1); }}>
          <option value="">Todos los tipos</option>
          {config.tiposSancion.map((t) => (
            <option key={t.id} value={t.id}>{t.nombre}</option>
          ))}
        </select>
        <input type="date" className={styles.input} value={filtroDesde} onChange={(e) => { setFiltroDesde(e.target.value); setPage(1); }} title="Fecha desde" />
        <input type="date" className={styles.input} value={filtroHasta} onChange={(e) => { setFiltroHasta(e.target.value); setPage(1); }} title="Fecha hasta" />
        <label className={styles.checkboxLabel}>
          <input type="checkbox" checked={mostrarAnuladas} onChange={(e) => { setMostrarAnuladas(e.target.checked); setPage(1); }} />
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
                <td>{s.fecha_desde ? `${formatDate(s.fecha_desde)} - ${formatDate(s.fecha_hasta)}` : '-'}</td>
                <td>
                  {s.anulada ? (
                    <span className={styles.statusAnulada}>Anulada</span>
                  ) : (
                    <span className={styles.statusActiva}>Activa</span>
                  )}
                </td>
                <td>
                  <div className={styles.actions}>
                    <button className={styles.btnView} onClick={() => setDetalleOpen(s)} title="Ver detalle"><Eye size={14} /></button>
                    <button className={styles.btnView} onClick={() => setPdfTarget(s)} title="Generar PDF"><FileDown size={14} /></button>
                    {puedeGestionar && !s.anulada && (
                      <button className={styles.btnAnular} onClick={() => openAnular(s)} title="Anular sancion"><Ban size={14} /></button>
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
        <div className={styles.paginationBar}>
          <button className={styles.btnCancel} disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Anterior</button>
          <span className={styles.paginationInfo}>Pagina {page} de {totalPages}</span>
          <button className={styles.btnCancel} disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Siguiente</button>
        </div>
      )}

      {/* Create modal */}
      {crearModalOpen && (
        <CrearSancionModal
          empleados={empleados}
          tiposActivos={config.tiposActivos}
          textosActivos={config.textosActivos}
          placeholders={placeholders}
          onClose={() => setCrearModalOpen(false)}
          onCreated={handleCreated}
        />
      )}

      {/* Anular modal */}
      {anularTarget && (
        <div className="modal-overlay-tesla">
          <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Anular sancion</h2>
              <button className="btn-close-tesla" onClick={() => setAnularTarget(null)} aria-label="Cerrar modal"><X size={14} /></button>
            </div>
            <div className="modal-body-tesla">
              <p className={styles.hintText}>
                Se anulara la sancion del empleado {anularTarget.empleado_nombre || `#${anularTarget.empleado_id}`}.
                Esta accion no se puede deshacer.
              </p>
              <div className={styles.formGroup}>
                <label>Motivo de anulacion (obligatorio)</label>
                <textarea className={styles.textarea} value={anularMotivo} onChange={(e) => setAnularMotivo(e.target.value)} required />
              </div>
              {anularError && <div className={styles.inlineError}>{anularError}</div>}
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setAnularTarget(null)}>Cancelar</button>
              <button className={styles.btnAnular} onClick={handleAnular} disabled={anularSaving}>
                {anularSaving ? 'Anulando...' : 'Confirmar anulacion'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Detail modal */}
      {detalleOpen && (
        <div className="modal-overlay-tesla">
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Detalle de sancion</h2>
              <button className="btn-close-tesla" onClick={() => setDetalleOpen(null)} aria-label="Cerrar modal"><X size={14} /></button>
            </div>
            <div className="modal-body-tesla">
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Empleado</label>
                  <div className={styles.detailValue}>{detalleOpen.empleado_nombre || `#${detalleOpen.empleado_id}`}</div>
                </div>
                <div className={styles.formGroup}>
                  <label>Tipo</label>
                  <div className={styles.detailValue}>{getTipoNombre(detalleOpen.tipo_sancion_id)}</div>
                </div>
              </div>
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Fecha</label>
                  <div className={styles.detailValue}>{formatDate(detalleOpen.fecha)}</div>
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
                <div className={styles.detailValue}>{detalleOpen.motivo}</div>
              </div>
              {detalleOpen.descripcion && (
                <div className={styles.formGroup}>
                  <label>Descripcion</label>
                  <div className={styles.detailValue}>{detalleOpen.descripcion}</div>
                </div>
              )}
              {detalleOpen.texto_sancion && (
                <div className={styles.formGroup}>
                  <label>Texto de la sancion</label>
                  <div className={styles.detailValueWrap}>{detalleOpen.texto_sancion}</div>
                </div>
              )}
              {detalleOpen.fecha_desde && (
                <div className={styles.formRow}>
                  <div className={styles.formGroup}>
                    <label>Suspension desde</label>
                    <div className={styles.detailValue}>{formatDate(detalleOpen.fecha_desde)}</div>
                  </div>
                  <div className={styles.formGroup}>
                    <label>Suspension hasta</label>
                    <div className={styles.detailValue}>{formatDate(detalleOpen.fecha_hasta)}</div>
                  </div>
                </div>
              )}
              {detalleOpen.anulada && detalleOpen.anulada_motivo && (
                <div className={styles.formGroup}>
                  <label>Motivo de anulacion</label>
                  <div className={styles.detailValueError}>{detalleOpen.anulada_motivo}</div>
                </div>
              )}
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnSave} onClick={() => { setDetalleOpen(null); setPdfTarget(detalleOpen); }}>
                <FileDown size={14} /> Generar PDF
              </button>
              <button className={styles.btnCancel} onClick={() => setDetalleOpen(null)}>Cerrar</button>
            </div>
          </div>
        </div>
      )}

      {/* Config modal */}
      {config.configModalOpen && (
        <SancionesConfigModal
          config={config}
          knownPlaceholders={placeholders.knownPlaceholders}
          onShowPlaceholderHelp={() => placeholders.setShowPlaceholderHelp(true)}
        />
      )}

      {/* Placeholder help modal */}
      {placeholders.showPlaceholderHelp && (
        <div className="modal-overlay-tesla">
          <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Placeholders disponibles</h2>
              <button className="btn-close-tesla" onClick={() => placeholders.setShowPlaceholderHelp(false)} aria-label="Cerrar modal">
                <X size={14} />
              </button>
            </div>
            <div className="modal-body-tesla">
              <p className={styles.hintText}>
                Usa estos nombres entre llaves en el texto predefinido. Los marcados como <strong>auto</strong> se completan automaticamente.
              </p>
              <table className={styles.table}>
                <thead>
                  <tr><th>Placeholder</th><th>Descripcion</th></tr>
                </thead>
                <tbody>
                  {Object.entries(placeholders.knownPlaceholders).map(([key, desc]) => (
                    <tr key={key}>
                      <td><code>{`{${key}}`}</code></td>
                      <td>{desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className={styles.hintSmall}>
                Tambien podes usar placeholders custom (ej: {'{motivo_detallado}'}). Se mostraran como campo de texto libre.
              </p>
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => placeholders.setShowPlaceholderHelp(false)}>Cerrar</button>
            </div>
          </div>
        </div>
      )}

      {/* PDF Generator Modal */}
      <DocumentGeneratorModal
        isOpen={!!pdfTarget}
        contexto="sanciones"
        entityData={pdfTarget ? {
          ...pdfTarget,
          tipo_sancion_nombre: getTipoNombre(pdfTarget.tipo_sancion_id),
          empleado_nombre: pdfTarget.empleado_nombre || '',
          empleado_legajo: pdfTarget.empleado_legajo || '',
          empleado_sector: pdfTarget.empleado_sector || '',
          dias_suspension: (() => {
            if (pdfTarget.fecha_desde && pdfTarget.fecha_hasta) {
              const desde = new Date(pdfTarget.fecha_desde + 'T12:00:00');
              const hasta = new Date(pdfTarget.fecha_hasta + 'T12:00:00');
              const diff = Math.round((hasta - desde) / (1000 * 60 * 60 * 24)) + 1;
              return diff > 0 ? String(diff) : '';
            }
            return '';
          })(),
        } : {}}
        onClose={() => setPdfTarget(null)}
      />
    </div>
  );
}

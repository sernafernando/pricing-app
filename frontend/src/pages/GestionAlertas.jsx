import { useState, useEffect } from 'react';
import api from '../services/api';
import styles from './GestionAlertas.module.css';
import ModalAlertaForm from '../components/ModalAlertaForm';
import { usePermisos } from '../contexts/PermisosContext';

export default function GestionAlertas() {
  const { tienePermiso } = usePermisos();
  const [alertas, setAlertas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [alertaEditar, setAlertaEditar] = useState(null);
  const [filtroActivo, setFiltroActivo] = useState(null); // null = todas, true = activas, false = inactivas
  const [maxAlertasVisibles, setMaxAlertasVisibles] = useState(1);
  const [guardandoConfig, setGuardandoConfig] = useState(false);

  const puedeGestionar = tienePermiso('alertas.gestionar');
  const puedeConfigurar = tienePermiso('alertas.configurar');

  useEffect(() => {
    if (puedeGestionar) {
      cargarAlertas();
    }
    if (puedeConfigurar) {
      cargarConfiguracion();
    }
  }, [puedeGestionar, puedeConfigurar, filtroActivo]);

  const cargarAlertas = async () => {
    try {
      setLoading(true);
      const params = filtroActivo !== null ? { activo: filtroActivo } : {};
      const response = await api.get('/alertas', { params });
      setAlertas(response.data);
    } catch (error) {
      console.error('Error al cargar alertas:', error);
      alert('Error al cargar alertas');
    } finally {
      setLoading(false);
    }
  };

  const cargarConfiguracion = async () => {
    try {
      const response = await api.get('/alertas/configuracion/global');
      setMaxAlertasVisibles(response.data.max_alertas_visibles);
    } catch (error) {
      console.error('Error al cargar configuración:', error);
    }
  };

  const guardarConfiguracion = async () => {
    try {
      setGuardandoConfig(true);
      await api.put('/alertas/configuracion/global', {
        max_alertas_visibles: maxAlertasVisibles
      });
      alert('✅ Configuración guardada');
    } catch (error) {
      console.error('Error al guardar configuración:', error);
      alert('❌ Error al guardar configuración');
    } finally {
      setGuardandoConfig(false);
    }
  };

  const handleCrear = () => {
    setAlertaEditar(null);
    setModalOpen(true);
  };

  const handleEditar = (alerta) => {
    setAlertaEditar(alerta);
    setModalOpen(true);
  };

  const handleEliminar = async (alertaId) => {
    if (!confirm('¿Estás seguro de desactivar esta alerta?')) {
      return;
    }

    try {
      await api.patch(`/alertas/${alertaId}/desactivar`);
      alert('✅ Alerta desactivada');
      cargarAlertas();
    } catch (error) {
      console.error('Error al desactivar alerta:', error);
      alert('Error al desactivar alerta');
    }
  };

  const handleToggleActivo = async (alerta) => {
    try {
      await api.put(`/alertas/${alerta.id}`, {
        activo: !alerta.activo
      });
      cargarAlertas();
    } catch (error) {
      console.error('Error al cambiar estado:', error);
      alert('Error al cambiar estado');
    }
  };

  const handleModalClose = (actualizado) => {
    setModalOpen(false);
    setAlertaEditar(null);
    if (actualizado) {
      cargarAlertas();
    }
  };

  const getVariantBadge = (variant) => {
    const colors = {
      info: styles.variantInfo,
      warning: styles.variantWarning,
      success: styles.variantSuccess,
      error: styles.variantError
    };
    return colors[variant] || colors.info;
  };

  const formatFecha = (fecha) => {
    if (!fecha) return '-';
    return new Date(fecha).toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (!puedeGestionar) {
    return (
      <div className={styles.noPermiso}>
        <h2>⛔ Sin Permisos</h2>
        <p>No tenés permiso para gestionar alertas.</p>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>Gestión de Alertas</h1>
        <button className="btn-tesla outline-subtle-primary" onClick={handleCrear}>
          + Nueva Alerta
        </button>
      </div>

      {/* Configuración Global */}
      {puedeConfigurar && (
        <div className={styles.configPanel}>
          <h3>⚙️ Configuración Global</h3>
          <div className={styles.configRow}>
            <label htmlFor="maxAlertas">Máximo de alertas visibles simultáneamente:</label>
            <select
              id="maxAlertas"
              value={maxAlertasVisibles}
              onChange={(e) => setMaxAlertasVisibles(parseInt(e.target.value))}
              className={styles.configInput}
            >
              <option value={1}>1 alerta</option>
              <option value={2}>2 alertas</option>
              <option value={3}>3 alertas</option>
              <option value={4}>4 alertas</option>
              <option value={5}>5 alertas</option>
              <option value={10}>10 alertas</option>
            </select>
            <button
              className="btn-tesla outline-subtle-success sm"
              onClick={guardarConfiguracion}
              disabled={guardandoConfig}
            >
              {guardandoConfig ? 'Guardando...' : 'Guardar'}
            </button>
          </div>
          <small className={styles.hint}>
            Las alertas con duración 0 (sticky) siempre se muestran. Las demás rotan según este límite.
          </small>
        </div>
      )}

      <div className={styles.filtros}>
        <button
          className={`btn-tesla ${filtroActivo === null ? 'outline-subtle-primary' : 'secondary'} sm`}
          onClick={() => setFiltroActivo(null)}
        >
          Todas
        </button>
        <button
          className={`btn-tesla ${filtroActivo === true ? 'outline-subtle-primary' : 'secondary'} sm`}
          onClick={() => setFiltroActivo(true)}
        >
          Activas
        </button>
        <button
          className={`btn-tesla ${filtroActivo === false ? 'outline-subtle-primary' : 'secondary'} sm`}
          onClick={() => setFiltroActivo(false)}
        >
          Inactivas
        </button>
      </div>

      {loading ? (
        <div className={styles.loading}>Cargando...</div>
      ) : alertas.length === 0 ? (
        <div className={styles.empty}>
          No hay alertas {filtroActivo === true ? 'activas' : filtroActivo === false ? 'inactivas' : ''}.
        </div>
      ) : (
        <div className="table-container-tesla">
          <table className="table-tesla striped">
            <thead className="table-tesla-head">
              <tr>
                <th>Estado</th>
                <th>Título</th>
                <th>Variant</th>
                <th>Vigencia</th>
                <th>Prioridad</th>
                <th>Comportamiento</th>
                <th>Destinatarios</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody className="table-tesla-body">
              {alertas.map((alerta) => (
                <tr key={alerta.id}>
                  <td>
                    <button
                      className={`btn-tesla ${alerta.activo ? 'outline-subtle-success' : 'outline-subtle-danger'} sm`}
                      onClick={() => handleToggleActivo(alerta)}
                      title={alerta.activo ? 'Desactivar' : 'Activar'}
                    >
                      {alerta.activo ? '✓ Activa' : '✗ Inactiva'}
                    </button>
                  </td>
                  <td className={styles.titulo}>{alerta.titulo}</td>
                  <td>
                    <span className={`${styles.variantBadge} ${getVariantBadge(alerta.variant)}`}>
                      {alerta.variant}
                    </span>
                  </td>
                  <td className={styles.vigencia}>
                    <div>{formatFecha(alerta.fecha_desde)}</div>
                    <div className={styles.fechaHasta}>
                      {alerta.fecha_hasta ? `→ ${formatFecha(alerta.fecha_hasta)}` : '(Indefinida)'}
                    </div>
                  </td>
                  <td className={styles.prioridad}>{alerta.prioridad}</td>
                  <td className={styles.comportamiento}>
                    <div className={styles.badges}>
                      {alerta.duracion_segundos === 0 ? (
                        <span className={styles.badgeSticky}>Sticky</span>
                      ) : (
                        <span className={styles.badgeDuracion}>{alerta.duracion_segundos}s</span>
                      )}
                      {alerta.persistent && (
                        <span className={styles.badgePersistent}>Persistent</span>
                      )}
                      {!alerta.dismissible && (
                        <span className={styles.badgeNoDismiss}>No cerrable</span>
                      )}
                    </div>
                  </td>
                  <td className={styles.destinatarios}>
                    {alerta.roles_destinatarios.includes('*') ? (
                      <span className={styles.todos}>Todos</span>
                    ) : (
                      <>
                        {alerta.roles_destinatarios.length > 0 && (
                          <div className={styles.roles}>
                            {alerta.roles_destinatarios.join(', ')}
                          </div>
                        )}
                        {alerta.usuarios_destinatarios && alerta.usuarios_destinatarios.length > 0 && (
                          <div className={styles.usuarios}>
                            + {alerta.usuarios_destinatarios.length} usuarios
                          </div>
                        )}
                      </>
                    )}
                  </td>
                  <td>
                    <div className={styles.acciones}>
                      <button
                        className="btn-tesla secondary icon-only sm"
                        onClick={() => handleEditar(alerta)}
                        title="Editar"
                        aria-label="Editar alerta"
                      >
                        ✎
                      </button>
                      <button
                        className="btn-tesla outline-subtle-danger icon-only sm"
                        onClick={() => handleEliminar(alerta.id)}
                        title="Eliminar"
                        aria-label="Eliminar alerta"
                      >
                        ✕
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalOpen && (
        <ModalAlertaForm
          alerta={alertaEditar}
          onClose={handleModalClose}
        />
      )}
    </div>
  );
}

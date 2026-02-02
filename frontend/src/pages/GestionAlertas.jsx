import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './GestionAlertas.module.css';
import ModalAlertaForm from '../components/ModalAlertaForm';
import { usePermisos } from '../contexts/PermisosContext';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default function GestionAlertas() {
  const { tienePermiso } = usePermisos();
  const [alertas, setAlertas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [alertaEditar, setAlertaEditar] = useState(null);
  const [filtroActivo, setFiltroActivo] = useState(null); // null = todas, true = activas, false = inactivas

  const puedeGestionar = tienePermiso('alertas.gestionar');

  useEffect(() => {
    if (puedeGestionar) {
      cargarAlertas();
    }
  }, [puedeGestionar, filtroActivo]);

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

  const handleCrear = () => {
    setAlertaEditar(null);
    setModalOpen(true);
  };

  const handleEditar = (alerta) => {
    setAlertaEditar(alerta);
    setModalOpen(true);
  };

  const handleEliminar = async (alertaId) => {
    if (!confirm('¿Estás seguro de eliminar esta alerta? (Se desactivará)')) {
      return;
    }

    try {
      await api.delete(`/alertas/${alertaId}`);
      alert('✅ Alerta eliminada');
      cargarAlertas();
    } catch (error) {
      console.error('Error al eliminar alerta:', error);
      alert('Error al eliminar alerta');
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
                <th>Mensaje</th>
                <th>Variant</th>
                <th>Vigencia</th>
                <th>Prioridad</th>
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
                  <td className={styles.mensaje}>{alerta.mensaje}</td>
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

import { useState, useEffect } from 'react';
import api from '../services/api';
import styles from './TabRentabilidad.module.css';

export default function TabAdminVentasFuera() {
  const [loading, setLoading] = useState(true);
  const [vendedoresExcluidos, setVendedoresExcluidos] = useState([]);
  const [vendedoresDisponibles, setVendedoresDisponibles] = useState([]);
  const [busqueda, setBusqueda] = useState('');
  const [mostrarModal, setMostrarModal] = useState(false);
  const [vendedorSeleccionado, setVendedorSeleccionado] = useState(null);
  const [motivo, setMotivo] = useState('');
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState('');



  useEffect(() => {
    cargarVendedoresExcluidos();
  }, []);

  const cargarVendedoresExcluidos = async () => {
    setLoading(true);
    try {
      const response = await api.get('/vendedores-excluidos');
      setVendedoresExcluidos(response.data);
    } catch (err) {
      console.error('Error cargando vendedores excluidos:', err);
      setError('Error al cargar la lista de vendedores excluidos');
    } finally {
      setLoading(false);
    }
  };

  const buscarVendedores = async (termino) => {
    if (termino.length < 2) {
      setVendedoresDisponibles([]);
      return;
    }

    try {
      const response = await api.get('/vendedores-excluidos/disponibles', {
        params: { buscar: termino }
      });
      setVendedoresDisponibles(response.data);
    } catch (err) {
      console.error('Error buscando vendedores:', err);
    }
  };

  const handleBusquedaChange = (e) => {
    const valor = e.target.value;
    setBusqueda(valor);
    buscarVendedores(valor);
  };

  const abrirModalExcluir = (vendedor) => {
    setVendedorSeleccionado(vendedor);
    setMotivo('');
    setMostrarModal(true);
  };

  const cerrarModal = () => {
    setMostrarModal(false);
    setVendedorSeleccionado(null);
    setMotivo('');
  };

  const confirmarExclusion = async () => {
    if (!vendedorSeleccionado) return;

    setGuardando(true);
    try {
      await api.post('/vendedores-excluidos', {
        sm_id: vendedorSeleccionado.sm_id,
        sm_name: vendedorSeleccionado.sm_name,
        motivo: motivo || null
      });

      await cargarVendedoresExcluidos();
      setBusqueda('');
      setVendedoresDisponibles([]);
      cerrarModal();
    } catch (err) {
      console.error('Error excluyendo vendedor:', err);
      setError(err.response?.data?.detail || 'Error al excluir vendedor');
    } finally {
      setGuardando(false);
    }
  };

  const eliminarExclusion = async (sm_id) => {
    if (!confirm('¿Estás seguro de quitar este vendedor de la lista de excluidos?')) {
      return;
    }

    try {
      await api.delete(`/vendedores-excluidos/${sm_id}`);

      await cargarVendedoresExcluidos();
    } catch (err) {
      console.error('Error eliminando exclusión:', err);
      setError(err.response?.data?.detail || 'Error al eliminar exclusión');
    }
  };

  if (loading) {
    return <div className={styles.loading}>Cargando...</div>;
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h2>Vendedores Excluidos</h2>
        <p className={styles.descripcion}>
          Los vendedores en esta lista no aparecerán en los reportes de Ventas por Fuera de ML
        </p>
      </div>

      {error && (
        <div className={styles.error}>
          {error}
          <button onClick={() => setError('')}>×</button>
        </div>
      )}

      {/* Buscador para agregar vendedores */}
      <div className={styles.seccionBuscar}>
        <h3>Agregar vendedor a excluir</h3>
        <div className={styles.buscadorContainer}>
          <input
            type="text"
            placeholder="Buscar vendedor por nombre..."
            value={busqueda}
            onChange={handleBusquedaChange}
            className={styles.inputBuscar}
          />
        </div>

        {vendedoresDisponibles.length > 0 && (
          <div className={styles.listaResultados}>
            {vendedoresDisponibles.map(v => (
              <div key={v.sm_id} className={styles.itemResultado}>
                <div className={styles.infoVendedor}>
                  <span className={styles.nombreVendedor}>{v.sm_name}</span>
                  <span className={styles.idVendedor}>ID: {v.sm_id}</span>
                </div>
                {v.ya_excluido ? (
                  <span className={styles.yaExcluido}>Ya excluido</span>
                ) : (
                  <button
                    onClick={() => abrirModalExcluir(v)}
                    className={styles.btnExcluir}
                  >
                    Excluir
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Lista de vendedores excluidos */}
      <div className={styles.seccionLista}>
        <h3>Vendedores actualmente excluidos ({vendedoresExcluidos.length})</h3>

        {vendedoresExcluidos.length === 0 ? (
          <p className={styles.sinResultados}>No hay vendedores excluidos</p>
        ) : (
          <div className={styles.tablaContainer}>
            <table className={styles.tabla}>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Nombre</th>
                  <th>Motivo</th>
                  <th>Fecha</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {vendedoresExcluidos.map(v => (
                  <tr key={v.sm_id}>
                    <td>{v.sm_id}</td>
                    <td>{v.sm_name || '-'}</td>
                    <td>{v.motivo || '-'}</td>
                    <td>{new Date(v.created_at).toLocaleDateString('es-AR')}</td>
                    <td>
                      <button
                        onClick={() => eliminarExclusion(v.sm_id)}
                        className={styles.btnEliminar}
                        title="Quitar de excluidos"
                      >
                        Quitar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal de confirmación */}
      {mostrarModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modal}>
            <h3>Excluir vendedor</h3>
            <p>
              ¿Estás seguro de excluir a <strong>{vendedorSeleccionado?.sm_name}</strong> (ID: {vendedorSeleccionado?.sm_id})?
            </p>
            <div className={styles.formGroup}>
              <label>Motivo (opcional):</label>
              <input
                type="text"
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                placeholder="Ej: Ventas internas, pruebas, etc."
                className={styles.inputMotivo}
              />
            </div>
            <div className={styles.modalBotones}>
              <button
                onClick={cerrarModal}
                className={styles.btnCancelar}
                disabled={guardando}
              >
                Cancelar
              </button>
              <button
                onClick={confirmarExclusion}
                className={styles.btnConfirmar}
                disabled={guardando}
              >
                {guardando ? 'Guardando...' : 'Confirmar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

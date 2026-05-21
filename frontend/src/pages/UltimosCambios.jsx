import { useState, useEffect } from 'react';
import api from '../services/api';
import styles from './UltimosCambios.module.css';

export default function UltimosCambios() {
  const [cambios, setCambios] = useState([]);
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState(50);

  useEffect(() => {
    cargarCambios();
    // cargarCambios se recrea cada render — recargar solo cuando cambia el límite
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit]);

  const cargarCambios = async () => {
    setLoading(true);
    try {
      const response = await api.get(
        `/auditoria/ultimos-cambios`,
        { params: { limit } }
      );
      setCambios(response.data);
    } catch (error) {
      console.error('Error cargando cambios:', error);
      alert('Error al cargar los cambios');
    } finally {
      setLoading(false);
    }
  };

  const formatearTipoAccion = (tipo) => {
    const tipos = {
      'modificar_precio_clasica': '💰 Precio Clásica',
      'modificar_precio_web': '🌐 Precio Web',
      'activar_rebate': '✅ Activar Rebate',
      'desactivar_rebate': '❌ Desactivar Rebate',
      'modificar_porcentaje_rebate': '📊 % Rebate',
      'marcar_out_of_cards': '🚫 Out of Cards ON',
      'desmarcar_out_of_cards': '✅ Out of Cards OFF',
      'activar_web_transferencia': '✅ Web Transf. ON',
      'desactivar_web_transferencia': '❌ Web Transf. OFF',
      'modificacion_masiva': '📦 Modificación Masiva'
    };
    return tipos[tipo] || tipo;
  };

  const formatearValores = (valores) => {
    if (!valores) return '-';
    return Object.entries(valores).map(([key, value]) => {
      const displayValue = typeof value === 'number' ? value.toFixed(2) : String(value);
      return `${key}: ${displayValue}`;
    }).join(', ');
  };

  const formatearFecha = (fecha) => {
    // Asegurar que se interprete como UTC y convertir a GMT-3
    const date = new Date(fecha + (fecha.includes('Z') ? '' : 'Z'));
    
    // Crear fechas de referencia en GMT-3
    const hoy = new Date();
    const ayer = new Date(hoy);
    ayer.setDate(ayer.getDate() - 1);
    
    const esHoy = date.toLocaleDateString('es-AR', { timeZone: 'America/Argentina/Buenos_Aires' }) === 
                  hoy.toLocaleDateString('es-AR', { timeZone: 'America/Argentina/Buenos_Aires' });
    const esAyer = date.toLocaleDateString('es-AR', { timeZone: 'America/Argentina/Buenos_Aires' }) === 
                   ayer.toLocaleDateString('es-AR', { timeZone: 'America/Argentina/Buenos_Aires' });
    
    const hora = date.toLocaleTimeString('es-AR', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'America/Argentina/Buenos_Aires'
    });
    
    if (esHoy) return `Hoy ${hora}`;
    if (esAyer) return `Ayer ${hora}`;
    
    return date.toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'America/Argentina/Buenos_Aires'
    });
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>📋 Últimos Cambios</h1>
        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className={styles.limitSelect}
        >
          <option value={25}>Últimos 25</option>
          <option value={50}>Últimos 50</option>
          <option value={100}>Últimos 100</option>
          <option value={200}>Últimos 200</option>
        </select>
      </div>

      {loading ? (
        <div className={styles.loading}>Cargando cambios...</div>
      ) : cambios.length === 0 ? (
        <div className={styles.empty}>No hay cambios registrados</div>
      ) : (
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Fecha y Hora</th>
                <th>Usuario</th>
                <th>Producto</th>
                <th>Tipo de Cambio</th>
                <th>Valores Anteriores</th>
                <th>Valores Nuevos</th>
                <th>Comentario</th>
              </tr>
            </thead>
            <tbody>
              {cambios.map(cambio => (
                <tr key={cambio.id}>
                  <td>
                    <div className={styles.fecha}>
                      {formatearFecha(cambio.fecha_cambio)}
                    </div>
                  </td>
                  <td>
                    <div className={styles.usuario}>
                      <strong>{cambio.usuario_nombre}</strong>
                      <small>{cambio.usuario_email}</small>
                    </div>
                  </td>
                  <td>
                    <div className={styles.producto}>
                      {cambio.codigo ? (
                        <>
                          <strong>{cambio.codigo}</strong>
                          <div className={styles.descripcion}>
                            {cambio.descripcion}
                          </div>
                          {cambio.marca && (
                            <small className={styles.marca}>{cambio.marca}</small>
                          )}
                        </>
                      ) : (
                        <div>
                          <strong>{cambio.descripcion}</strong>
                          {cambio.productos_afectados && (
                            <small> ({cambio.productos_afectados} productos)</small>
                          )}
                        </div>
                      )}
                    </div>
                  </td>
                  <td>
                    <strong>{formatearTipoAccion(cambio.tipo_accion)}</strong>
                  </td>
                  <td className={styles.valores}>
                    <small>{formatearValores(cambio.valores_anteriores)}</small>
                  </td>
                  <td className={styles.valores}>
                    <small>{formatearValores(cambio.valores_nuevos)}</small>
                  </td>
                  <td>
                    <small className={styles.comentario}>
                      {cambio.comentario || '-'}
                    </small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

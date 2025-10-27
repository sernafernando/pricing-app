import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './UltimosCambios.module.css';

export default function UltimosCambios() {
  const [cambios, setCambios] = useState([]);
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState(50);

  useEffect(() => {
    cargarCambios();
  }, [limit]);

  const cargarCambios = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(
        `https://pricing.gaussonline.com.ar/api/auditoria/ultimos-cambios?limit=${limit}`,
        { headers: { Authorization: `Bearer ${token}` }}
      );
      setCambios(response.data);
    } catch (error) {
      console.error('Error cargando cambios:', error);
      alert('Error al cargar los cambios');
    } finally {
      setLoading(false);
    }
  };

  const getChangeColor = (cambio) => {
    if (cambio > 0) return '#059669';
    if (cambio < 0) return '#dc2626';
    return '#6b7280';
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
        <h1 className={styles.title}>📋 Últimos Cambios de Precios</h1>
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
                <th>Precio Anterior</th>
                <th>Precio Nuevo</th>
                <th>Cambio</th>
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
                      <strong>{cambio.codigo}</strong>
                      <div className={styles.descripcion}>
                        {cambio.descripcion}
                      </div>
                      {cambio.marca && (
                        <small className={styles.marca}>{cambio.marca}</small>
                      )}
                    </div>
                  </td>
                  <td className={styles.precio}>
                    ${cambio.precio_anterior.toLocaleString('es-AR', {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2
                    })}
                  </td>
                  <td className={styles.precio}>
                    ${cambio.precio_nuevo.toLocaleString('es-AR', {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2
                    })}
                  </td>
                  <td>
                    <div 
                      className={styles.cambio}
                      style={{ color: getChangeColor(cambio.cambio) }}
                    >
                      <strong>
                        {cambio.cambio >= 0 ? '+' : ''}
                        ${cambio.cambio.toLocaleString('es-AR', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2
                        })}
                      </strong>
                      <small>
                        ({cambio.cambio_porcentaje >= 0 ? '+' : ''}
                        {cambio.cambio_porcentaje.toFixed(2)}%)
                      </small>
                    </div>
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

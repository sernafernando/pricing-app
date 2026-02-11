import { useState, useEffect } from 'react';
import api from '../../services/api';
import styles from '../../pages/TurboRouting.module.css';

export default function TabBanlist() {
  const [banlist, setBanlist] = useState([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  
  // Form state
  const [mlshippingid, setMlshippingid] = useState('');
  const [motivo, setMotivo] = useState('');
  const [notas, setNotas] = useState('');
  const [enviando, setEnviando] = useState(false);

  const fetchBanlist = async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/turbo/banlist');
      setBanlist(data.items || []);
      setTotal(data.total || 0);
    } catch {
      alert('Error cargando banlist');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBanlist();
  }, []);

  const handleBanear = async (e) => {
    e.preventDefault();
    
    if (!mlshippingid.trim() || !motivo) {
      alert('Completá ID del envío y motivo');
      return;
    }

    setEnviando(true);
    try {
      await api.post('/turbo/banlist', {
        mlshippingid: mlshippingid.trim(),
        motivo,
        notas: notas.trim() || null
      });
      
      alert(`✅ Envío ${mlshippingid} agregado a banlist`);
      
      // Reset form
      setMlshippingid('');
      setMotivo('');
      setNotas('');
      
      // Refresh list
      fetchBanlist();
    } catch (error) {
      const errorMsg = error.response?.data?.detail || 'Error baneando envío';
      alert(`❌ ${errorMsg}`);
    } finally {
      setEnviando(false);
    }
  };

  const handleDesbanear = async (id, mlshippingid) => {
    if (!confirm(`¿Seguro que querés quitar "${mlshippingid}" de la banlist?\n\nEste envío volverá a aparecer en el sistema.`)) {
      return;
    }

    try {
      await api.delete(`/turbo/banlist/${id}`);
      
      alert(`✅ Envío ${mlshippingid} removido de banlist`);
      fetchBanlist();
    } catch {
      alert('❌ Error removiendo de banlist');
    }
  };

  const formatFecha = (fecha) => {
    if (!fecha) return '-';
    return new Date(fecha).toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getMotivoClass = (motivo) => {
    const map = {
      estado_buggeado: styles.motivoEstadoBuggeado,
      duplicado: styles.motivoDuplicado,
      inconsistencia_ml: styles.motivoInconsistenciaMl,
      error_sincronizacion: styles.motivoErrorSincronizacion,
      otro: styles.motivoOtro
    };
    return `${styles.motivoBadge} ${map[motivo] || styles.motivoOtro}`;
  };

  return (
    <div className={styles.tabContent}>
      <div className={styles.header}>
        <div>
          <h2>🚫 Banlist de Envíos Turbo</h2>
          <p className={styles.subtitle}>
            Envíos excluidos del sistema por estados buggeados o inconsistencias.
            {total > 0 && <strong> Total: {total}</strong>}
          </p>
        </div>
      </div>

      {/* FORMULARIO AGREGAR A BANLIST */}
      <div className={`${styles.card} ${styles.cardMarginBottom}`}>
        <h3 className={styles.sectionTitle}>Agregar Envío a Banlist</h3>
        <form onSubmit={handleBanear} className={styles.formBanlist}>
          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label htmlFor="mlshippingid">ID Envío ML *</label>
              <input
                id="mlshippingid"
                type="text"
                placeholder="Ej: 45335511237"
                value={mlshippingid}
                onChange={(e) => setMlshippingid(e.target.value)}
                required
                disabled={enviando}
              />
            </div>
            
            <div className={styles.formGroup}>
              <label htmlFor="motivo">Motivo *</label>
              <select
                id="motivo"
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                required
                disabled={enviando}
              >
                <option value="">Seleccionar...</option>
                <option value="estado_buggeado">Estado Buggeado</option>
                <option value="duplicado">Duplicado</option>
                <option value="inconsistencia_ml">Inconsistencia ML</option>
                <option value="error_sincronizacion">Error de Sincronización</option>
                <option value="otro">Otro</option>
              </select>
            </div>
          </div>

          <div className={styles.formGroup}>
            <label htmlFor="notas">Notas Adicionales (opcional)</label>
            <textarea
              id="notas"
              placeholder="Ej: Estado stuck desde diciembre 2025, consultado con ML sin solución"
              value={notas}
              onChange={(e) => setNotas(e.target.value)}
              rows={3}
              disabled={enviando}
            />
          </div>

          <button 
            type="submit" 
            className={styles.btnPrimary}
            disabled={enviando}
          >
            {enviando ? '⏳ Agregando...' : '🚫 Agregar a Banlist'}
          </button>
        </form>
      </div>

      {/* TABLA DE BANLIST */}
      <div className={styles.card}>
        <h3 className={styles.sectionTitle}>Envíos Baneados</h3>
        
        {loading ? (
          <div className={styles.loadingState}>
            <p>⏳ Cargando banlist...</p>
          </div>
        ) : banlist.length === 0 ? (
          <div className={styles.emptyState}>
            <p>✅ No hay envíos en banlist.</p>
            <p>Los envíos baneados aparecerán aquí.</p>
          </div>
        ) : (
          <div className={styles.tableContainer}>
            <table className={styles.tablaTesla}>
              <thead>
                <tr>
                  <th>ID Envío ML</th>
                  <th>Motivo</th>
                  <th>Notas</th>
                  <th>Baneado Por</th>
                  <th>Fecha</th>
                  <th className={styles.actionColumn}>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {banlist.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <code className={styles.codeTag}>
                        {item.mlshippingid}
                      </code>
                    </td>
                    <td>
                      <span className={getMotivoClass(item.motivo)}>
                        {item.motivo.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td className={styles.notasCell}>
                      {item.notas || <span className={styles.textSecondary}>-</span>}
                    </td>
                    <td>
                      {item.baneado_por || <span className={styles.textSecondary}>Sistema</span>}
                    </td>
                    <td className={styles.fechaCell}>
                      {formatFecha(item.baneado_at)}
                    </td>
                    <td>
                      <button
                        onClick={() => handleDesbanear(item.id, item.mlshippingid)}
                        className={styles.btnDangerSmall}
                      >
                        ✅ Desbanear
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

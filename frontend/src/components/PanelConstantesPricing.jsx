import { useState, useEffect } from 'react';
import api from '../services/api';
import './PanelConstantesPricing.css';
import { useModalClickOutside } from '../hooks/useModalClickOutside';

export default function PanelConstantesPricing() {
  const modalNuevaVersion = useModalClickOutside(() => setMostrarFormNuevaVersion(false));
  const [constanteActual, setConstanteActual] = useState(null);
  const [versiones, setVersiones] = useState([]);
  const [mostrarFormNuevaVersion, setMostrarFormNuevaVersion] = useState(false);
  const [cargando, setCargando] = useState(false);

  // Estado para nueva versión
  const [nuevaVersion, setNuevaVersion] = useState({
    monto_tier1: 15000,
    monto_tier2: 24000,
    monto_tier3: 33000,
    comision_tier1: 1095,
    comision_tier2: 2190,
    comision_tier3: 2628,
    varios_porcentaje: 6.5,
    grupo_comision_default: 1,
    markup_adicional_cuotas: 4.0,
    comision_tienda_nube: 1.0,
    comision_tienda_nube_tarjeta: 3.0,
    offset_flex: '',
    fecha_desde: new Date().toISOString().split('T')[0]
  });

  useEffect(() => {
    cargarDatos();
  }, []);

  const cargarDatos = async () => {
    setCargando(true);
    try {
      // Cargar constantes actuales
      const actual = await api.get('/pricing-constants/actual');
      setConstanteActual(actual.data);

      // Cargar todas las versiones
      const todasVersiones = await api.get('/pricing-constants');
      setVersiones(todasVersiones.data);

    } catch (error) {
      console.error('Error cargando constantes:', error);
      alert('Error al cargar constantes de pricing');
    } finally {
      setCargando(false);
    }
  };

  const copiarDatosActuales = () => {
    if (!constanteActual) return;

    setNuevaVersion({
      ...constanteActual,
      offset_flex: constanteActual.offset_flex ?? '',
      fecha_desde: new Date().toISOString().split('T')[0]
    });
  };

  const handleGuardarNuevaVersion = async () => {
    if (!nuevaVersion.fecha_desde) {
      alert('Debe especificar una fecha de inicio');
      return;
    }

    try {
      setCargando(true);

      const payload = {
        ...nuevaVersion,
        offset_flex: nuevaVersion.offset_flex === '' ? null : nuevaVersion.offset_flex,
      };
      await api.post('/pricing-constants', payload);

      alert('Nueva versión de constantes creada correctamente');
      setMostrarFormNuevaVersion(false);
      cargarDatos();
    } catch (error) {
      console.error('Error guardando nueva versión:', error);
      alert(error.response?.data?.detail || 'Error al guardar nueva versión');
    } finally {
      setCargando(false);
    }
  };

  const handleEliminarVersion = async (id) => {
    if (!confirm('¿Está seguro de eliminar esta versión?')) return;

    try {
      setCargando(true);

      await api.delete(`/pricing-constants/${id}`);

      alert('Versión eliminada correctamente');
      cargarDatos();
    } catch (error) {
      console.error('Error eliminando versión:', error);
      alert(error.response?.data?.detail || 'Error al eliminar versión');
    } finally {
      setCargando(false);
    }
  };

  if (cargando && !constanteActual) {
    return <div className="panel-constantes-pricing"><p>Cargando...</p></div>;
  }

  return (
    <div className="panel-constantes-pricing">
      <div className="constantes-header">
        <h2>Constantes de Pricing</h2>
        <div className="header-buttons">
          <button
            className="btn-secondary"
            onClick={() => {
              copiarDatosActuales();
              setMostrarFormNuevaVersion(true);
            }}
            disabled={!constanteActual}
          >
            ✏️ Editar Valores Actuales
          </button>
          <button
            className="btn-tesla outline-subtle-primary"
            onClick={() => {
              copiarDatosActuales();
              setMostrarFormNuevaVersion(true);
            }}
            disabled={!constanteActual}
          >
            + Nueva Versión (Futuro)
          </button>
        </div>
      </div>

      {/* Constantes Actuales */}
      {constanteActual && (
        <div className="constantes-actuales">
          <h3>Valores Vigentes</h3>
          <div className="constantes-grid">
            <div className="constante-item">
              <label>Monto Tier 1 (&lt; este monto):</label>
              <span>${constanteActual.monto_tier1?.toLocaleString('es-AR')}</span>
            </div>
            <div className="constante-item">
              <label>Comisión Tier 1:</label>
              <span>${constanteActual.comision_tier1?.toLocaleString('es-AR')}</span>
            </div>
            <div className="constante-item">
              <label>Monto Tier 2:</label>
              <span>${constanteActual.monto_tier2?.toLocaleString('es-AR')}</span>
            </div>
            <div className="constante-item">
              <label>Comisión Tier 2:</label>
              <span>${constanteActual.comision_tier2?.toLocaleString('es-AR')}</span>
            </div>
            <div className="constante-item">
              <label>Monto Tier 3 (envío gratis):</label>
              <span>${constanteActual.monto_tier3?.toLocaleString('es-AR')}</span>
            </div>
            <div className="constante-item">
              <label>Comisión Tier 3:</label>
              <span>${constanteActual.comision_tier3?.toLocaleString('es-AR')}</span>
            </div>
            <div className="constante-item">
              <label>Varios (%):</label>
              <span>{constanteActual.varios_porcentaje}%</span>
            </div>
            <div className="constante-item">
              <label>Grupo Comisión Default:</label>
              <span>{constanteActual.grupo_comision_default}</span>
            </div>
            <div className="constante-item">
              <label>Markup Adicional Cuotas (%):</label>
              <span>{constanteActual.markup_adicional_cuotas}%</span>
            </div>
          </div>

          <h4 style={{marginTop: '20px', marginBottom: '10px'}}>Otros Parámetros</h4>
          <div className="constantes-grid">
            <div className="constante-item">
              <label>Offset Flex ($):</label>
              <span>{constanteActual.offset_flex != null ? `$${Number(constanteActual.offset_flex).toLocaleString('es-AR')}` : 'Sin asignar'}</span>
            </div>
          </div>

          <h4 style={{marginTop: '20px', marginBottom: '10px'}}>Comisiones Tienda Nube</h4>
          <div className="constantes-grid">
            <div className="constante-item">
              <label>Comisión Efectivo/Transferencia (%):</label>
              <span>{constanteActual.comision_tienda_nube || 1.0}%</span>
            </div>
            <div className="constante-item">
              <label>Comisión Tarjeta (%):</label>
              <span>{constanteActual.comision_tienda_nube_tarjeta || 3.0}%</span>
            </div>
          </div>
        </div>
      )}

      {/* Formulario Nueva Versión */}
      {mostrarFormNuevaVersion && (
        <div
          ref={modalNuevaVersion.overlayRef}
          className="modal-overlay"
          onMouseDown={modalNuevaVersion.handleOverlayMouseDown}
          onClick={modalNuevaVersion.handleOverlayClick}
        >
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>Nueva Versión de Constantes</h3>

            <div className="form-constantes">
              <div className="form-group">
                <label>Fecha Desde:</label>
                <input
                  type="date"
                  value={nuevaVersion.fecha_desde}
                  onChange={e => setNuevaVersion({...nuevaVersion, fecha_desde: e.target.value})}
                />
              </div>

              <h4>Tiers de Precio</h4>
              <div className="form-row">
                <div className="form-group">
                  <label>Monto Tier 1:</label>
                  <input
                    type="number"
                    value={nuevaVersion.monto_tier1}
                    onChange={e => setNuevaVersion({...nuevaVersion, monto_tier1: parseFloat(e.target.value)})}
                  />
                </div>
                <div className="form-group">
                  <label>Comisión Tier 1:</label>
                  <input
                    type="number"
                    value={nuevaVersion.comision_tier1}
                    onChange={e => setNuevaVersion({...nuevaVersion, comision_tier1: parseFloat(e.target.value)})}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Monto Tier 2:</label>
                  <input
                    type="number"
                    value={nuevaVersion.monto_tier2}
                    onChange={e => setNuevaVersion({...nuevaVersion, monto_tier2: parseFloat(e.target.value)})}
                  />
                </div>
                <div className="form-group">
                  <label>Comisión Tier 2:</label>
                  <input
                    type="number"
                    value={nuevaVersion.comision_tier2}
                    onChange={e => setNuevaVersion({...nuevaVersion, comision_tier2: parseFloat(e.target.value)})}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Monto Tier 3 (envío gratis):</label>
                  <input
                    type="number"
                    value={nuevaVersion.monto_tier3}
                    onChange={e => setNuevaVersion({...nuevaVersion, monto_tier3: parseFloat(e.target.value)})}
                  />
                </div>
                <div className="form-group">
                  <label>Comisión Tier 3:</label>
                  <input
                    type="number"
                    value={nuevaVersion.comision_tier3}
                    onChange={e => setNuevaVersion({...nuevaVersion, comision_tier3: parseFloat(e.target.value)})}
                  />
                </div>
              </div>

              <h4>Otros Parámetros</h4>
              <div className="form-row">
                <div className="form-group">
                  <label>Varios (%):</label>
                  <input
                    type="number"
                    step="0.1"
                    value={nuevaVersion.varios_porcentaje}
                    onChange={e => setNuevaVersion({...nuevaVersion, varios_porcentaje: parseFloat(e.target.value)})}
                  />
                </div>
                <div className="form-group">
                  <label>Grupo Comisión Default:</label>
                  <input
                    type="number"
                    value={nuevaVersion.grupo_comision_default}
                    onChange={e => setNuevaVersion({...nuevaVersion, grupo_comision_default: parseInt(e.target.value)})}
                  />
                </div>
                <div className="form-group">
                  <label>Markup Adicional Cuotas (%):</label>
                  <input
                    type="number"
                    step="0.1"
                    value={nuevaVersion.markup_adicional_cuotas}
                    onChange={e => setNuevaVersion({...nuevaVersion, markup_adicional_cuotas: parseFloat(e.target.value)})}
                  />
                </div>
                <div className="form-group">
                  <label>Offset Flex ($):</label>
                  <input
                    type="number"
                    step="0.01"
                    value={nuevaVersion.offset_flex}
                    onChange={e => setNuevaVersion({...nuevaVersion, offset_flex: e.target.value === '' ? '' : parseFloat(e.target.value)})}
                    placeholder="Sin asignar"
                  />
                </div>
              </div>

              <h4>Comisiones Tienda Nube</h4>
              <div className="form-row">
                <div className="form-group">
                  <label>Comisión Efectivo/Transferencia (%):</label>
                  <input
                    type="number"
                    step="0.1"
                    value={nuevaVersion.comision_tienda_nube}
                    onChange={e => setNuevaVersion({...nuevaVersion, comision_tienda_nube: parseFloat(e.target.value)})}
                  />
                </div>
                <div className="form-group">
                  <label>Comisión Tarjeta (%):</label>
                  <input
                    type="number"
                    step="0.1"
                    value={nuevaVersion.comision_tienda_nube_tarjeta}
                    onChange={e => setNuevaVersion({...nuevaVersion, comision_tienda_nube_tarjeta: parseFloat(e.target.value)})}
                  />
                </div>
              </div>
            </div>

            <div className="modal-actions">
              <button
                className="btn-secondary"
                onClick={() => setMostrarFormNuevaVersion(false)}
              >
                Cancelar
              </button>
              <button
                className="btn-tesla outline-subtle-primary"
                onClick={handleGuardarNuevaVersion}
                disabled={cargando}
              >
                {cargando ? 'Guardando...' : 'Guardar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Historial de Versiones */}
      <div className="versiones-historial">
        <h3>Historial de Versiones</h3>
        {versiones.map(version => (
          <div key={version.id} className="version-card">
            <div className="version-card-header">
              <div className="version-fechas">
                <span className="version-fecha-desde">
                  Desde: {new Date(version.fecha_desde).toLocaleDateString('es-AR')}
                </span>
                <span className="version-fecha-hasta">
                  Hasta: {version.fecha_hasta ? new Date(version.fecha_hasta).toLocaleDateString('es-AR') : <strong>Vigente</strong>}
                </span>
              </div>
              {versiones.length > 1 && (
                <button
                  className="btn-tesla outline-subtle-danger sm"
                  onClick={() => handleEliminarVersion(version.id)}
                  disabled={cargando}
                >
                  Eliminar
                </button>
              )}
            </div>
            <div className="version-card-body">
              <table className="version-detail-table">
                <thead>
                  <tr>
                    <th></th>
                    <th>Tier 1</th>
                    <th>Tier 2</th>
                    <th>Tier 3 (envío gratis)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="version-row-label">Monto</td>
                    <td>${version.monto_tier1?.toLocaleString('es-AR')}</td>
                    <td>${version.monto_tier2?.toLocaleString('es-AR')}</td>
                    <td>${version.monto_tier3?.toLocaleString('es-AR')}</td>
                  </tr>
                  <tr>
                    <td className="version-row-label">Comisión</td>
                    <td>${version.comision_tier1?.toLocaleString('es-AR')}</td>
                    <td>${version.comision_tier2?.toLocaleString('es-AR')}</td>
                    <td>${version.comision_tier3?.toLocaleString('es-AR')}</td>
                  </tr>
                </tbody>
              </table>
              <div className="version-params">
                <div className="version-param">
                  <span className="version-param-label">Varios</span>
                  <span className="version-param-value">{version.varios_porcentaje}%</span>
                </div>
                <div className="version-param">
                  <span className="version-param-label">Markup Cuotas</span>
                  <span className="version-param-value">{version.markup_adicional_cuotas}%</span>
                </div>
                <div className="version-param">
                  <span className="version-param-label">Grupo Comisión</span>
                  <span className="version-param-value">{version.grupo_comision_default}</span>
                </div>
                <div className="version-param">
                  <span className="version-param-label">Offset Flex</span>
                  <span className="version-param-value">{version.offset_flex != null ? `$${Number(version.offset_flex).toLocaleString('es-AR')}` : '—'}</span>
                </div>
                <div className="version-param">
                  <span className="version-param-label">TN Efectivo/Transf.</span>
                  <span className="version-param-value">{version.comision_tienda_nube || 1.0}%</span>
                </div>
                <div className="version-param">
                  <span className="version-param-label">TN Tarjeta</span>
                  <span className="version-param-value">{version.comision_tienda_nube_tarjeta || 3.0}%</span>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

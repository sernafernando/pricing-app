import { useState, useEffect } from 'react';
import api from '../services/api';
import { toLocalDateString } from '../utils/dateUtils';
import './PanelComisiones.css';
import { useModalClickOutside } from '../hooks/useModalClickOutside';

export default function PanelComisiones() {
  const modalNuevaVersion = useModalClickOutside(() => setMostrarFormNuevaVersion(false));
  const modalDetalleVersion = useModalClickOutside(() => setMostrarDetalleVersion(false));
  const [versionActual, setVersionActual] = useState(null);
  const [comisionesCalculadas, setComisionesCalculadas] = useState([]);
  const [versiones, setVersiones] = useState([]);
  const [mostrarFormNuevaVersion, setMostrarFormNuevaVersion] = useState(false);
  const [versionSeleccionada, setVersionSeleccionada] = useState(null);
  const [mostrarDetalleVersion, setMostrarDetalleVersion] = useState(false);
  const [cargando, setCargando] = useState(false);

  // Estado para nueva versión
  const [nuevaVersion, setNuevaVersion] = useState({
    nombre: '',
    descripcion: '',
    fecha_desde: toLocalDateString(),
    comisiones_base: Array(13).fill(null).map((_, i) => ({
      grupo_id: i + 1,
      comision_base: 0
    })),
    adicionales_cuota: [
      { cuotas: 3, adicional: 0 },
      { cuotas: 6, adicional: 0 },
      { cuotas: 9, adicional: 0 },
      { cuotas: 12, adicional: 0 }
    ]
  });

  useEffect(() => {
    cargarDatos();
  }, []);

  const cargarDatos = async () => {
    setCargando(true);
    try {
      // Cargar versión vigente
      const vigente = await api.get('/comisiones/vigente');
      setVersionActual(vigente.data);

      // Cargar comisiones calculadas
      const calculadas = await api.get('/comisiones/calculadas');
      setComisionesCalculadas(calculadas.data);

      // Cargar todas las versiones
      const todasVersiones = await api.get('/comisiones/versiones');
      setVersiones(todasVersiones.data);

    } catch (error) {
      console.error('Error cargando comisiones:', error);
      alert('Error al cargar comisiones');
    } finally {
      setCargando(false);
    }
  };

  const copiarDatosActuales = () => {
    if (!versionActual) return;

    setNuevaVersion({
      nombre: `Actualización ${new Date().toLocaleDateString('es-AR')}`,
      descripcion: '',
      fecha_desde: toLocalDateString(),
      comisiones_base: versionActual.comisiones_base.map(cb => ({
        grupo_id: cb.grupo_id,
        comision_base: cb.comision_base
      })),
      adicionales_cuota: versionActual.adicionales_cuota.map(ac => ({
        cuotas: ac.cuotas,
        adicional: ac.adicional
      }))
    });
  };

  const actualizarComisionBase = (grupoId, valor) => {
    setNuevaVersion(prev => ({
      ...prev,
      comisiones_base: prev.comisiones_base.map(cb =>
        cb.grupo_id === grupoId ? { ...cb, comision_base: parseFloat(valor) || 0 } : cb
      )
    }));
  };

  const actualizarAdicional = (cuotas, valor) => {
    setNuevaVersion(prev => ({
      ...prev,
      adicionales_cuota: prev.adicionales_cuota.map(ac =>
        ac.cuotas === cuotas ? { ...ac, adicional: parseFloat(valor) || 0 } : ac
      )
    }));
  };

  const calcularComisionCuotas = (grupoId, cuotas) => {
    const base = nuevaVersion.comisiones_base.find(cb => cb.grupo_id === grupoId)?.comision_base || 0;
    const adicional = nuevaVersion.adicionales_cuota.find(ac => ac.cuotas === cuotas)?.adicional || 0;
    return (base + adicional).toFixed(2);
  };

  const verDetalleVersion = async (version) => {
    setVersionSeleccionada(version);
    setMostrarDetalleVersion(true);
  };

  const calcularMatrizVersion = (version) => {
    const adicionales = {};
    version.adicionales_cuota.forEach(ac => {
      adicionales[ac.cuotas] = ac.adicional;
    });

    return version.comisiones_base.map(cb => ({
      grupo_id: cb.grupo_id,
      lista_4: cb.comision_base,
      lista_3_cuotas: cb.comision_base + (adicionales[3] || 0),
      lista_6_cuotas: cb.comision_base + (adicionales[6] || 0),
      lista_9_cuotas: cb.comision_base + (adicionales[9] || 0),
      lista_12_cuotas: cb.comision_base + (adicionales[12] || 0)
    }));
  };

  const editarVersion = (version) => {
    // Cargar datos de la versión en el formulario
    setNuevaVersion({
      nombre: version.nombre,
      descripcion: version.descripcion || '',
      fecha_desde: version.fecha_desde,
      comisiones_base: version.comisiones_base.map(cb => ({
        grupo_id: cb.grupo_id,
        comision_base: cb.comision_base
      })),
      adicionales_cuota: version.adicionales_cuota.map(ac => ({
        cuotas: ac.cuotas,
        adicional: ac.adicional
      }))
    });
    setMostrarDetalleVersion(false);
    setMostrarFormNuevaVersion(true);
    // Guardar el ID para actualizar en lugar de crear
    setVersionSeleccionada(version);
  };

  const eliminarVersion = async (version) => {
    const motivo = prompt('Ingrese el motivo de la eliminación (mínimo 10 caracteres):');

    if (!motivo || motivo.trim().length < 10) {
      alert('El motivo debe tener al menos 10 caracteres');
      return;
    }

    if (!confirm(`¿Confirmar eliminación de la versión "${version.nombre}"?\n\nEsto reactivará la versión anterior.`)) {
      return;
    }

    setCargando(true);
    try {
      await api.delete(`/comisiones/version/${version.id}`, {
        data: { motivo: motivo.trim() }
      });

      alert('✅ Versión eliminada correctamente');
      setMostrarDetalleVersion(false);
      cargarDatos();
    } catch (error) {
      console.error('Error al eliminar versión:', error);
      alert('❌ Error: ' + (error.response?.data?.detail || error.message));
    } finally {
      setCargando(false);
    }
  };

  const guardarNuevaVersion = async () => {
    if (!nuevaVersion.nombre.trim()) {
      alert('Debe ingresar un nombre para la nueva versión');
      return;
    }

    const esEdicion = versionSeleccionada && versionSeleccionada.activo;

    if (!esEdicion && !confirm('¿Confirmar creación de nueva versión de comisiones?\n\nEsto cerrará la versión actual y activará la nueva.')) {
      return;
    }

    if (esEdicion && !confirm('¿Confirmar actualización de la versión actual?')) {
      return;
    }

    setCargando(true);
    try {
      if (esEdicion) {
        // Actualizar versión existente
        await api.patch(`/comisiones/version/${versionSeleccionada.id}`, nuevaVersion);
        alert('✅ Versión actualizada exitosamente');
      } else {
        // Crear nueva versión
        await api.post('/comisiones/nueva-version', nuevaVersion);
        alert('✅ Nueva versión de comisiones creada exitosamente');
      }

      setMostrarFormNuevaVersion(false);
      setVersionSeleccionada(null);
      cargarDatos();
    } catch (error) {
      console.error('Error al guardar versión:', error);
      alert('❌ Error: ' + (error.response?.data?.detail || error.message));
    } finally {
      setCargando(false);
    }
  };

  if (cargando && !versionActual) {
    return <div className="panel-comisiones">Cargando...</div>;
  }

  return (
    <div className="panel-comisiones">
      <div className="panel-header">
        <h2>Gestión de Comisiones</h2>
        <button
          onClick={() => {
            copiarDatosActuales();
            setMostrarFormNuevaVersion(true);
          }}
          className="btn-tesla outline-subtle-primary"
          disabled={cargando}
        >
          ➕ Nueva Versión
        </button>
      </div>

      {versionActual && (
        <div className="version-actual">
          <h3>Versión Actual: {versionActual.nombre}</h3>
          <div className="version-info">
            <span>Vigencia: {new Date(versionActual.fecha_desde).toLocaleDateString('es-AR')} - {versionActual.fecha_hasta ? new Date(versionActual.fecha_hasta).toLocaleDateString('es-AR') : 'Actualidad'}</span>
            {versionActual.descripcion && <span>{versionActual.descripcion}</span>}
          </div>
        </div>
      )}

      {comisionesCalculadas.length > 0 && (
        <div className="tabla-comisiones-wrapper">
          <h3>Matriz de Comisiones Vigentes</h3>
          <table className="tabla-comisiones">
            <thead>
              <tr>
                <th>Grupo</th>
                <th>Lista 4 (Base)</th>
                <th>3 Cuotas</th>
                <th>6 Cuotas</th>
                <th>9 Cuotas</th>
                <th>12 Cuotas</th>
              </tr>
            </thead>
            <tbody>
              {comisionesCalculadas.map(row => (
                <tr key={row.grupo_id}>
                  <td className="grupo-cell">Grupo {row.grupo_id}</td>
                  <td>{row.lista_4.toFixed(2)}%</td>
                  <td>{row.lista_3_cuotas.toFixed(2)}%</td>
                  <td>{row.lista_6_cuotas.toFixed(2)}%</td>
                  <td>{row.lista_9_cuotas.toFixed(2)}%</td>
                  <td>{row.lista_12_cuotas.toFixed(2)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {mostrarFormNuevaVersion && (
        <div
          ref={modalNuevaVersion.overlayRef}
          className="modal-overlay"
          onMouseDown={modalNuevaVersion.handleOverlayMouseDown}
          onClick={modalNuevaVersion.handleOverlayClick}
        >
          <div className="modal-comisiones" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{versionSeleccionada && versionSeleccionada.activo ? 'Editar Versión de Comisiones' : 'Nueva Versión de Comisiones'}</h2>
              <button onClick={() => setMostrarFormNuevaVersion(false)} className="close-btn">✕</button>
            </div>

            <div className="modal-body">
              <div className="form-group">
                <label>Nombre de la versión</label>
                <input
                  type="text"
                  value={nuevaVersion.nombre}
                  onChange={(e) => setNuevaVersion({...nuevaVersion, nombre: e.target.value})}
                  placeholder="Ej: Actualización Marzo 2024"
                />
              </div>

              <div className="form-group">
                <label>Descripción (opcional)</label>
                <textarea
                  value={nuevaVersion.descripcion}
                  onChange={(e) => setNuevaVersion({...nuevaVersion, descripcion: e.target.value})}
                  placeholder="Descripción de los cambios..."
                  rows={3}
                />
              </div>

              <div className="form-group">
                <label>Fecha desde</label>
                <input
                  type="date"
                  value={nuevaVersion.fecha_desde}
                  onChange={(e) => setNuevaVersion({...nuevaVersion, fecha_desde: e.target.value})}
                />
              </div>

              <div className="adicionales-section">
                <h4>Adicionales por Cuota (se suman a la base)</h4>
                <div className="adicionales-grid">
                  {nuevaVersion.adicionales_cuota.map(ac => (
                    <div key={ac.cuotas} className="adicional-item">
                      <label>{ac.cuotas} Cuotas</label>
                      <input
                        type="number"
                        step="0.1"
                        value={ac.adicional}
                        onChange={(e) => actualizarAdicional(ac.cuotas, e.target.value)}
                      />
                      <span>%</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="tabla-edicion-wrapper">
                <h4>Comisiones Base por Grupo (Lista 4)</h4>
                <table className="tabla-edicion">
                  <thead>
                    <tr>
                      <th>Grupo</th>
                      <th>Base</th>
                      <th>3 Cuotas</th>
                      <th>6 Cuotas</th>
                      <th>9 Cuotas</th>
                      <th>12 Cuotas</th>
                    </tr>
                  </thead>
                  <tbody>
                    {nuevaVersion.comisiones_base.map(cb => (
                      <tr key={cb.grupo_id}>
                        <td className="grupo-cell">Grupo {cb.grupo_id}</td>
                        <td>
                          <input
                            type="number"
                            step="0.01"
                            value={cb.comision_base}
                            onChange={(e) => actualizarComisionBase(cb.grupo_id, e.target.value)}
                            className="input-comision"
                          />
                          <span>%</span>
                        </td>
                        <td className="calc-cell">{calcularComisionCuotas(cb.grupo_id, 3)}%</td>
                        <td className="calc-cell">{calcularComisionCuotas(cb.grupo_id, 6)}%</td>
                        <td className="calc-cell">{calcularComisionCuotas(cb.grupo_id, 9)}%</td>
                        <td className="calc-cell">{calcularComisionCuotas(cb.grupo_id, 12)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="modal-footer">
              <button onClick={() => setMostrarFormNuevaVersion(false)} className="btn-secondary">
                Cancelar
              </button>
              <button onClick={guardarNuevaVersion} className="btn-tesla outline-subtle-primary" disabled={cargando}>
                {cargando ? 'Guardando...' : '✓ Guardar Nueva Versión'}
              </button>
            </div>
          </div>
        </div>
      )}

      {versiones.length > 0 && (
        <div className="historial-versiones">
          <h3>Historial de Versiones</h3>
          <div className="versiones-list">
            {versiones.map(v => (
              <div
                key={v.id}
                className={`version-item ${v.activo ? 'activa' : ''}`}
                onClick={() => verDetalleVersion(v)}
              >
                <div className="version-nombre">{v.nombre}</div>
                <div className="version-fechas">
                  {new Date(v.fecha_desde).toLocaleDateString('es-AR')} -
                  {v.fecha_hasta ? new Date(v.fecha_hasta).toLocaleDateString('es-AR') : 'Actualidad'}
                </div>
                {v.descripcion && <div className="version-desc">{v.descripcion}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Modal para ver detalle de versión histórica */}
      {mostrarDetalleVersion && versionSeleccionada && (
        <div
          ref={modalDetalleVersion.overlayRef}
          className="modal-overlay"
          onMouseDown={modalDetalleVersion.handleOverlayMouseDown}
          onClick={modalDetalleVersion.handleOverlayClick}
        >
          <div className="modal-comisiones" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{versionSeleccionada.nombre}</h2>
              <button onClick={() => setMostrarDetalleVersion(false)} className="close-btn">✕</button>
            </div>

            <div className="modal-body">
              <div className="version-info" style={{ marginBottom: '24px' }}>
                <div><strong>Vigencia:</strong> {new Date(versionSeleccionada.fecha_desde).toLocaleDateString('es-AR')} - {versionSeleccionada.fecha_hasta ? new Date(versionSeleccionada.fecha_hasta).toLocaleDateString('es-AR') : 'Actualidad'}</div>
                {versionSeleccionada.descripcion && <div><strong>Descripción:</strong> {versionSeleccionada.descripcion}</div>}
              </div>

              <div className="adicionales-section">
                <h4>Adicionales por Cuota</h4>
                <div className="adicionales-grid">
                  {versionSeleccionada.adicionales_cuota.map(ac => (
                    <div key={ac.cuotas} className="adicional-readonly">
                      <strong>{ac.cuotas} Cuotas:</strong> <span>{ac.adicional}%</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="tabla-comisiones-wrapper">
                <h4>Matriz de Comisiones</h4>
                <table className="tabla-comisiones">
                  <thead>
                    <tr>
                      <th>Grupo</th>
                      <th>Lista 4 (Base)</th>
                      <th>3 Cuotas</th>
                      <th>6 Cuotas</th>
                      <th>9 Cuotas</th>
                      <th>12 Cuotas</th>
                    </tr>
                  </thead>
                  <tbody>
                    {calcularMatrizVersion(versionSeleccionada).map(row => (
                      <tr key={row.grupo_id}>
                        <td className="grupo-cell">Grupo {row.grupo_id}</td>
                        <td>{row.lista_4.toFixed(2)}%</td>
                        <td>{row.lista_3_cuotas.toFixed(2)}%</td>
                        <td>{row.lista_6_cuotas.toFixed(2)}%</td>
                        <td>{row.lista_9_cuotas.toFixed(2)}%</td>
                        <td>{row.lista_12_cuotas.toFixed(2)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="modal-footer">
              {versionSeleccionada.activo && (
                <>
                  <button
                    onClick={() => editarVersion(versionSeleccionada)}
                    className="btn-tesla outline-subtle-primary"
                    disabled={cargando}
                  >
                    ✏️ Editar
                  </button>
                  <button
                    onClick={() => eliminarVersion(versionSeleccionada)}
                    className="btn-tesla outline-subtle-danger"
                    disabled={cargando}
                  >
                    🗑️ Eliminar
                  </button>
                </>
              )}
              <button onClick={() => setMostrarDetalleVersion(false)} className="btn-secondary">
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

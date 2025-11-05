import { useState, useEffect } from 'react';
import axios from 'axios';
import './PanelComisiones.css';

export default function PanelComisiones() {
  const [versionActual, setVersionActual] = useState(null);
  const [comisionesCalculadas, setComisionesCalculadas] = useState([]);
  const [versiones, setVersiones] = useState([]);
  const [mostrarFormNuevaVersion, setMostrarFormNuevaVersion] = useState(false);
  const [cargando, setCargando] = useState(false);

  // Estado para nueva versión
  const [nuevaVersion, setNuevaVersion] = useState({
    nombre: '',
    descripcion: '',
    fecha_desde: new Date().toISOString().split('T')[0],
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
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      // Cargar versión vigente
      const vigente = await axios.get(
        'https://pricing.gaussonline.com.ar/api/comisiones/vigente',
        { headers }
      );
      setVersionActual(vigente.data);

      // Cargar comisiones calculadas
      const calculadas = await axios.get(
        'https://pricing.gaussonline.com.ar/api/comisiones/calculadas',
        { headers }
      );
      setComisionesCalculadas(calculadas.data);

      // Cargar todas las versiones
      const todasVersiones = await axios.get(
        'https://pricing.gaussonline.com.ar/api/comisiones/versiones',
        { headers }
      );
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
      fecha_desde: new Date().toISOString().split('T')[0],
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

  const guardarNuevaVersion = async () => {
    if (!nuevaVersion.nombre.trim()) {
      alert('Debe ingresar un nombre para la nueva versión');
      return;
    }

    if (!confirm('¿Confirmar creación de nueva versión de comisiones?\n\nEsto cerrará la versión actual y activará la nueva.')) {
      return;
    }

    setCargando(true);
    try {
      const token = localStorage.getItem('token');
      await axios.post(
        'https://pricing.gaussonline.com.ar/api/comisiones/nueva-version',
        nuevaVersion,
        { headers: { Authorization: `Bearer ${token}` } }
      );

      alert('✅ Nueva versión de comisiones creada exitosamente');
      setMostrarFormNuevaVersion(false);
      cargarDatos();
    } catch (error) {
      console.error('Error al crear versión:', error);
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
          className="btn-primary"
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
        <div className="modal-overlay" onClick={() => setMostrarFormNuevaVersion(false)}>
          <div className="modal-comisiones" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Nueva Versión de Comisiones</h2>
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
              <button onClick={guardarNuevaVersion} className="btn-primary" disabled={cargando}>
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
              <div key={v.id} className={`version-item ${v.activo ? 'activa' : ''}`}>
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
    </div>
  );
}

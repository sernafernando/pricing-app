import { useState, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, Polygon, Popup } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import '@geoman-io/leaflet-geoman-free';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import styles from './GestionZonas.module.css';
import api from '../../services/api';

export default function GestionZonas({ zonas, onZonaCreada }) {
  const [nombre, setNombre] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [color, setColor] = useState('#3388ff');
  const [poligonoTemporal, setPoligonoTemporal] = useState(null);
  const [guardando, setGuardando] = useState(false);
  const [autoGenerando, setAutoGenerando] = useState(false);
  const [motoqueros, setMotoqueros] = useState([]);
  const mapRef = useRef(null);
  
  // Cargar motoqueros activos
  useEffect(() => {
    const cargarMotoqueros = async () => {
      try {
        const response = await api.get('/turbo/motoqueros');
        setMotoqueros(response.data);
      } catch {
        // Error silencioso: si falla, el botón auto-generar quedará deshabilitado
      }
    };
    
    cargarMotoqueros();
  }, []);
  
  // Inicializar Leaflet.Geoman cuando el mapa esté listo
  useEffect(() => {
    if (!mapRef.current) return;
    
    const map = mapRef.current;
    
    // Agregar controles de Geoman
    map.pm.addControls({
      position: 'topright',
      drawMarker: false,
      drawCircle: false,
      drawCircleMarker: false,
      drawPolyline: false,
      drawRectangle: false,
      drawPolygon: true,
      editMode: true,
      dragMode: false,
      cutPolygon: false,
      removalMode: true,
    });
    
    // Configurar opciones de dibujo
    map.pm.setPathOptions({
      color: color,
      fillColor: color,
      fillOpacity: 0.3,
      weight: 3,
    });
    
    // Event handler cuando se crea un polígono
    map.on('pm:create', (e) => {
      const layer = e.layer;
      
      // Convertir a GeoJSON
      const coords = layer.getLatLngs()[0].map(latlng => [latlng.lng, latlng.lat]);
      const geojson = {
        type: 'Polygon',
        coordinates: [[...coords, coords[0]]] // Cerrar el polígono
      };
      
      setPoligonoTemporal(geojson);
      
      // Guardar referencia para poder eliminar después
      layer._zonaTemp = true;
    });
    
    // Event handler cuando se edita
    map.on('pm:edit', (e) => {
      const layer = e.layer;
      const coords = layer.getLatLngs()[0].map(latlng => [latlng.lng, latlng.lat]);
      const geojson = {
        type: 'Polygon',
        coordinates: [[...coords, coords[0]]]
      };
      setPoligonoTemporal(geojson);
    });
    
    // Event handler cuando se elimina
    map.on('pm:remove', (e) => {
      if (e.layer._zonaTemp) {
        setPoligonoTemporal(null);
      }
    });
    
    return () => {
      map.off('pm:create');
      map.off('pm:edit');
      map.off('pm:remove');
      map.pm.removeControls();
    };
  }, [color]);
  
  // Actualizar color cuando cambia
  useEffect(() => {
    if (mapRef.current) {
      mapRef.current.pm.setPathOptions({
        color: color,
        fillColor: color,
        fillOpacity: 0.3,
        weight: 3,
      });
    }
  }, [color]);
  
  const handleGuardarZona = async () => {
    if (!nombre.trim()) {
      alert('El nombre es obligatorio');
      return;
    }
    
    if (!poligonoTemporal) {
      alert('Dibujá un polígono en el mapa');
      return;
    }
    
    setGuardando(true);
    try {
      const response = await api.post(
        '/turbo/zonas',
        {
          nombre,
          descripcion,
          poligono: poligonoTemporal,
          color,
          activa: true
        }
      );
      
      alert('✅ Zona creada correctamente');
      setNombre('');
      setDescripcion('');
      setPoligonoTemporal(null);
      
      // Limpiar polígono temporal del mapa
      if (mapRef.current) {
        mapRef.current.eachLayer((layer) => {
          if (layer._zonaTemp) {
            mapRef.current.removeLayer(layer);
          }
        });
      }
      
      if (onZonaCreada) {
        onZonaCreada(response.data);
      }
    } catch (error) {
      alert(error.response?.data?.detail || 'Error al crear zona');
    } finally {
      setGuardando(false);
    }
  };
  
  const handleToggleZona = async (zona) => {
    const accion = zona.activa ? 'desactivar' : 'activar';
    if (!confirm(`¿${accion.charAt(0).toUpperCase() + accion.slice(1)} la zona "${zona.nombre}"?`)) return;
    
    try {
      const response = await api.put(`/turbo/zonas/${zona.id}/toggle`);
      
      alert(`✅ Zona ${zona.activa ? 'desactivada' : 'activada'} correctamente`);
      
      // Actualizar zona en la lista (simulando recarga)
      if (onZonaCreada) {
        onZonaCreada(response.data);
      }
    } catch (error) {
      alert(error.response?.data?.detail || `Error al ${accion} zona`);
    }
  };
  
  const handleZoomToZona = (zona) => {
    if (!mapRef.current || !zona.poligono?.coordinates?.[0]) return;
    
    // Convertir coordenadas de GeoJSON [lng, lat] a Leaflet [lat, lng]
    const coords = zona.poligono.coordinates[0].map(c => [c[1], c[0]]);
    
    // Crear bounds y hacer zoom
    const bounds = L.latLngBounds(coords);
    mapRef.current.fitBounds(bounds, { 
      padding: [50, 50],
      maxZoom: 14
    });
  };
  
  const handleAutoGenerar = async () => {
    const motoquerosActivos = motoqueros.filter(m => m.activo);
    const cantidadZonas = motoquerosActivos.length;
    
    if (cantidadZonas === 0) {
      alert('⚠️ No hay motoqueros activos. Creá al menos 1 motoquero primero.');
      return;
    }
    
    if (cantidadZonas > 6) {
      alert('⚠️ Máximo 6 zonas permitidas. Tenés ' + cantidadZonas + ' motoqueros activos.');
      return;
    }
    
    const confirmacion = confirm(
      `🤖 ¿Generar ${cantidadZonas} zonas automáticamente?\n\n` +
      `Algoritmo: K-Means Clustering\n` +
      `• Se agruparán los envíos Turbo pendientes\n` +
      `• Distribución equitativa por zona\n` +
      `• Se desactivarán zonas auto-generadas previas\n\n` +
      `Requisito: Al menos 70% de envíos deben estar geocodificados`
    );
    
    if (!confirmacion) return;
    
    setAutoGenerando(true);
    try {
      const response = await api.post('/turbo/zonas/auto-generar', null, {
        params: {
          cantidad_motoqueros: cantidadZonas,
          eliminar_anteriores: true
        }
      });
      
      const zonasCreadas = response.data;
      
      alert(
        `✅ ${zonasCreadas.length} zonas generadas correctamente\n\n` +
        zonasCreadas.map((z, i) => `${i + 1}. ${z.nombre} (${z.descripcion})`).join('\n')
      );
      
      // Notificar al padre para actualizar lista
      if (onZonaCreada) {
        zonasCreadas.forEach(zona => onZonaCreada(zona));
      }
      
      // Limpiar formulario manual (por las dudas)
      setNombre('');
      setDescripcion('');
      setPoligonoTemporal(null);
      
    } catch (error) {
      const errorMsg = error.response?.data?.detail || 'Error al generar zonas';
      alert('❌ ' + errorMsg);
    } finally {
      setAutoGenerando(false);
    }
  };
  
  return (
    <div className={styles.container}>
      <div className={styles.panel}>
        <div className={styles.formSection}>
        <div className={styles.header}>
          <h3>Crear Nueva Zona</h3>
          <button 
            className={`${styles.btn} ${styles.btnAuto}`}
            onClick={handleAutoGenerar}
            disabled={autoGenerando || motoqueros.filter(m => m.activo).length === 0}
            title={
              motoqueros.filter(m => m.activo).length === 0 
                ? 'No hay motoqueros activos' 
                : `Generar ${motoqueros.filter(m => m.activo).length} zonas automáticamente`
            }
          >
            {autoGenerando ? '⏳ Generando...' : `🤖 Auto-generar ${motoqueros.filter(m => m.activo).length} Zonas`}
          </button>
        </div>
        
        <div className={styles.form}>
          <div className={styles.field}>
            <label>Nombre *</label>
            <input 
              type="text"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              placeholder="Ej: Zona Centro"
              className={styles.input}
            />
          </div>
          
          <div className={styles.field}>
            <label>Descripción</label>
            <textarea 
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              placeholder="Opcional"
              className={styles.textarea}
              rows={2}
            />
          </div>
          
          <div className={styles.field}>
            <label>Color</label>
            <input 
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              className={styles.colorPicker}
            />
          </div>
          
          {poligonoTemporal && (
            <div className={styles.success}>
              ✅ Polígono dibujado ({poligonoTemporal.coordinates[0].length - 1} puntos)
            </div>
          )}
          
          <button 
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleGuardarZona}
            disabled={guardando || !nombre || !poligonoTemporal}
          >
            {guardando ? '💾 Guardando...' : '💾 Guardar Zona'}
          </button>
        </div>
        
        <div className={styles.instrucciones}>
          <p><strong>📍 Cómo dibujar una zona:</strong></p>
          <ol>
            <li>Hacé click en el botón <strong>🔷 Draw Polygon</strong> (arriba a la derecha del mapa)</li>
            <li>Hacé click en el mapa para agregar cada punto del polígono</li>
            <li>Agregá todos los puntos que necesites (mínimo 3, máximo ilimitado)</li>
            <li><strong style={{color: 'var(--brand-primary)'}}>Hacé click en el ÚLTIMO punto nuevamente para finalizar</strong></li>
            <li>Completá el formulario y guardá</li>
          </ol>
          <p style={{ marginTop: '0.5rem', fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>
            💡 <strong>Tip:</strong> Leaflet.Geoman permite polígonos de cualquier cantidad de puntos. Para editar, usá el botón ✏️ Edit.
          </p>
        </div>
        </div>
        
        {/* LISTA DE ZONAS */}
        <div className={styles.zonasSection}>
          <h3>Zonas Creadas ({zonas.length})</h3>
          
          {zonas.length === 0 ? (
            <div className={styles.emptyZonas}>
              <p>📍 No hay zonas creadas aún</p>
              <p style={{ fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                Dibujá tu primera zona en el mapa
              </p>
            </div>
          ) : (
            <div className={styles.zonasList}>
              {zonas.map(zona => (
                <div key={zona.id} className={styles.zonaCard}>
                  <div 
                    className={styles.zonaColor} 
                    style={{ backgroundColor: zona.color || '#3388ff' }}
                  />
                  <div className={styles.zonaInfo}>
                    <h4>{zona.nombre}</h4>
                    {zona.descripcion && <p>{zona.descripcion}</p>}
                    <div className={styles.zonaMeta}>
                      <span className={styles.zonaPoints}>
                        {zona.poligono?.coordinates?.[0]?.length - 1 || 0} puntos
                      </span>
                      {zona.activa ? (
                        <span className={styles.zonaStatus} style={{ color: '#22c55e' }}>● Activa</span>
                      ) : (
                        <span className={styles.zonaStatus} style={{ color: '#ef4444' }}>● Inactiva</span>
                      )}
                    </div>
                  </div>
                  <div className={styles.zonaActions}>
                    <button 
                      className={styles.btnIcon}
                      onClick={() => handleZoomToZona(zona)}
                      title="Ver en mapa"
                      aria-label="Ver zona en mapa"
                    >
                      🔍
                    </button>
                    <button 
                      className={`${styles.btnIcon} ${zona.activa ? styles.btnIconSuccess : styles.btnIconWarning}`}
                      onClick={() => handleToggleZona(zona)}
                      title={zona.activa ? 'Desactivar zona' : 'Activar zona'}
                      aria-label={zona.activa ? 'Desactivar zona' : 'Activar zona'}
                    >
                      {zona.activa ? '✅' : '❌'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      
      <div className={styles.mapWrapper}>
        <MapContainer
          center={[-34.6037, -58.3816]} // Buenos Aires
          zoom={12}
          style={{ height: '100%', width: '100%' }}
          whenReady={(mapInstance) => {
            mapRef.current = mapInstance.target;
          }}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          
          {/* Zonas existentes - SOLO ACTIVAS en el mapa */}
          {zonas.filter(z => z.activa).map(zona => {
            const coords = zona.poligono?.coordinates?.[0]?.map(c => [c[1], c[0]]) || [];
            
            return coords.length > 0 ? (
              <Polygon
                key={zona.id}
                positions={coords}
                pathOptions={{
                  color: zona.color || '#3388ff',
                  fillColor: zona.color || '#3388ff',
                  fillOpacity: 0.2
                }}
              >
                <Popup>
                  <div className={styles.popup}>
                    <h4>{zona.nombre}</h4>
                    {zona.descripcion && <p>{zona.descripcion}</p>}
                    <button 
                      className={zona.activa ? styles.btnDanger : styles.btnSuccess}
                      onClick={() => handleToggleZona(zona)}
                    >
                      {zona.activa ? '❌ Desactivar' : '✅ Activar'}
                    </button>
                  </div>
                </Popup>
              </Polygon>
            ) : null;
          })}
        </MapContainer>
      </div>
    </div>
  );
}

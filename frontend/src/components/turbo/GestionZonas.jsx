import { useState, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, Polygon, Popup } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import '@geoman-io/leaflet-geoman-free';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import styles from './GestionZonas.module.css';
import api from '../../services/api';

export default function GestionZonas({ zonas, onZonaCreada, onZonaEliminada }) {
  const [nombre, setNombre] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [color, setColor] = useState('#3388ff');
  const [poligonoTemporal, setPoligonoTemporal] = useState(null);
  const [guardando, setGuardando] = useState(false);
  const mapRef = useRef(null);
  
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
  
  const handleEliminarZona = async (zonaId) => {
    if (!confirm('¿Desactivar esta zona?')) return;
    
    try {
      await api.delete(`/turbo/zonas/${zonaId}`);
      
      alert('✅ Zona desactivada');
      
      if (onZonaEliminada) {
        onZonaEliminada(zonaId);
      }
    } catch (error) {
      alert(error.response?.data?.detail || 'Error al eliminar zona');
    }
  };
  
  return (
    <div className={styles.container}>
      <div className={styles.panel}>
        <div className={styles.formSection}>
        <h3>Crear Nueva Zona</h3>
        
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
          
          {/* Zonas existentes */}
          {zonas.map(zona => {
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
                      className={styles.btnDanger}
                      onClick={() => handleEliminarZona(zona.id)}
                    >
                      🗑️ Eliminar
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

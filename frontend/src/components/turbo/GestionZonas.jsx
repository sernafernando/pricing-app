import { useState, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, Polygon, Popup } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import 'leaflet-draw/dist/leaflet.draw.css';
import styles from './GestionZonas.module.css';
import api from '../../services/api';

// Importar leaflet-draw
import 'leaflet-draw';

export default function GestionZonas({ zonas, onZonaCreada, onZonaEliminada }) {
  const [nombre, setNombre] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [color, setColor] = useState('#3388ff');
  const [poligonoTemporal, setPoligonoTemporal] = useState(null);
  const [guardando, setGuardando] = useState(false);
  const mapRef = useRef(null);
  const drawnItemsRef = useRef(null);
  
  // Inicializar controles de dibujo cuando el mapa esté listo
  useEffect(() => {
    if (!mapRef.current) return;
    
    const map = mapRef.current;
    
    // FeatureGroup para las capas dibujadas
    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);
    drawnItemsRef.current = drawnItems;
    
    // Control de dibujo CON CONFIGURACIÓN CORRECTA
    const drawControl = new L.Control.Draw({
      position: 'topright',
      edit: {
        featureGroup: drawnItems,
        remove: true
      },
      draw: {
        polygon: {
          allowIntersection: false,
          drawError: {
            color: '#e74c3c',
            message: '<strong>Error:</strong> Las líneas no pueden cruzarse!'
          },
          shapeOptions: {
            color: color,
            weight: 3,
            fillOpacity: 0.3,
            fillColor: color
          },
          showArea: true,
          metric: true,
          // CLAVE: Estas opciones permiten polígonos de N puntos
          icon: new L.DivIcon({
            iconSize: new L.Point(8, 8),
            className: 'leaflet-div-icon leaflet-editing-icon'
          }),
          touchIcon: new L.DivIcon({
            iconSize: new L.Point(20, 20),
            className: 'leaflet-div-icon leaflet-editing-icon leaflet-touch-icon'
          }),
          guidelineDistance: 20,
          maxGuideLineLength: 4000,
          shapeOptions: {
            stroke: true,
            color: color,
            weight: 4,
            opacity: 0.5,
            fill: true,
            fillColor: color,
            fillOpacity: 0.2,
            clickable: true
          },
          metric: true,
          showArea: true,
          repeatMode: false
        },
        polyline: false,
        rectangle: false,
        circle: false,
        marker: false,
        circlemarker: false
      }
    });
    
    map.addControl(drawControl);
    
    // Event handlers
    map.on(L.Draw.Event.CREATED, (e) => {
      const layer = e.layer;
      
      // Limpiar capas anteriores
      drawnItems.clearLayers();
      drawnItems.addLayer(layer);
      
      // Convertir a GeoJSON
      const coords = layer.getLatLngs()[0].map(latlng => [latlng.lng, latlng.lat]);
      const geojson = {
        type: 'Polygon',
        coordinates: [[...coords, coords[0]]] // Cerrar el polígono
      };
      
      setPoligonoTemporal(geojson);
    });
    
    map.on(L.Draw.Event.EDITED, (e) => {
      const layers = e.layers;
      layers.eachLayer((layer) => {
        const coords = layer.getLatLngs()[0].map(latlng => [latlng.lng, latlng.lat]);
        const geojson = {
          type: 'Polygon',
          coordinates: [[...coords, coords[0]]]
        };
        setPoligonoTemporal(geojson);
      });
    });
    
    map.on(L.Draw.Event.DELETED, () => {
      setPoligonoTemporal(null);
    });
    
    return () => {
      map.off(L.Draw.Event.CREATED);
      map.off(L.Draw.Event.EDITED);
      map.off(L.Draw.Event.DELETED);
      map.removeControl(drawControl);
      map.removeLayer(drawnItems);
    };
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
      
      // Limpiar mapa
      if (drawnItemsRef.current) {
        drawnItemsRef.current.clearLayers();
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
            <li>Hacé click en el botón <strong>📐 Draw a polygon</strong> (arriba a la derecha del mapa)</li>
            <li>Hacé click en el mapa para agregar cada vértice del polígono</li>
            <li>Agregá todos los puntos que necesites (mínimo 3)</li>
            <li><strong style={{color: 'var(--brand-primary)'}}>IMPORTANTE: Hacé click en el PRIMER punto (el círculo inicial) para cerrar el polígono</strong></li>
            <li>Completá el formulario y hacé click en <strong>Guardar Zona</strong></li>
          </ol>
          <p style={{ marginTop: '0.5rem', fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>
            💡 <strong>Tip:</strong> Para cancelar, presioná ESC. Para editar una zona dibujada, usá el botón ✏️ Edit layers.
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

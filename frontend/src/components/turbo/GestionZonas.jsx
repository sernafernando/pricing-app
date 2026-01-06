import { useState } from 'react';
import { MapContainer, TileLayer, FeatureGroup } from 'react-leaflet';
import { EditControl } from 'react-leaflet-draw';
import 'leaflet/dist/leaflet.css';
import 'leaflet-draw/dist/leaflet.draw.css';
import styles from './GestionZonas.module.css';
import api from '../../services/api';

export default function GestionZonas({ zonas, onZonaCreada, onZonaEliminada }) {
  const [nombre, setNombre] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [color, setColor] = useState('#3388ff');
  const [poligonoTemporal, setPoligonoTemporal] = useState(null);
  const [guardando, setGuardando] = useState(false);
  
  const handleCrearPoligono = (e) => {
    const { layerType, layer } = e;
    
    if (layerType === 'polygon') {
      const coords = layer.getLatLngs()[0].map(latlng => [latlng.lng, latlng.lat]);
      
      // GeoJSON format: [[[lng, lat], [lng, lat], ...]]
      const geojson = {
        type: 'Polygon',
        coordinates: [[...coords, coords[0]]] // Cerrar el polígono
      };
      
      setPoligonoTemporal(geojson);
    }
  };
  
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
      {/* MAPA CON DRAWING TOOLS */}
      <div className={styles.mapaSection}>
        <h3 className={styles.seccionTitulo}>Dibujar Nueva Zona</h3>
        <div className={styles.mapaContainer}>
          <MapContainer
            center={[-34.6037, -58.3816]}
            zoom={12}
            className={styles.mapa}
          >
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution='&copy; OpenStreetMap'
            />
            
            <FeatureGroup>
              <EditControl
                position="topright"
                onCreated={handleCrearPoligono}
                draw={{
                  rectangle: false,
                  circle: false,
                  circlemarker: false,
                  marker: false,
                  polyline: false,
                  polygon: {
                    allowIntersection: false,
                    shapeOptions: {
                      color: color,
                      fillOpacity: 0.3
                    }
                  }
                }}
              />
            </FeatureGroup>
          </MapContainer>
        </div>
        
        {poligonoTemporal && (
          <div className={styles.poligonoInfo}>
            ✅ Polígono dibujado ({poligonoTemporal.coordinates[0].length - 1} puntos)
          </div>
        )}
      </div>
      
      {/* FORMULARIO */}
      <div className={styles.formularioSection}>
        <h3 className={styles.seccionTitulo}>Datos de la Zona</h3>
        
        <div className={styles.campo}>
          <label className={styles.label}>Nombre *</label>
          <input
            type="text"
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            className={styles.input}
            placeholder="Ej: Zona Norte"
          />
        </div>
        
        <div className={styles.campo}>
          <label className={styles.label}>Descripción</label>
          <textarea
            value={descripcion}
            onChange={(e) => setDescripcion(e.target.value)}
            className={styles.textarea}
            placeholder="Descripción opcional"
            rows={3}
          />
        </div>
        
        <div className={styles.campo}>
          <label className={styles.label}>Color</label>
          <input
            type="color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            className={styles.colorPicker}
          />
        </div>
        
        <button
          className="btn-tesla primary"
          onClick={handleGuardarZona}
          disabled={guardando || !poligonoTemporal}
        >
          {guardando ? 'Guardando...' : '💾 Guardar Zona'}
        </button>
      </div>
      
      {/* LISTA DE ZONAS */}
      <div className={styles.listadoSection}>
        <h3 className={styles.seccionTitulo}>Zonas Existentes</h3>
        
        {zonas.length === 0 ? (
          <p className={styles.emptyMessage}>No hay zonas creadas</p>
        ) : (
          <div className={styles.zonasList}>
            {zonas.map(zona => (
              <div key={zona.id} className={styles.zonaCard}>
                <div 
                  className={styles.zonaColor} 
                  style={{ backgroundColor: zona.color }}
                />
                <div className={styles.zonaInfo}>
                  <h4>{zona.nombre}</h4>
                  {zona.descripcion && <p>{zona.descripcion}</p>}
                  <span className={styles.zonaStatus}>
                    {zona.activa ? '✅ Activa' : '❌ Inactiva'}
                  </span>
                </div>
                {zona.activa && (
                  <button
                    className="btn-tesla danger"
                    onClick={() => handleEliminarZona(zona.id)}
                  >
                    🗑️
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

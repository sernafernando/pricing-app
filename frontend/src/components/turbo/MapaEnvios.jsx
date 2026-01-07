import { useEffect, useState } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polygon, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import styles from './MapaEnvios.module.css';

// Fix para iconos de Leaflet que no cargan por default
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

// Iconos personalizados por estado
const iconoPendiente = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

const iconoAsignado = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-blue.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

const iconoEntregado = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

// Componente para ajustar bounds del mapa
function FitBounds({ positions }) {
  const map = useMap();
  
  useEffect(() => {
    if (positions && positions.length > 0) {
      const bounds = L.latLngBounds(positions);
      map.fitBounds(bounds, { padding: [50, 50] });
    }
  }, [positions, map]);
  
  return null;
}

export default function MapaEnvios({ 
  envios = [], 
  zonas = [], 
  onEnvioClick,
  onZonaClick
}) {
  const [posicionesValidas, setPosicionesValidas] = useState([]);
  
  // Filtrar envíos con coordenadas válidas
  useEffect(() => {
    const validas = envios
      .filter(e => e.latitud && e.longitud)
      .map(e => [e.latitud, e.longitud]);
    setPosicionesValidas(validas);
  }, [envios]);
  
  // Centro default: Buenos Aires
  const centroDefault = [-34.6037, -58.3816];
  
  const getIcono = (envio) => {
    // Verificar estado ML primero (delivered, shipped, cancelled)
    if (envio.mlstatus === 'delivered') {
      return iconoEntregado;
    } else if (envio.asignado) {
      // Asignado pero no entregado todavía
      return iconoAsignado;
    } else {
      // Pendiente sin asignar
      return iconoPendiente;
    }
  };
  
  return (
    <div className={styles.mapaContainer}>
      <MapContainer 
        center={centroDefault} 
        zoom={12} 
        className={styles.mapa}
        scrollWheelZoom={true}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        
        {/* Ajustar bounds si hay envíos con coordenadas */}
        {posicionesValidas.length > 0 && (
          <FitBounds positions={posicionesValidas} />
        )}
        
        {/* Renderizar zonas de reparto */}
        {zonas.map(zona => (
          <Polygon
            key={zona.id}
            positions={zona.poligono.coordinates[0].map(coord => [coord[1], coord[0]])}
            pathOptions={{
              color: zona.color || '#3388ff',
              fillColor: zona.color || '#3388ff',
              fillOpacity: 0.2,
              weight: 2
            }}
            eventHandlers={{
              click: () => onZonaClick && onZonaClick(zona)
            }}
          >
            <Popup>
              <div className={styles.popup}>
                <h4>{zona.nombre}</h4>
                <p>{zona.descripcion || 'Sin descripción'}</p>
              </div>
            </Popup>
          </Polygon>
        ))}
        
        {/* Renderizar markers de envíos */}
        {envios.map(envio => {
          if (!envio.latitud || !envio.longitud) return null;
          
          return (
            <Marker
              key={envio.mlshippingid}
              position={[envio.latitud, envio.longitud]}
              icon={getIcono(envio)}
              eventHandlers={{
                click: () => onEnvioClick && onEnvioClick(envio)
              }}
            >
              <Popup>
                <div className={styles.popup}>
                  <h4>Envío #{envio.mlshippingid}</h4>
                  <p><strong>Destinatario:</strong> {envio.mlreceiver_name}</p>
                  <p><strong>Dirección:</strong> {envio.direccion_completa}</p>
                  <p><strong>Estado:</strong> {envio.mlstatus}</p>
                  {envio.motoquero_nombre && (
                    <p><strong>Motoquero:</strong> {envio.motoquero_nombre}</p>
                  )}
                </div>
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>
      
      {/* Leyenda */}
      <div className={styles.leyenda}>
        <h4>Leyenda</h4>
        <div className={styles.leyendaItem}>
          <div className={`${styles.leyendaIcono} ${styles.iconoRojo}`} />
          <span>Pendiente</span>
        </div>
        <div className={styles.leyendaItem}>
          <div className={`${styles.leyendaIcono} ${styles.iconoAzul}`} />
          <span>Asignado</span>
        </div>
        <div className={styles.leyendaItem}>
          <div className={`${styles.leyendaIcono} ${styles.iconoVerde}`} />
          <span>Entregado</span>
        </div>
      </div>
      
      {/* Info de envíos sin geocoding */}
      {envios.length > 0 && posicionesValidas.length === 0 && (
        <div className={styles.sinCoordenadas}>
          ⚠️ No hay envíos con coordenadas geocodificadas
        </div>
      )}
      
      {envios.length > 0 && posicionesValidas.length < envios.length && posicionesValidas.length > 0 && (
        <div className={styles.sinCoordenadas}>
          ℹ️ {envios.length - posicionesValidas.length} de {envios.length} envíos sin geocoding
        </div>
      )}
    </div>
  );
}

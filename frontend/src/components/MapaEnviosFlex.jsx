import { useEffect, useState, useMemo } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { MapPin, AlertTriangle } from 'lucide-react';
import 'leaflet/dist/leaflet.css';
import styles from './MapaEnviosFlex.module.css';

// Fix iconos de Leaflet que no cargan por default
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

// ── SVG marker factory ──────────────────────────────────────────
const markerCache = new Map();

const createColoredIcon = (color) => {
  const key = color || '#6b7280';
  if (markerCache.has(key)) return markerCache.get(key);

  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="25" height="41" viewBox="0 0 25 41">
      <path d="M12.5 0C5.6 0 0 5.6 0 12.5C0 21.9 12.5 41 12.5 41S25 21.9 25 12.5C25 5.6 19.4 0 12.5 0z"
            fill="${key}" stroke="#fff" stroke-width="1.5"/>
      <circle cx="12.5" cy="12.5" r="5" fill="#fff"/>
    </svg>`;

  const icon = new L.Icon({
    iconUrl: `data:image/svg+xml;base64,${btoa(svg)}`,
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
  });

  markerCache.set(key, icon);
  return icon;
};

// ── FitBounds helper ────────────────────────────────────────────
const FitBounds = ({ positions }) => {
  const map = useMap();

  useEffect(() => {
    if (positions.length > 0) {
      const bounds = L.latLngBounds(positions);
      map.fitBounds(bounds, { padding: [50, 50] });
    }
  }, [positions, map]);

  return null;
};

// ── Status labels ───────────────────────────────────────────────
const ML_STATUS_LABELS = {
  ready_to_ship: 'Listo para enviar',
  shipped: 'Enviado',
  delivered: 'Entregado',
  cancelled: 'Cancelado',
  not_delivered: 'No entregado',
};

// ── Main Component ──────────────────────────────────────────────
export default function MapaEnviosFlex({ envios = [] }) {
  const [modoColor, setModoColor] = useState('logistica'); // 'logistica' | 'cordon'

  // Separar envíos con y sin coordenadas
  const { conCoords, sinCoords, posiciones } = useMemo(() => {
    const con = [];
    const sin = [];
    const pos = [];

    for (const e of envios) {
      if (e.latitud && e.longitud) {
        con.push(e);
        pos.push([e.latitud, e.longitud]);
      } else {
        sin.push(e);
      }
    }

    return { conCoords: con, sinCoords: sin, posiciones: pos };
  }, [envios]);

  // Leyenda dinámica según modo de color activo
  const leyendaItems = useMemo(() => {
    const items = new Map();

    for (const e of conCoords) {
      if (modoColor === 'logistica') {
        const key = e.logistica_nombre || 'Sin logística';
        if (!items.has(key)) {
          items.set(key, e.logistica_color || '#6b7280');
        }
      } else {
        const key = e.cordon || 'Sin cordón';
        if (!items.has(key)) {
          // Colores fijos por cordón
          const cordonColors = {
            'CABA': '#3b82f6',
            'Cordón 1': '#22c55e',
            'Cordón 2': '#f59e0b',
            'Cordón 3': '#ef4444',
            'Sin cordón': '#6b7280',
          };
          items.set(key, cordonColors[key] || '#6b7280');
        }
      }
    }

    return Array.from(items.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [conCoords, modoColor]);

  // Color de marker según modo
  const getColor = (envio) => {
    if (modoColor === 'logistica') {
      return envio.logistica_color || '#6b7280';
    }
    const cordonColors = {
      'CABA': '#3b82f6',
      'Cordón 1': '#22c55e',
      'Cordón 2': '#f59e0b',
      'Cordón 3': '#ef4444',
    };
    return cordonColors[envio.cordon] || '#6b7280';
  };

  // Centro default: Buenos Aires
  const centroDefault = [-34.6037, -58.3816];

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

        {posiciones.length > 0 && <FitBounds positions={posiciones} />}

        {conCoords.map((envio) => (
          <Marker
            key={envio.shipping_id}
            position={[envio.latitud, envio.longitud]}
            icon={createColoredIcon(getColor(envio))}
          >
            <Popup>
              <div className={styles.popup}>
                <h4>Envío #{envio.shipping_id}</h4>
                <p><strong>Destinatario:</strong> {envio.mlreceiver_name}</p>
                <p><strong>Dirección:</strong> {envio.direccion_completa}</p>
                <p><strong>CP:</strong> {envio.mlzip_code}</p>
                <p><strong>Cordón:</strong> {envio.cordon || 'Sin asignar'}</p>
                <p><strong>Logística:</strong> {envio.logistica_nombre || 'Sin asignar'}</p>
                {envio.transporte_nombre && (
                  <p><strong>Transporte:</strong> {envio.transporte_nombre}</p>
                )}
                <p>
                  <strong>Estado ML:</strong>{' '}
                  {ML_STATUS_LABELS[envio.mlstatus] || envio.mlstatus}
                </p>
                {envio.pistoleado_at && (
                  <p><strong>Pistoleado:</strong> {new Date(envio.pistoleado_at).toLocaleString('es-AR')}</p>
                )}
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>

      {/* Controles flotantes: modo color + leyenda */}
      <div className={styles.controlPanel}>
        <div className={styles.colorToggle}>
          <span className={styles.colorToggleLabel}>Color por:</span>
          <button
            type="button"
            className={`${styles.colorToggleBtn} ${modoColor === 'logistica' ? styles.colorToggleBtnActive : ''}`}
            onClick={() => setModoColor('logistica')}
          >
            Logística
          </button>
          <button
            type="button"
            className={`${styles.colorToggleBtn} ${modoColor === 'cordon' ? styles.colorToggleBtnActive : ''}`}
            onClick={() => setModoColor('cordon')}
          >
            Cordón
          </button>
        </div>

        {leyendaItems.length > 0 && (
          <div className={styles.leyenda}>
            {leyendaItems.map(([label, color]) => (
              <div key={label} className={styles.leyendaItem}>
                <div
                  className={styles.leyendaDot}
                  style={{ background: color }}
                />
                <span>{label}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Info bar: conteo de envíos con/sin coords */}
      <div className={styles.infoBar}>
        <div className={styles.infoBadge}>
          <MapPin size={14} />
          <span>{conCoords.length} con ubicación</span>
        </div>
        {sinCoords.length > 0 && (
          <div className={`${styles.infoBadge} ${styles.infoBadgeWarning}`}>
            <AlertTriangle size={14} />
            <span>{sinCoords.length} sin coordenadas</span>
          </div>
        )}
      </div>
    </div>
  );
}

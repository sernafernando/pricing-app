import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { LogIn, LogOut, CheckCircle, MapPin, AlertTriangle, ArrowLeft } from 'lucide-react';
import { useAuthStore } from '../store/authStore';
import { rrhhAPI } from '../services/api';
import styles from './FichajeMobile.module.css';

/**
 * FichajeMobile — Standalone mobile-first clock-in/out page.
 *
 * No sidebar, no topbar. Fullscreen layout designed for phone screens.
 * Requires JWT auth (user must be logged in) + linked RRHHEmpleado.
 *
 * Flow:
 * 1. On mount: fetch estado (employee name, suggested tipo, last fichada)
 * 2. Request GPS (informative, never blocking)
 * 3. User taps big button → POST /fichar with geo data
 * 4. Show success/error feedback, refresh estado
 */

const REFRESH_INTERVAL_MS = 30_000; // Refresh estado every 30s

/** Format datetime to HH:MM in Argentina timezone */
const formatTime = (isoString) => {
  if (!isoString) return '--:--';
  const d = new Date(isoString);
  return d.toLocaleTimeString('es-AR', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'America/Argentina/Buenos_Aires',
  });
};

/** Format datetime to HH:MM:SS for live clock */
const formatClock = (date) =>
  date.toLocaleTimeString('es-AR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'America/Argentina/Buenos_Aires',
  });

/** Format date to readable string */
const formatDate = (date) =>
  date.toLocaleDateString('es-AR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    timeZone: 'America/Argentina/Buenos_Aires',
  });

/** Format distance to human readable */
const formatDistance = (meters) => {
  if (meters == null) return null;
  if (meters < 1000) return `${Math.round(meters)}m`;
  return `${(meters / 1000).toFixed(1)}km`;
};

export default function FichajeMobile() {
  const token = useAuthStore((state) => state.token);
  const navigate = useNavigate();

  // Estado from backend
  const [estado, setEstado] = useState(null);
  const [loading, setLoading] = useState(true);
  const [initError, setInitError] = useState(null);

  // Fichada action
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [actionError, setActionError] = useState(null);

  // GPS
  const [gpsPosition, setGpsPosition] = useState(null);
  const [gpsError, setGpsError] = useState(null);

  // Live clock
  const [now, setNow] = useState(new Date());
  const clockRef = useRef(null);

  // Redirect to login if no token
  useEffect(() => {
    if (!token) {
      navigate('/login', { replace: true });
    }
  }, [token, navigate]);

  // Live clock tick
  useEffect(() => {
    clockRef.current = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(clockRef.current);
  }, []);

  // Fetch estado
  const fetchEstado = useCallback(async () => {
    try {
      const { data } = await rrhhAPI.getEstadoFichaje();
      setEstado(data);
      setInitError(null);
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (err.response?.status === 404 || err.response?.status === 403) {
        setInitError(detail || 'No tenés un empleado vinculado.');
      } else {
        setInitError(detail || 'Error al cargar estado de fichaje.');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load + periodic refresh
  useEffect(() => {
    fetchEstado();
    const interval = setInterval(fetchEstado, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchEstado]);

  // Request GPS on mount (informative, never blocking)
  useEffect(() => {
    if (!navigator.geolocation) {
      setGpsError('GPS no disponible');
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGpsPosition({
          latitud: pos.coords.latitude,
          longitud: pos.coords.longitude,
          accuracy_metros: pos.coords.accuracy,
        });
        setGpsError(null);
      },
      () => {
        setGpsError('GPS denegado');
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
  }, []);

  // Handle fichar
  const handleFichar = async () => {
    if (submitting) return;

    setSubmitting(true);
    setActionError(null);
    setResult(null);

    try {
      const payload = {};
      if (gpsPosition) {
        payload.latitud = gpsPosition.latitud;
        payload.longitud = gpsPosition.longitud;
        payload.accuracy_metros = gpsPosition.accuracy_metros;
      }

      const { data } = await rrhhAPI.ficharMobile(payload);
      setResult(data);

      // Refresh estado after successful fichada
      await fetchEstado();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setActionError(detail || 'Error al registrar fichada.');
    } finally {
      setSubmitting(false);
    }
  };

  // Clear result after 10 seconds
  useEffect(() => {
    if (!result) return;
    const timer = setTimeout(() => setResult(null), 10000);
    return () => clearTimeout(timer);
  }, [result]);

  // Loading state
  if (loading) {
    return <div className={styles.loadingContainer}>Cargando...</div>;
  }

  // Init error (no empleado, inactive, etc.)
  if (initError) {
    return (
      <div className={styles.errorContainer}>
        <AlertTriangle size={48} color="#f87171" />
        <div className={styles.errorTitle}>No se puede fichar</div>
        <div className={styles.errorDesc}>{initError}</div>
        <button className={styles.retryButton} onClick={() => navigate('/login')}>
          <ArrowLeft size={14} /> Volver
        </button>
      </div>
    );
  }

  const isEntrada = estado?.sugerencia === 'entrada';

  return (
    <div className={styles.container}>
      {/* Header: name + clock */}
      <div className={styles.header}>
        <div className={styles.employeeName}>{estado?.empleado_nombre}</div>
        <div className={styles.clock}>{formatClock(now)}</div>
        <div className={styles.date}>{formatDate(now)}</div>
      </div>

      {/* Main action area */}
      <div className={styles.actionArea}>
        <button
          className={`${styles.fichajeButton} ${isEntrada ? styles.entrada : styles.salida}`}
          onClick={handleFichar}
          disabled={submitting}
          aria-label={isEntrada ? 'Fichar entrada' : 'Fichar salida'}
        >
          {isEntrada ? (
            <LogIn className={styles.buttonIcon} />
          ) : (
            <LogOut className={styles.buttonIcon} />
          )}
          <span className={styles.buttonLabel}>
            {submitting ? 'Fichando...' : isEntrada ? 'Entrada' : 'Salida'}
          </span>
        </button>

        {/* GPS info */}
        <div className={styles.gpsInfo}>
          <MapPin className={styles.gpsIcon} />
          {gpsPosition ? (
            <span>
              GPS activo (precis. {Math.round(gpsPosition.accuracy_metros)}m)
            </span>
          ) : (
            <span>{gpsError || 'Obteniendo GPS...'}</span>
          )}
        </div>
      </div>

      {/* Success feedback */}
      {result && (
        <div className={styles.successMessage}>
          <div className={styles.successTitle}>
            <CheckCircle size={20} />
            {result.tipo === 'entrada' ? 'Entrada registrada' : 'Salida registrada'}
          </div>
          <div className={styles.successDetail}>
            {formatTime(result.timestamp)}
            {result.distancia_oficina_metros != null && (
              <> &middot; {formatDistance(result.distancia_oficina_metros)} de la oficina</>
            )}
          </div>
        </div>
      )}

      {/* Error feedback */}
      {actionError && (
        <div className={styles.errorMessage}>{actionError}</div>
      )}

      {/* Status card */}
      {estado && (
        <div className={styles.statusCard}>
          {estado.ultima_fichada && (
            <div className={styles.statusRow}>
              <span className={styles.statusLabel}>Ultima fichada</span>
              <span className={styles.statusValue}>
                <span
                  className={`${styles.statusBadge} ${
                    estado.ultima_fichada.tipo === 'entrada'
                      ? styles.badgeEntrada
                      : styles.badgeSalida
                  }`}
                >
                  {estado.ultima_fichada.tipo === 'entrada' ? (
                    <LogIn size={12} />
                  ) : (
                    <LogOut size={12} />
                  )}
                  {estado.ultima_fichada.tipo}
                </span>
                {' '}
                {formatTime(estado.ultima_fichada.timestamp)}
              </span>
            </div>
          )}
          <div className={styles.statusRow}>
            <span className={styles.statusLabel}>Fichadas hoy</span>
            <span className={styles.statusValue}>{estado.fichadas_hoy}</span>
          </div>
          <div className={styles.statusRow}>
            <span className={styles.statusLabel}>Origen</span>
            <span className={styles.statusValue}>mobile</span>
          </div>
        </div>
      )}
    </div>
  );
}

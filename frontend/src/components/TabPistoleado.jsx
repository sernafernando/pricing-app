import { useState, useEffect, useCallback, useRef } from 'react';
import {
  ScanBarcode, CheckCircle, AlertCircle, XCircle, Box, BarChart3,
  Volume2, VolumeX, Undo2,
} from 'lucide-react';
import api from '../services/api';
import styles from './TabPistoleado.module.css';

// ── Comandos QR (texto plano escaneado) ─────────────────────────────

// Patrones de contenedores — dinámicos, cualquier número es válido
const CONTENEDOR_REGEX = /^(CAJA|SUELTOS)\s+\d+$/;
const CONTENEDORES_FIJOS = ['EXTRA', 'POR FUERA'];

const esContenedor = (upper) =>
  CONTENEDOR_REGEX.test(upper) || CONTENEDORES_FIJOS.includes(upper);

const COMANDO_ANULAR = 'ANULAR';
const COMANDO_CONTADOR = 'BACKUP';

const MAX_LOG_ITEMS = 50;

// ── TTS helper ──────────────────────────────────────────────────────

// ── Audio local (archivos MP3 pregenerados) ─────────────────────────

const SOUND_BASE = '/sounds';

// Cache de Audio objects para evitar recargar
const audioCache = new Map();

const getAudio = (filename) => {
  if (audioCache.has(filename)) return audioCache.get(filename);
  const audio = new Audio(`${SOUND_BASE}/${filename}.mp3`);
  audioCache.set(filename, audio);
  return audio;
};

const playSound = (filename) => {
  const audio = getAudio(filename);
  audio.currentTime = 0;
  audio.play().catch(() => {}); // Silenciar error si no hay interacción
};

// Convertir nombre de contenedor a archivo de audio
// "CAJA 1" → "caja_1", "SUELTOS 2" → "sueltos_2", "POR FUERA" → "por_fuera"
const contenedorToSound = (nombre) =>
  nombre.toLowerCase().replace(/\s+/g, '_');

// ── QR parser ───────────────────────────────────────────────────────

const parseQrInput = (raw) => {
  const trimmed = raw.trim();
  if (!trimmed) return null;

  // Comando de contenedor (CAJA N, SUELTOS N, EXTRA, POR FUERA)
  const upper = trimmed.toUpperCase();
  if (esContenedor(upper)) {
    return { type: 'contenedor', value: upper };
  }
  if (upper === COMANDO_ANULAR) {
    return { type: 'anular' };
  }
  if (upper === COMANDO_CONTADOR) {
    return { type: 'contador' };
  }

  // JSON de etiqueta de envío
  try {
    const data = JSON.parse(trimmed);
    const shippingId = data.id || data.shipping_id;
    if (shippingId) {
      return { type: 'etiqueta', shippingId: String(shippingId) };
    }
  } catch {
    // No es JSON, podría ser un shipping_id directo (numérico)
    if (/^\d{8,}$/.test(trimmed)) {
      return { type: 'etiqueta', shippingId: trimmed };
    }
  }

  return { type: 'desconocido', raw: trimmed };
};

// ── sessionStorage helpers ───────────────────────────────────────────

const SS_PREFIX = 'pistoleado_';

const ssGet = (key, fallback) => {
  try {
    const raw = sessionStorage.getItem(`${SS_PREFIX}${key}`);
    return raw !== null ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
};

const ssSet = (key, value) => {
  try {
    sessionStorage.setItem(`${SS_PREFIX}${key}`, JSON.stringify(value));
  } catch {
    // sessionStorage lleno o deshabilitado — ignorar
  }
};

// ────────────────────────────────────────────────────────────────────

export default function TabPistoleado({ operador = null }) {
  // Logística y caja activas (persistidos en sessionStorage)
  const [logisticas, setLogisticas] = useState([]);
  const [logisticaId, setLogisticaId] = useState(() => ssGet('logisticaId', ''));
  const [cajaActiva, setCajaActiva] = useState(() => ssGet('cajaActiva', ''));

  // Scan
  const [scanInput, setScanInput] = useState('');
  const [scanLog, setScanLog] = useState(() => {
    const saved = ssGet('scanLog', []);
    // Restaurar Date objects de los timestamps
    return saved.map((item) => ({ ...item, time: new Date(item.time) }));
  });
  const [processing, setProcessing] = useState(false);
  const scanRef = useRef(null);

  // Stats
  const [stats, setStats] = useState(null);
  const [contadorSesion, setContadorSesion] = useState(() => ssGet('contadorSesion', 0));

  // Audio
  const [ttsEnabled, setTtsEnabled] = useState(() => ssGet('ttsEnabled', true));

  // ── Persistir estado en sessionStorage ───────────────────────

  useEffect(() => { ssSet('logisticaId', logisticaId); }, [logisticaId]);
  useEffect(() => { ssSet('cajaActiva', cajaActiva); }, [cajaActiva]);
  useEffect(() => { ssSet('scanLog', scanLog); }, [scanLog]);
  useEffect(() => { ssSet('contadorSesion', contadorSesion); }, [contadorSesion]);
  useEffect(() => { ssSet('ttsEnabled', ttsEnabled); }, [ttsEnabled]);

  // ── Cargar logísticas ───────────────────────────────────────

  const cargarLogisticas = useCallback(async () => {
    try {
      const { data: etiquetas } = await api.get('/etiquetas-envio', {
        params: { fecha_envio: new Date().toISOString().split('T')[0] },
      });
      // Extraer logísticas únicas de las etiquetas del día
      const logMap = new Map();
      etiquetas.forEach((e) => {
        if (e.logistica_id && e.logistica_nombre) {
          logMap.set(e.logistica_id, {
            id: e.logistica_id,
            nombre: e.logistica_nombre,
            color: e.logistica_color,
          });
        }
      });
      setLogisticas(Array.from(logMap.values()));
    } catch (err) {
      console.error('Error cargando logísticas:', err);
    }
  }, []);

  useEffect(() => {
    cargarLogisticas();
  }, [cargarLogisticas]);

  // ── Cargar stats ────────────────────────────────────────────

  const cargarStats = useCallback(async () => {
    if (!logisticaId) {
      setStats(null);
      return;
    }
    try {
      const { data } = await api.get('/etiquetas-envio/pistoleado/stats', {
        params: {
          fecha: new Date().toISOString().split('T')[0],
          logistica_id: logisticaId,
        },
      });
      setStats(data);

      // Check 100% completion
      if (data.total_etiquetas > 0 && data.pistoleadas === data.total_etiquetas) {
        const logNombre = logisticas.find((l) => l.id === Number(logisticaId))?.nombre || '';
        addLog('complete', `${logNombre} completo: ${data.pistoleadas}/${data.total_etiquetas}`);
        if (ttsEnabled) playSound('upload_ok');
      }
    } catch (err) {
      console.error('Error cargando stats:', err);
    }
  }, [logisticaId, logisticas, ttsEnabled]);

  useEffect(() => {
    cargarStats();
  }, [cargarStats]);

  // ── Auto-focus ──────────────────────────────────────────────

  useEffect(() => {
    scanRef.current?.focus();
  }, [cajaActiva, logisticaId]);

  // ── Log de escaneos ─────────────────────────────────────────

  const addLog = (type, message, extra = {}) => {
    setScanLog((prev) => [
      { id: Date.now(), type, message, time: new Date(), ...extra },
      ...prev.slice(0, MAX_LOG_ITEMS - 1),
    ]);
  };

  // ── Handlers de comandos ────────────────────────────────────

  const handleComando = async (parsed) => {
    switch (parsed.type) {
      case 'contenedor': {
        setCajaActiva(parsed.value);
        addLog('comando', `Modo: ${parsed.value}`);
        if (ttsEnabled) {
          const soundFile = contenedorToSound(parsed.value);
          // Intentar reproducir audio específico, fallback a scan_ok
          const audio = new Audio(`${SOUND_BASE}/${soundFile}.mp3`);
          audio.onerror = () => playSound('scan_ok');
          audio.play().catch(() => playSound('scan_ok'));
        }
        break;
      }
      case 'anular': {
        await handleAnular();
        break;
      }
      case 'contador': {
        if (ttsEnabled && contadorSesion > 0 && contadorSesion <= 500) {
          playSound(String(contadorSesion));
        }
        addLog('comando', `Contador: ${contadorSesion}`);
        break;
      }
      case 'desconocido': {
        addLog('error', `QR no reconocido: ${parsed.raw}`);
        break;
      }
      default:
        break;
    }
  };

  const handleAnular = async () => {
    // Buscar el último pistoleado exitoso en el log
    const ultimoExito = scanLog.find((item) => item.type === 'success');
    if (!ultimoExito?.shippingId) {
      addLog('error', 'No hay pistoleado reciente para anular');
      return;
    }

    try {
      const { data } = await api.delete(
        `/etiquetas-envio/pistolear/${ultimoExito.shippingId}`,
        { params: { operador_id: operador?.operadorActivo?.id } },
      );
      addLog('anulado', `Anulado: ${ultimoExito.shippingId} por ${data.anulado_por}`);
      setContadorSesion((prev) => Math.max(0, prev - 1));
      if (ttsEnabled) playSound('invalid_scan');
      cargarStats();
    } catch (err) {
      const detail = err.response?.data?.detail || 'Error al anular';
      addLog('error', `Error anulando: ${detail}`);
    }
  };

  // ── Handler principal de scan ───────────────────────────────

  const handleScan = async () => {
    const raw = scanInput.trim();
    if (!raw || processing) return;

    setScanInput('');
    const parsed = parseQrInput(raw);

    if (!parsed) return;

    // Si no es etiqueta, es un comando
    if (parsed.type !== 'etiqueta') {
      await handleComando(parsed);
      scanRef.current?.focus();
      return;
    }

    // Validar requisitos
    if (!logisticaId) {
      addLog('error', 'Seleccioná una logística antes de pistolear');
      scanRef.current?.focus();
      return;
    }
    if (!cajaActiva) {
      addLog('error', 'Escaneá un QR de caja primero (ej: CAJA 1)');
      scanRef.current?.focus();
      return;
    }
    if (!operador?.operadorActivo?.id) {
      addLog('error', 'Operador no identificado');
      scanRef.current?.focus();
      return;
    }

    // Pistolear
    setProcessing(true);
    try {
      const { data } = await api.post('/etiquetas-envio/pistolear', {
        shipping_id: parsed.shippingId,
        caja: cajaActiva,
        logistica_id: Number(logisticaId),
        operador_id: operador.operadorActivo.id,
      });

      const newCount = data.count || contadorSesion + 1;
      setContadorSesion(newCount);

      addLog('success', `${parsed.shippingId} — ${data.receiver_name || 'Sin nombre'} — ${data.cordon || data.ciudad || ''} — ${cajaActiva}`, {
        shippingId: parsed.shippingId,
      });

      // Sonar número si está en rango, sino beep genérico
      if (ttsEnabled) {
        if (newCount > 0 && newCount <= 500) {
          playSound(String(newCount));
        } else {
          playSound('scan_ok');
        }
      }
      cargarStats();
    } catch (err) {
      const status = err.response?.status;
      const detail = err.response?.data?.detail;

      if (status === 409) {
        // Ya pistoleada
        const info = typeof detail === 'object' ? detail : {};
        addLog('duplicate', `Ya pistoleada: ${parsed.shippingId} por ${info.pistoleado_por || '?'} en ${info.pistoleado_caja || '?'}`, {
          shippingId: parsed.shippingId,
        });
        if (ttsEnabled) playSound('scan_duplicate');
      } else if (status === 422) {
        // Logística no coincide
        const info = typeof detail === 'object' ? detail : {};
        addLog('logistica_error', `Logística no coincide: ${parsed.shippingId} — asignada a ${info.etiqueta_logistica || '?'}, pistoleando ${info.pistoleando_logistica || '?'}`, {
          shippingId: parsed.shippingId,
        });
        if (ttsEnabled) playSound('invalid_scan');
      } else if (status === 404) {
        addLog('error', `No encontrada: ${parsed.shippingId}`);
        if (ttsEnabled) playSound('invalid_scan');
      } else {
        addLog('error', `Error: ${typeof detail === 'string' ? detail : 'Error desconocido'}`);
        if (ttsEnabled) playSound('upload_error');
      }
    } finally {
      setProcessing(false);
      scanRef.current?.focus();
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleScan();
    }
  };

  // ── Render ──────────────────────────────────────────────────

  const porcentaje = stats ? stats.porcentaje : 0;

  return (
    <div className={styles.container}>
      {/* Controles superiores */}
      <div className={styles.controlsBar}>
        <div className={styles.controlGroup}>
          <label className={styles.controlLabel}>Logística</label>
          <select
            value={logisticaId}
            onChange={(e) => setLogisticaId(e.target.value)}
            className={styles.selectLogistica}
          >
            <option value="">Seleccionar logística...</option>
            {logisticas.map((l) => (
              <option key={l.id} value={l.id}>{l.nombre}</option>
            ))}
          </select>
        </div>

        <div className={styles.controlGroup}>
          <label className={styles.controlLabel}>Caja activa</label>
          <div
            className={`${styles.cajaIndicator} ${cajaActiva ? styles.cajaActiva : styles.cajaPendiente}`}
          >
            <Box size={16} />
            {cajaActiva || 'Sin caja — escaneá un QR de caja'}
          </div>
        </div>

        <button
          className={`${styles.ttsToggle} ${ttsEnabled ? styles.ttsOn : styles.ttsOff}`}
          onClick={() => setTtsEnabled((prev) => !prev)}
          aria-label={ttsEnabled ? 'Desactivar audio' : 'Activar audio'}
          title={ttsEnabled ? 'Audio activado' : 'Audio desactivado'}
        >
          {ttsEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
        </button>
      </div>

      {/* Scanner */}
      <div className={styles.scannerSection}>
        <ScanBarcode size={20} style={{ color: 'var(--text-tertiary)', flexShrink: 0 }} />
        <input
          ref={scanRef}
          type="text"
          value={scanInput}
          onChange={(e) => setScanInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            !logisticaId
              ? 'Seleccioná una logística primero...'
              : !cajaActiva
              ? 'Escaneá un QR de caja para empezar...'
              : 'Escanear QR de etiqueta...'
          }
          className={styles.scannerInput}
          autoComplete="off"
          disabled={processing}
          autoFocus
        />
        {processing && <div className={styles.processingIndicator}>Procesando...</div>}
      </div>

      {/* Stats */}
      {stats && logisticaId && (
        <div className={styles.statsSection}>
          <div className={styles.statsGrid}>
            <div className={styles.statCard}>
              <div className={`${styles.statValue} ${styles.statPrimary}`}>
                {stats.pistoleadas}/{stats.total_etiquetas}
              </div>
              <div className={styles.statLabel}>Pistoleadas</div>
            </div>
            <div className={styles.statCard}>
              <div className={styles.statValue}>{stats.pendientes}</div>
              <div className={styles.statLabel}>Pendientes</div>
            </div>
            <div className={styles.statCard}>
              <div className={`${styles.statValue} ${styles.statCounter}`}>
                {contadorSesion}
              </div>
              <div className={styles.statLabel}>Mi progreso</div>
            </div>
          </div>

          {/* Progress bar */}
          <div className={styles.progressContainer}>
            <div className={styles.progressBar}>
              <div
                className={`${styles.progressFill} ${porcentaje === 100 ? styles.progressComplete : ''}`}
                style={{ width: `${porcentaje}%` }}
              />
            </div>
            <span className={styles.progressLabel}>{porcentaje}%</span>
          </div>

          {/* Desglose por caja */}
          {Object.keys(stats.por_caja).length > 0 && (
            <div className={styles.cajasGrid}>
              {Object.entries(stats.por_caja).map(([caja, count]) => (
                <span
                  key={caja}
                  className={`${styles.cajaBadge} ${caja === cajaActiva ? styles.cajaBadgeActiva : ''}`}
                >
                  {caja}: {count}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Scan Log */}
      <div className={styles.logSection}>
        <div className={styles.logHeader}>
          <BarChart3 size={16} />
          <span>Registro de escaneos ({scanLog.length})</span>
        </div>
        <div className={styles.logList}>
          {scanLog.length === 0 ? (
            <div className={styles.logEmpty}>
              Esperando escaneos...
            </div>
          ) : (
            scanLog.map((item) => (
              <div
                key={item.id}
                className={`${styles.logItem} ${styles[`log${item.type.charAt(0).toUpperCase() + item.type.slice(1)}`] || ''}`}
              >
                <span className={styles.logIcon}>
                  {item.type === 'success' && <CheckCircle size={14} />}
                  {item.type === 'duplicate' && <AlertCircle size={14} />}
                  {item.type === 'error' && <XCircle size={14} />}
                  {item.type === 'logistica_error' && <AlertCircle size={14} />}
                  {item.type === 'comando' && <Box size={14} />}
                  {item.type === 'anulado' && <Undo2 size={14} />}
                  {item.type === 'complete' && <CheckCircle size={14} />}
                </span>
                <span className={styles.logMessage}>{item.message}</span>
                <span className={styles.logTime}>
                  {item.time.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

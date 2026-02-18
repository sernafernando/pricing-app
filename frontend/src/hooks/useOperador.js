/**
 * useOperador — Hook para gestión de operadores con PIN.
 *
 * Maneja:
 * - Carga de config de tabs que requieren PIN
 * - Validación de PIN contra el backend
 * - Estado del operador activo (autenticado con PIN)
 * - Timer de inactividad que expira el PIN
 * - Registro de actividad (acciones del operador)
 *
 * Uso:
 *   const {
 *     operadorActivo,
 *     necesitaPin,
 *     validarPin,
 *     cerrarSesionOperador,
 *     registrarActividad,
 *   } = useOperador();
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import api from '../services/api';

// Eventos que consideramos como "actividad" del usuario
const ACTIVITY_EVENTS = ['mousedown', 'keydown', 'scroll', 'touchstart'];

export default function useOperador() {
  // Config de qué tabs requieren PIN (viene del backend)
  const [configTabs, setConfigTabs] = useState([]);
  const [configLoading, setConfigLoading] = useState(true);

  // Operador actualmente autenticado con PIN
  const [operadorActivo, setOperadorActivo] = useState(null);

  // Último timestamp de actividad del usuario
  const lastActivityRef = useRef(Date.now());
  const timerRef = useRef(null);

  // Timeout en minutos para el tab actual (null si no aplica)
  const timeoutRef = useRef(null);

  // ── Cargar config de tabs ─────────────────────────────────────────

  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const { data } = await api.get('/config-operaciones/tabs');
        setConfigTabs(data.filter((t) => t.activo));
      } catch {
        // Si falla, no requerimos PIN en ningún tab
        setConfigTabs([]);
      } finally {
        setConfigLoading(false);
      }
    };
    fetchConfig();
  }, []);

  // ── Determinar si un tab necesita PIN ─────────────────────────────

  const necesitaPin = useCallback(
    (tabKey, pagePath) => {
      if (configLoading) return false; // Todavía cargando, no bloquear
      return configTabs.some(
        (t) => t.tab_key === tabKey && t.page_path === pagePath
      );
    },
    [configTabs, configLoading]
  );

  const getTimeout = useCallback(
    (tabKey, pagePath) => {
      const config = configTabs.find(
        (t) => t.tab_key === tabKey && t.page_path === pagePath
      );
      return config ? config.timeout_minutos : null;
    },
    [configTabs]
  );

  // ── Validar PIN ───────────────────────────────────────────────────

  const validarPin = useCallback(async (pin) => {
    try {
      const { data } = await api.post('/config-operaciones/operadores/validar-pin', {
        pin,
      });

      if (data.ok) {
        setOperadorActivo({
          id: data.operador_id,
          nombre: data.nombre,
          pin,
        });
        lastActivityRef.current = Date.now();
        return { ok: true, nombre: data.nombre };
      }

      return { ok: false, error: 'PIN inválido' };
    } catch (err) {
      return {
        ok: false,
        error: err.response?.data?.detail || 'Error al validar PIN',
      };
    }
  }, []);

  // ── Cerrar sesión de operador ─────────────────────────────────────

  const cerrarSesionOperador = useCallback(() => {
    setOperadorActivo(null);
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // ── Timer de inactividad ──────────────────────────────────────────

  const iniciarTimer = useCallback(
    (tabKey, pagePath) => {
      const minutes = getTimeout(tabKey, pagePath);
      if (!minutes) return;

      timeoutRef.current = minutes;
      lastActivityRef.current = Date.now();

      // Limpiar timer anterior
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }

      // Chequear inactividad cada 10 segundos
      timerRef.current = setInterval(() => {
        const elapsed = (Date.now() - lastActivityRef.current) / 1000 / 60;
        if (elapsed >= timeoutRef.current) {
          cerrarSesionOperador();
        }
      }, 10000);
    },
    [getTimeout, cerrarSesionOperador]
  );

  // ── Registrar actividad del usuario (resetea timer) ───────────────

  useEffect(() => {
    const handleActivity = () => {
      lastActivityRef.current = Date.now();
    };

    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, handleActivity, { passive: true });
    }

    return () => {
      for (const event of ACTIVITY_EVENTS) {
        window.removeEventListener(event, handleActivity);
      }
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, []);

  // ── Registrar actividad en el backend ─────────────────────────────

  const registrarActividad = useCallback(
    async (tabKey, accion, detalle = null) => {
      if (!operadorActivo) return;

      try {
        await api.post('/config-operaciones/actividad', {
          operador_id: operadorActivo.id,
          tab_key: tabKey,
          accion,
          detalle,
        });
      } catch {
        // Log silencioso — no bloquear la acción del usuario
      }
    },
    [operadorActivo]
  );

  return {
    operadorActivo,
    configLoading,
    necesitaPin,
    validarPin,
    cerrarSesionOperador,
    iniciarTimer,
    registrarActividad,
  };
}

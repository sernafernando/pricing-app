import { create } from 'zustand';
import axios from 'axios';
import { authAPI, registerAuthFailureHandler } from '../services/api';

// --- Proactive Token Refresh ---
// En vez de esperar a que un request falle con 401, decodificamos el JWT
// y programamos un refresh ANTES de que expire. El usuario nunca ve nada.

let refreshTimer = null;

function getTokenExpiry(token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    return payload.exp ? payload.exp * 1000 : null; // ms
  } catch {
    return null;
  }
}

function scheduleProactiveRefresh(accessToken, doRefresh) {
  // Limpiar timer anterior
  if (refreshTimer) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }

  const expiry = getTokenExpiry(accessToken);
  if (!expiry) return;

  // Refreshear cuando quede el 20% del tiempo restante
  // Ej: token de 30min → refreshea a los 24min (quedan 6min de margen)
  const now = Date.now();
  const timeLeft = expiry - now;
  const refreshAt = Math.max(timeLeft * 0.8, 10_000); // mínimo 10s

  refreshTimer = setTimeout(() => {
    doRefresh();
  }, refreshAt);
}

async function silentRefresh(set, get) {
  const refreshToken = localStorage.getItem('refresh_token');
  if (!refreshToken) return;

  try {
    const { data } = await axios.post(
      `${import.meta.env.VITE_API_URL}/auth/refresh`,
      { refresh_token: refreshToken }
    );
    const newToken = data.access_token;
    localStorage.setItem('token', newToken);
    set({ token: newToken });

    // Programar el próximo refresh
    scheduleProactiveRefresh(newToken, () => silentRefresh(set, get));
  } catch {
    // Si el refresh token expiró, no hacemos nada agresivo acá.
    // El interceptor de api.js se va a encargar cuando el usuario
    // haga su próximo request.
  }
}

export const useAuthStore = create((set, get) => {
  // Registrar el handler de auth failure para que api.js pueda
  // triggear un logout limpio sin recargar la página
  registerAuthFailureHandler(() => {
    if (refreshTimer) {
      clearTimeout(refreshTimer);
      refreshTimer = null;
    }
    set({ token: null, user: null, isAuthenticated: false });
  });

  return {
    user: null,
    token: localStorage.getItem('token'),
    isAuthenticated: false,

    login: async (username, password) => {
      try {
        const response = await authAPI.login(username, password);
        const { access_token, refresh_token, usuario } = response.data;

        localStorage.setItem('token', access_token);
        localStorage.setItem('refresh_token', refresh_token);
        set({ token: access_token, user: usuario, isAuthenticated: true });

        // Arrancar proactive refresh
        scheduleProactiveRefresh(access_token, () => silentRefresh(set, get));

        return { success: true };
      } catch (error) {
        return { success: false, error: error.response?.data?.detail || 'Error al iniciar sesión' };
      }
    },

    logout: () => {
      if (refreshTimer) {
        clearTimeout(refreshTimer);
        refreshTimer = null;
      }
      localStorage.removeItem('token');
      localStorage.removeItem('refresh_token');
      set({ token: null, user: null, isAuthenticated: false });
    },

    checkAuth: async () => {
      try {
        const response = await authAPI.me();
        set({ user: response.data, isAuthenticated: true });

        // Si checkAuth pasa, el token es válido → programar proactive refresh
        const token = localStorage.getItem('token');
        if (token) {
          scheduleProactiveRefresh(token, () => silentRefresh(set, get));
        }
      } catch {
        localStorage.removeItem('token');
        localStorage.removeItem('refresh_token');
        set({ token: null, user: null, isAuthenticated: false });
      }
    },
  };
});

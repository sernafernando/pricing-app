import { useState, useEffect } from 'react';
import api from '../services/api';

const POLL_INTERVAL_MS = 15 * 60 * 1000; // 15 minutos

/**
 * Hook para obtener datos de clima desde el backend.
 * Hace polling cada 15 minutos para mantener el dato actualizado.
 * 
 * @returns {{ weather: object|null, loading: boolean, error: string|null }}
 */
export const useWeather = () => {
  const [weather, setWeather] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let intervalId = null;
    let cancelled = false;

    const fetchWeather = async () => {
      try {
        const { data } = await api.get('/api/weather/current');
        if (!cancelled) {
          setWeather(data);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setError('Clima no disponible');
          setWeather(null);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    fetchWeather();
    intervalId = setInterval(fetchWeather, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, []);

  return { weather, loading, error };
};

export default useWeather;

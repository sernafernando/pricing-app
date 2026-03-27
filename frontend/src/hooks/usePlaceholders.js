import { useState, useEffect, useCallback } from 'react';
import { rrhhAPI } from '../services/api';

/**
 * Extrae placeholders {xxx} de un texto.
 * Retorna array de nombres únicos. Ej: "{nombre} bla {legajo}" → ["nombre", "legajo"]
 */
export const extractPlaceholders = (text) => {
  if (!text) return [];
  const matches = text.match(/\{(\w+)\}/g);
  if (!matches) return [];
  return [...new Set(matches.map((m) => m.slice(1, -1)))];
};

/**
 * Reemplaza {placeholder} en el texto con los valores del mapa.
 * Los que no tienen valor quedan como {placeholder}.
 */
export const interpolateText = (template, values) => {
  if (!template) return '';
  return template.replace(/\{(\w+)\}/g, (match, key) => {
    const val = values[key];
    return val !== undefined && val !== '' ? val : match;
  });
};

const formatDate = (dateStr) => {
  if (!dateStr) return '-';
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
};

/**
 * Hook para manejar placeholders de textos predefinidos de sanciones.
 *
 * Encapsula: known placeholders, current placeholders, values, auto-fill, help modal.
 */
export default function usePlaceholders({ empleados, tiposSancion }) {
  const [knownPlaceholders, setKnownPlaceholders] = useState({});
  const [placeholderValues, setPlaceholderValues] = useState({});
  const [currentPlaceholders, setCurrentPlaceholders] = useState([]);
  const [showPlaceholderHelp, setShowPlaceholderHelp] = useState(false);

  useEffect(() => {
    const fetchPlaceholders = async () => {
      try {
        const { data } = await rrhhAPI.obtenerPlaceholdersSancion();
        setKnownPlaceholders(data || {});
      } catch {
        setKnownPlaceholders({});
      }
    };
    fetchPlaceholders();
  }, []);

  const buildAutoFillValues = useCallback((empleadoId, formData) => {
    const emp = empleados.find((e) => e.id === Number(empleadoId));
    const tipo = tiposSancion.find((t) => t.id === Number(formData.tipo_sancion_id));
    const auto = {};
    if (emp) {
      auto.nombre_empleado = `${emp.apellido}, ${emp.nombre}`.toUpperCase();
      auto.legajo = emp.legajo || '';
      auto.dni = emp.dni || '';
      auto.cuil = emp.cuil || '';
      auto.area = emp.area || '';
      auto.puesto = emp.puesto || '';
      auto.fecha_ingreso = emp.fecha_ingreso ? formatDate(emp.fecha_ingreso) : '';
    }
    if (tipo) {
      auto.tipo_sancion = tipo.nombre || '';
    }
    if (formData.fecha_desde && formData.fecha_hasta) {
      const desde = new Date(formData.fecha_desde + 'T12:00:00');
      const hasta = new Date(formData.fecha_hasta + 'T12:00:00');
      const diff = Math.round((hasta - desde) / (1000 * 60 * 60 * 24)) + 1;
      if (diff > 0) auto.dias_suspension = String(diff);
    }
    if (formData.fecha) auto.fecha_sancion = formatDate(formData.fecha);
    if (formData.fecha_desde) auto.fecha_desde = formatDate(formData.fecha_desde);
    if (formData.fecha_hasta) auto.fecha_hasta = formatDate(formData.fecha_hasta);
    return auto;
  }, [empleados, tiposSancion]);

  const refreshPlaceholderValues = useCallback((formData, extraPlaceholders) => {
    const auto = buildAutoFillValues(formData.empleado_id, formData);
    const phs = extraPlaceholders || currentPlaceholders;
    setPlaceholderValues((prev) => {
      const next = {};
      for (const ph of phs) {
        if (auto[ph] !== undefined) {
          next[ph] = auto[ph];
        } else {
          next[ph] = prev[ph] || '';
        }
      }
      return next;
    });
  }, [buildAutoFillValues, currentPlaceholders]);

  const reset = useCallback(() => {
    setCurrentPlaceholders([]);
    setPlaceholderValues({});
  }, []);

  return {
    knownPlaceholders,
    placeholderValues,
    setPlaceholderValues,
    currentPlaceholders,
    setCurrentPlaceholders,
    showPlaceholderHelp,
    setShowPlaceholderHelp,
    refreshPlaceholderValues,
    reset,
  };
}

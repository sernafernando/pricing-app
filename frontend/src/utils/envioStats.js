/**
 * Compute estadísticas de etiquetas de envío desde el array local.
 *
 * Reemplaza al endpoint GET /etiquetas-envio/estadisticas que hacía
 * 8+ queries SQL pesadas con JOINs y ROW_NUMBER. Como el listing
 * ya devuelve TODAS las etiquetas (sin paginar), las stats se pueden
 * calcular client-side en O(n) con un solo recorrido del array.
 *
 * El shape del objeto retornado es idéntico al del response de
 * EstadisticasEnvioResponse (backend) para no tocar el template.
 *
 * @param {Array} etiquetas — array completo de etiquetas del listing
 * @returns {Object} stats con la misma forma que EstadisticasEnvioResponse
 */
export const computeStats = (etiquetas) => {
  const por_cordon = {};
  const por_logistica = {};
  const por_estado_ml = {};
  const por_estado_erp = {};
  const costo_por_logistica = {};

  let sin_cordon = 0;
  let sin_logistica = 0;
  let flagged = 0;
  let retornados = 0;
  let costo_total = 0;

  for (const e of etiquetas) {
    // Cordón
    if (e.cordon) {
      por_cordon[e.cordon] = (por_cordon[e.cordon] || 0) + 1;
    } else {
      sin_cordon++;
    }

    // Logística
    if (e.logistica_id != null && e.logistica_nombre) {
      por_logistica[e.logistica_nombre] = (por_logistica[e.logistica_nombre] || 0) + 1;
    } else {
      sin_logistica++;
    }

    // Estado ML
    if (e.mlstatus) {
      por_estado_ml[e.mlstatus] = (por_estado_ml[e.mlstatus] || 0) + 1;
    }

    // Estado ERP (incluye "Facturado")
    if (e.ssos_name) {
      por_estado_erp[e.ssos_name] = (por_estado_erp[e.ssos_name] || 0) + 1;
    }

    // Flag
    if (e.flag_envio != null) {
      flagged++;
    }

    // Retornados
    if (e.retornado) {
      retornados++;
    }

    // Costos
    if (e.costo_envio != null) {
      const costo = Number(e.costo_envio) || 0;
      costo_total += costo;
      if (e.logistica_nombre) {
        costo_por_logistica[e.logistica_nombre] = (costo_por_logistica[e.logistica_nombre] || 0) + costo;
      }
    }
  }

  return {
    total: etiquetas.length,
    por_cordon,
    sin_cordon,
    por_logistica,
    sin_logistica,
    por_estado_ml,
    por_estado_erp,
    costo_total: Math.round(costo_total * 100) / 100,
    costo_por_logistica,
    flagged,
    retornados,
  };
};

/** Display labels for `eje_procesal` (warehouse process axis). */
const EJES_PROCESAL_LABEL = {
  n_a_servicio: 'N/A servicio',
  por_recibir: 'Por recibir',
  recibido: 'Recibido',
  faltantes_sin_res: 'Faltantes',
  faltantes_con_res: 'Faltantes con resolución',
  controlado: 'Controlado',
};

/** Same axis, retiro copy when the pedido requires pickup at the supplier. */
const EJES_PROCESAL_LABEL_RETIRO = {
  ...EJES_PROCESAL_LABEL,
  por_recibir: 'Por retirar',
  recibido: 'Retirado',
};

/**
 * @param {string | null | undefined} eje
 * @param {boolean} [requiereEnvio=false]
 * @param {boolean} [arriboEnCurso=false] — partial arribo/retiro saved; still por_recibir
 * @returns {string}
 */
export function ejeProcesalLabel(eje, requiereEnvio = false, arriboEnCurso = false) {
  if (!eje) return '—';
  if (arriboEnCurso && eje === 'por_recibir') {
    return requiereEnvio ? 'Retirando' : 'Recibiendo';
  }
  const map = requiereEnvio ? EJES_PROCESAL_LABEL_RETIRO : EJES_PROCESAL_LABEL;
  return map[eje] || eje;
}

export { EJES_PROCESAL_LABEL };

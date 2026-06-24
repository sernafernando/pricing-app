/**
 * EstadoBadge — Badge visual de estado para entidades del módulo compras.
 *
 * Soporta 3 variantes (`pedido`, `op`, `nc`) que mapean estados internos del
 * backend a 5 tonos visuales (Pagado/Aplicada verde, Parcial amarillo,
 * Pendiente naranja, Cancelado gris, Borrador gris suave).
 *
 * Para variant='pedido': si pedido.estado='pagado_parcial' AND saldo===0,
 * se muestra como Pagado (caso edge de pedidos saldados con corrección).
 *
 * Si el estado no está mapeado, se muestra "Desconocido" tono gris (no throw).
 *
 * @example
 * <EstadoBadge variant="pedido" estado="pagado_parcial" saldo={0} />
 * <EstadoBadge variant="op" estado="pendiente" />
 * <EstadoBadge variant="nc" estado="aplicada_parcial" />
 */

import { CheckCircle2, Clock, CircleAlert, X, HelpCircle } from 'lucide-react';
import styles from './EstadoBadge.module.css';

// ─────────────────────────────────────────────────────────────────────────
// Mapping por variant. Clave = estado backend.
// Cada entry: { tone: string (toneXxx class), label: string, icon: lucide }
// ─────────────────────────────────────────────────────────────────────────

const TONES = {
  pagado: { class: styles.tonePagado, icon: CheckCircle2 },
  parcial: { class: styles.toneParcial, icon: Clock },
  pendiente: { class: styles.tonePendiente, icon: CircleAlert },
  cancelado: { class: styles.toneCancelado, icon: X },
  borrador: { class: styles.toneBorrador, icon: Clock },
  desconocido: { class: styles.toneCancelado, icon: HelpCircle },
};

const MAPPING_PEDIDO = {
  pagado: { tone: 'pagado', label: 'Pagado' },
  pagado_parcial: { tone: 'parcial', label: 'Parcial' },
  // pagado_parcial+saldo=0 se resuelve en runtime más abajo
  // Estados de recepción en depósito (TabRecepcionDeposito).
  recibido: { tone: 'pagado', label: 'Recibido' },
  con_faltantes: { tone: 'pendiente', label: 'Con faltantes' },
  aprobado: { tone: 'pendiente', label: 'Pendiente' },
  pendiente_aprobacion: { tone: 'borrador', label: 'Sin aprobar' },
  borrador: { tone: 'borrador', label: 'Borrador' },
  rechazado: { tone: 'cancelado', label: 'Rechazado' },
  cancelado: { tone: 'cancelado', label: 'Cancelado' },
};

const MAPPING_OP = {
  pagado: { tone: 'pagado', label: 'Pagada' },
  pendiente: { tone: 'pendiente', label: 'Pendiente' },
  anulado: { tone: 'cancelado', label: 'Anulada' },
  cancelado: { tone: 'cancelado', label: 'Cancelada' },
};

const MAPPING_NC = {
  aplicada: { tone: 'pagado', label: 'Aplicada' },
  aplicada_parcial: { tone: 'parcial', label: 'Parcial' },
  aprobado: { tone: 'pendiente', label: 'Aprobada' },
  pendiente_aprobacion: { tone: 'borrador', label: 'Sin aprobar' },
  borrador: { tone: 'borrador', label: 'Borrador' },
  rechazado: { tone: 'cancelado', label: 'Rechazada' },
  cancelado: { tone: 'cancelado', label: 'Cancelada' },
};

const VARIANTS = {
  pedido: MAPPING_PEDIDO,
  op: MAPPING_OP,
  nc: MAPPING_NC,
};

/**
 * @param {Object} props
 * @param {'pedido'|'op'|'nc'} props.variant
 * @param {string} props.estado
 * @param {number} [props.saldo] - sólo aplica a variant='pedido'
 * @param {'sm'|'md'} [props.size='sm']
 */
export default function EstadoBadge({ variant, estado, saldo, size = 'sm' }) {
  const mapping = VARIANTS[variant];
  let entry = mapping?.[estado];

  // Caso edge: pedido pagado_parcial con saldo=0 → mostrar como Pagado
  if (variant === 'pedido' && estado === 'pagado_parcial' && Number(saldo) === 0) {
    entry = { tone: 'pagado', label: 'Pagado' };
  }

  // Fallback: variant o estado desconocido
  if (!entry) {
    entry = { tone: 'desconocido', label: 'Desconocido' };
  }

  const tone = TONES[entry.tone] || TONES.desconocido;
  const Icon = tone.icon;
  const sizeClass = size === 'md' ? styles.sizeMd : styles.sizeSm;

  return (
    <span className={`${styles.badge} ${tone.class} ${sizeClass}`}>
      <Icon size={11} strokeWidth={2.5} />
      {entry.label}
    </span>
  );
}

import { AlertTriangle, Bell, DollarSign, Package, Receipt, Wrench } from 'lucide-react';

/**
 * Notification families shown as tabs in the bell and in /notificaciones.
 * Mirrors backend/app/services/notificacion_familias.py.
 */
export const FAMILIAS_NOTIFICACION = [
  { key: null, label: 'Todas' },
  { key: 'compras', label: 'Compras' },
  { key: 'markup', label: 'Markup' },
  { key: 'tecnicas', label: 'Técnicas' },
  { key: 'otras', label: 'Otras' },
];

const PREFIJOS_TECNICAS = ['ml_bot.', 'tickets.'];

const TITULOS_POR_TIPO = {
  'compras.factura_cargada': 'Factura cargada',
  'compras.pedido_monto_difiere_factura': 'Monto del pedido distinto a la factura',
  'compras.faltantes': 'Faltantes en recepción',
  'compras.faltantes_resuelto': 'Faltantes resueltos',
  'ml_bot.llm_failover': 'Bot ML: falla de proveedor LLM',
  'tickets.vikunja_sync_error': 'Tickets: error de sincronización',
  stock_bajo: 'Stock bajo',
  precio_desactualizado: 'Precio desactualizado',
};

const ICONOS_POR_FAMILIA = { compras: Receipt, markup: AlertTriangle, tecnicas: Wrench };
const ICONOS_OTRAS = { stock_bajo: Package, precio_desactualizado: DollarSign };

export function familiaDeTipo(tipo = '') {
  if (tipo.startsWith('compras.')) return 'compras';
  if (tipo === 'markup_bajo') return 'markup';
  if (PREFIJOS_TECNICAS.some((prefijo) => tipo.startsWith(prefijo))) return 'tecnicas';
  return 'otras';
}

/** Only markup_bajo uses the markup template (product, markup real, sale details). */
export const esNotificacionMarkup = (tipo) => familiaDeTipo(tipo) === 'markup';

/** lucide icon component for a notification tipo (one per family, a few per tipo in "otras"). */
export function iconoDeTipo(tipo) {
  const familia = familiaDeTipo(tipo);
  return ICONOS_POR_FAMILIA[familia] || ICONOS_OTRAS[tipo] || Bell;
}

export function tituloDeTipo(tipo) {
  if (TITULOS_POR_TIPO[tipo]) return TITULOS_POR_TIPO[tipo];
  const familia = FAMILIAS_NOTIFICACION.find((f) => f.key === familiaDeTipo(tipo));
  return familia ? familia.label : 'Notificación';
}

/** Unread count of a tab: the total for "Todas", the family count otherwise. */
export function noLeidasDeFamilia(stats, familia) {
  if (!familia) return stats?.no_leidas ?? 0;
  return stats?.no_leidas_por_familia?.[familia] ?? 0;
}

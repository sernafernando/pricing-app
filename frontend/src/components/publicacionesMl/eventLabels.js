/**
 * Spanish labels of the event types the store writes
 * (`services/ml_publications/events.py`). An unknown type shows as itself:
 * a new type must be visible before somebody gets to label it.
 */
export const EVENT_LABELS = {
  status_paused: 'Pausada',
  status_activated: 'Activada',
  status_closed: 'Cerrada',
  status_under_review: 'En revisión',
  status_changed_other: 'Cambio de estado',
  sub_status_changed: 'Cambio de subestado',
  stock_depleted: 'Sin stock',
  stock_replenished: 'Stock repuesto',
  price_changed: 'Precio modificado',
  promotion_offered: 'Promoción ofrecida',
  promotion_activated: 'Promoción activada',
  promotion_finished: 'Promoción finalizada',
  promotion_price_changed: 'Precio de promoción modificado',
  catalog_competition_won: 'Ganó la competencia de catálogo',
  catalog_competition_lost: 'Perdió la competencia de catálogo',
  moderation_applied: 'Moderación aplicada',
  moderation_resolved: 'Moderación resuelta',
  product_link_changed: 'Vínculo con producto modificado',
  item_gone: 'Eliminada de ML',
  item_restored: 'Restaurada en ML',
};

export const eventLabel = (type) => EVENT_LABELS[type] ?? type;

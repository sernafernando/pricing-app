"""After a costo SI recompute: re-cost the stored Tienda Nube metrics (`ventas_tienda_nube_metricas`) of the product from that date on
(owner L15). The work is shared with the other GBP metrics table: `app.services.costo_si_metricas_gbp`."""

from app.services.costo_si.despues import registrar
from app.services.costo_si_metricas_gbp import recostear_tn

registrar("ventas_tienda_nube_metricas", recostear_tn)

"""After a costo SI recompute: re-cost the stored ventas fuera ML metrics (`ventas_fuera_ml_metricas`) of the product from that date on
(owner L15). The work is shared with the other GBP metrics table: `app.services.costo_si_metricas_gbp`."""

from app.services.costo_si.despues import registrar
from app.services.costo_si_metricas_gbp import recostear_fuera

registrar("ventas_fuera_ml_metricas", recostear_fuera)

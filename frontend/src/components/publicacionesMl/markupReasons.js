/** Why the backend could not compute a markup (`view/markup.py` `REASON_*`). */
export const MARKUP_REASONS = {
  sin_vinculo: 'La publicación no está vinculada a un producto',
  sin_costo: 'El producto vinculado no tiene costo',
  sin_comision: 'No hay comisión para la lista de precios de la publicación',
  sin_precio: 'La publicación no tiene precio',
  desactualizado: 'La variación cambió mientras se calculaba: recargá para ver el dato actual',
  ads_sin_ventas: 'Hay costo de Ads pero no hubo unidades vendidas',
};
export const UNKNOWN_REASON = 'No se pudo calcular el markup';

// Filter value constants for Productos page
export const FILTER_VALUES = {
  TODOS: 'todos',
  CON_STOCK: 'con_stock',
  SIN_STOCK: 'sin_stock',
  CON_PRECIO: 'con_precio',
  SIN_PRECIO: 'sin_precio',
  CON_REBATE: 'con_rebate',
  SIN_REBATE: 'sin_rebate',
  CON_OFERTA: 'con_oferta',
  SIN_OFERTA: 'sin_oferta',
  CON_WEB_TRANSF: 'con_web_transf',
  SIN_WEB_TRANSF: 'sin_web_transf',
  CON_DESCUENTO: 'con_descuento',
  SIN_DESCUENTO: 'sin_descuento',
  NO_PUBLICADO: 'no_publicado',
  POSITIVO: 'positivo',
  NEGATIVO: 'negativo',
  CON_OUT_OF_CARDS: 'con_out_of_cards',
  SIN_OUT_OF_CARDS: 'sin_out_of_cards'
};

// Available color labels for product row marking
export const COLORES_DISPONIBLES = [
  { id: 'rojo', nombre: 'Urgente', color: 'var(--product-urgent-bg)', colorTexto: 'var(--product-urgent-text)' },
  { id: 'naranja', nombre: 'Advertencia', color: 'var(--product-warning-bg)', colorTexto: 'var(--product-warning-text)' },
  { id: 'amarillo', nombre: 'Atención', color: 'var(--product-attention-bg)', colorTexto: 'var(--product-attention-text)' },
  { id: 'verde', nombre: 'OK', color: 'var(--product-ok-bg)', colorTexto: 'var(--product-ok-text)' },
  { id: 'azul', nombre: 'Info', color: 'var(--product-info-bg)', colorTexto: 'var(--product-info-text)' },
  { id: 'purpura', nombre: 'Revisión', color: 'var(--product-review-bg)', colorTexto: 'var(--product-review-text)' },
  { id: 'gris', nombre: 'Inactivo', color: 'var(--product-inactive-bg)', colorTexto: 'var(--product-inactive-text)' },
  { id: null, nombre: 'Sin color', color: null, colorTexto: null },
];

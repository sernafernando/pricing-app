// Labels and formatting shared by the "Acciones IA" page and its undo dialog.

export const ACCIONES = {
  promo_aplicar: 'Aplicar promo',
  promo_quitar: 'Quitar promo',
  estado_pausar: 'Pausar',
  estado_activar: 'Activar',
  precio_lista: 'Precio de lista',
  precio_cuota: 'Precio en cuotas',
  precio_markup_masivo: 'Markup masivo',
  precio_mayorista: 'Precio mayorista',
};

export const RESULTADOS = {
  ok: 'OK',
  rechazada: 'Rechazada',
  bloqueada: 'Bloqueada',
  ambigua: 'Ambigua',
  error: 'Error',
  denegada: 'Denegada',
};

export const etiquetaAccion = (accion) => ACCIONES[accion] || accion;
export const etiquetaResultado = (resultado) => RESULTADOS[resultado] || resultado;

const formatearValor = (valor) => {
  if (valor === null || valor === undefined) return '—';
  if (typeof valor === 'number') return valor.toLocaleString('es-AR', { maximumFractionDigits: 2 });
  if (typeof valor === 'boolean') return valor ? 'sí' : 'no';
  return String(valor);
};

// `antes` / `despues` are flat objects of scalars: one "clave: valor" line each.
export const pares = (objeto) =>
  Object.entries(objeto || {}).map(([clave, valor]) => `${clave}: ${formatearValor(valor)}`);

export const formatearFecha = (iso) =>
  iso ? new Date(iso).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' }) : '—';

export const formatearHora = (iso) =>
  iso ? new Date(iso).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' }) : '';

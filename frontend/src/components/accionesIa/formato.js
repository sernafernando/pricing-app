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

// ML publication states arrive in English from the API.
const ESTADOS = { active: 'activa', paused: 'pausada', closed: 'finalizada', under_review: 'en revisión', inactive: 'inactiva' };

// `antes` / `despues` are flat objects of scalars: one "clave: valor" line each.
export const pares = (objeto) =>
  Object.entries(objeto || {}).map(
    ([clave, valor]) => `${clave}: ${clave === 'estado' ? ESTADOS[valor] || formatearValor(valor) : formatearValor(valor)}`
  );

// 24-hour clock everywhere: "14:05", never "02:05 p. m." (which also ends sentences in a double period).
const HORA = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };

export const formatearHora = (iso) => (iso ? new Date(iso).toLocaleTimeString('es-AR', HORA) : '');

/** Short date for the table: "19/11 14:05". */
export const formatearFecha = (iso) =>
  iso
    ? `${new Date(iso).toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit' })} ${formatearHora(iso)}`
    : '—';

/** Full date for the tooltip: "19/11/26 14:05". */
export const formatearFechaCompleta = (iso) =>
  iso
    ? `${new Date(iso).toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: '2-digit' })} ${formatearHora(iso)}`
    : '';

// The AI tools, as the filter shows them (the API filters by the tool name).
export const HERRAMIENTAS = {
  promo_aplicar: 'Aplicar promo',
  promo_quitar: 'Quitar promo',
  promos_aplicar_mejoras: 'Aplicar promos que mejoran',
  publicaciones_estado: 'Pausar o activar publicaciones',
  precio_lista_cambiar: 'Cambiar precio de lista',
  precios_markup_masivo: 'Cambiar markup masivo',
  precio_cuotas_cambiar: 'Cambiar precio en cuotas',
  precio_mayorista_cambiar: 'Cambiar precio mayorista',
  accion_deshacer: 'Deshacer acciones',
};

export const etiquetaHerramienta = (tool) => HERRAMIENTAS[tool] || tool;

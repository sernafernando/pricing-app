/**
 * Registry dinámico de páginas y tabs.
 *
 * Cada página que tiene tabs llama a `registrarPagina()` a nivel de módulo
 * (fuera de componentes). Como los imports son estáticos en App.jsx,
 * todas las páginas se registran al arrancar la app — no depende de que
 * el componente se monte.
 *
 * Uso en la página:
 *   import { registrarPagina } from '../registry/tabRegistry';
 *   registrarPagina({
 *     pagePath: '/pedidos-preparacion',
 *     pageLabel: 'Preparación',
 *     tabs: [
 *       { tabKey: 'preparacion', label: 'Preparación' },
 *       { tabKey: 'envios-flex', label: 'Envíos Flex' },
 *     ],
 *   });
 *
 * Uso en ConfigOperaciones:
 *   import { getPaginas } from '../registry/tabRegistry';
 *   const paginas = getPaginas(); // [{ pagePath, pageLabel, tabs: [...] }]
 */

const _paginas = new Map();

/**
 * Registra una página y sus tabs en el catálogo global.
 * Si se llama dos veces con el mismo pagePath, la segunda sobreescribe.
 */
export const registrarPagina = ({ pagePath, pageLabel, tabs }) => {
  _paginas.set(pagePath, { pagePath, pageLabel, tabs });
};

/**
 * Devuelve todas las páginas registradas, ordenadas por label.
 */
export const getPaginas = () => {
  return Array.from(_paginas.values()).sort((a, b) =>
    a.pageLabel.localeCompare(b.pageLabel)
  );
};

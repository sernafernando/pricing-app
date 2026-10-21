/**
 * Pure helpers that answer "which screens can this user open, and why?" from
 * the `permisos_detallados` payload of `GET /permisos/usuario/{id}`:
 *
 *   { categoria: [{ codigo, nombre, descripcion, es_critico, tiene_por_rol,
 *                   override (bool|null), efectivo, origen,
 *                   roles_adicionales: [codigo] }] }
 *
 * `origen` is one of superadmin | override_agregado | override_quitado | rol |
 * rol_adicional | sin_permiso (backend
 * `PermisosService.obtener_permisos_detallados_usuario`).
 *
 * Screens come from `screenCatalog.js`; every screen's `permisos` is any-of,
 * exactly like `ProtectedRoute` in App.jsx. Every other payload permission is
 * an extra ("permiso adicional"): it is listed under the screen(s) where it
 * acts (`PERMISOS_ADICIONALES` rules) and never changes that screen's access;
 * one with no screen at all goes to the "Otros permisos" group.
 */

// Mirrors backend/app/services/pm_scope.py: FULL_VIEW_ROLES and PERMISO_FULL_VIEW.
export const FULL_VIEW_ROLES = ['SUPERADMIN', 'ADMIN', 'GERENTE'];
export const PERMISO_FULL_VIEW = 'ventas_ml.ver_todas_marcas';

export const STATUS = {
  ACCEDE: 'accede',
  SIN_ACCESO: 'sin_acceso',
  CONDICIONAL: 'condicional',
  PUBLICA: 'publica',
};

export const FILTROS = ['todo', 'sin_acceso', 'con_overrides', 'criticos', 'depende_de_datos'];

/** Flattens the per-category payload into a Map codigo -> permission (+ categoria). */
export function indexarPermisos(permisosDetallados) {
  const indice = new Map();
  for (const [categoria, permisos] of Object.entries(permisosDetallados || {})) {
    for (const permiso of permisos || []) {
      indice.set(permiso.codigo, { ...permiso, categoria });
    }
  }
  return indice;
}

/**
 * Same decision as `pm_scope.is_full_view`: a full-view role, or the
 * full-view permission held effectively (an override that removed it wins).
 */
export function esFullView({ rol, permisos }) {
  if (FULL_VIEW_ROLES.includes(rol)) return true;
  return Boolean(permisos.get(PERMISO_FULL_VIEW)?.efectivo);
}

function filaDe(codigo, permisos) {
  const permiso = permisos.get(codigo);
  if (!permiso) {
    // The catalog references a code the backend does not know (renamed or not
    // migrated yet): show it, but it can neither grant access nor be edited.
    return {
      codigo,
      nombre: codigo,
      descripcion: '',
      es_critico: false,
      override: null,
      efectivo: false,
      origen: 'sin_permiso',
      desconocido: true,
    };
  }
  return permiso;
}

// A data-scoped screen can declare its own bypass (the ranking's
// `consultas.ver_ranking`); otherwise the global pm_scope rule applies.
function veTodoEnPantalla(screen, permisos, ctx) {
  if (screen.fullViewPermisos) {
    return screen.fullViewPermisos.some((codigo) => permisos.get(codigo)?.efectivo);
  }
  return ctx.esFullView;
}

/**
 * Access of one user to one screen.
 *
 * ctx: { esFullView, paresDelegados (number | null = unknown), esSuperadmin }.
 * `condicional` is only claimed when the pair count is KNOWN to be zero.
 */
export function accesoPantalla(screen, permisos, ctx) {
  if (screen.permisos.length === 0) {
    return { status: STATUS.PUBLICA, origen: null, filas: [] };
  }

  const filas = screen.permisos.map((codigo) => filaDe(codigo, permisos));

  if (ctx.esSuperadmin) {
    return { status: STATUS.ACCEDE, origen: 'superadmin', filas };
  }

  const otorgante = filas.find((fila) => fila.efectivo);
  if (!otorgante) {
    const quitada = filas.some((fila) => fila.origen === 'override_quitado');
    return { status: STATUS.SIN_ACCESO, origen: quitada ? 'override_quitado' : 'sin_permiso', filas };
  }

  const sinDatos =
    screen.scope === 'data' && ctx.paresDelegados === 0 && !veTodoEnPantalla(screen, permisos, ctx);

  return { status: sinDatos ? STATUS.CONDICIONAL : STATUS.ACCEDE, origen: otorgante.origen, filas };
}

const prefijoDe = (codigo) => String(codigo).split('.')[0];

/**
 * Paths (catalog order) whose "Permisos adicionales" list `codigo`; [] = none.
 * reglas: `{ prefijos, porPantalla }` (screenCatalog `PERMISOS_ADICIONALES`):
 * porPantalla wins, then prefijos, then the screens whose access permissions
 * share the prefix. An access permission of any screen is never an extra.
 */
export function pantallasDeAdicional(codigo, catalogo, reglas = {}) {
  if (catalogo.some((screen) => screen.permisos.includes(codigo))) return [];
  const { prefijos = {}, porPantalla = {} } = reglas;
  const prefijo = prefijoDe(codigo);
  let destinos = Object.keys(porPantalla).filter((path) => porPantalla[path].includes(codigo));
  if (destinos.length === 0) {
    destinos = Object.hasOwn(prefijos, prefijo)
      ? prefijos[prefijo]
      : catalogo.filter((screen) => screen.permisos.some((p) => prefijoDe(p) === prefijo)).map((s) => s.path);
  }
  const elegidos = new Set(destinos);
  return catalogo.filter((screen) => elegidos.has(screen.path)).map((screen) => screen.path);
}

function repartirAdicionales(permisos, catalogo, reglas) {
  const porPantalla = new Map(catalogo.map((screen) => [screen.path, []]));
  const otros = [];
  const acceso = new Set(catalogo.flatMap((screen) => screen.permisos));
  for (const permiso of permisos.values()) {
    if (acceso.has(permiso.codigo)) continue;
    const destinos = pantallasDeAdicional(permiso.codigo, catalogo, reglas);
    if (destinos.length === 0) otros.push(permiso);
    for (const path of destinos) porPantalla.get(path).push(permiso);
  }
  return { porPantalla, otros };
}

/**
 * One entry per catalog screen: `{ ...screen, acceso, adicionales }`, where
 * `adicionales` are the payload rows of its extra permissions (they never
 * change `acceso`). ctx: { rol, paresDelegados }. reglas: see
 * `pantallasDeAdicional`.
 */
export function construirVistaPorPantalla(permisosDetallados, { rol, paresDelegados }, catalogo, reglas = {}) {
  const permisos = indexarPermisos(permisosDetallados);
  const ctx = {
    esSuperadmin: rol === 'SUPERADMIN',
    esFullView: esFullView({ rol, permisos }),
    paresDelegados,
  };
  const { porPantalla } = repartirAdicionales(permisos, catalogo, reglas);
  return catalogo.map((screen) => ({
    ...screen,
    acceso: accesoPantalla(screen, permisos, ctx),
    adicionales: porPantalla.get(screen.path),
  }));
}

/** Payload permissions with no screen at all ("Otros permisos"), so they stay editable. */
export function otrosPermisos(permisosDetallados, catalogo, reglas = {}) {
  return repartirAdicionales(indexarPermisos(permisosDetallados), catalogo, reglas).otros;
}

/** Lower-case, accent-free form used by every search comparison. */
export function normalizar(texto) {
  return String(texto ?? '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase();
}

function textoPermiso(fila) {
  return [fila.codigo, fila.nombre, fila.descripcion].map(normalizar).join(' ');
}

// Access rows plus extras: what search, con_overrides and criticos look at.
const filasConAdicionales = (item) => [...item.acceso.filas, ...(item.adicionales || [])];

/**
 * Search over screen label/path/section and the codigo/nombre/descripcion of
 * its access permissions and its extras.
 */
export function coincideBusqueda(item, busqueda) {
  const q = normalizar(busqueda).trim();
  if (!q) return true;
  const textoPantalla = [item.label, item.path, item.section].map(normalizar).join(' ');
  if (textoPantalla.includes(q)) return true;
  return filasConAdicionales(item).some((fila) => textoPermiso(fila).includes(q));
}

/** Search over a single permission (the "Otros permisos" group). */
export function permisoCoincideBusqueda(permiso, busqueda) {
  const q = normalizar(busqueda).trim();
  if (!q) return true;
  return `${textoPermiso(permiso)} ${normalizar(permiso.categoria)}`.includes(q);
}

/**
 * Screen filters. `sin_acceso` is the screen status only (an extra never
 * decides access); `con_overrides` and `criticos` also look at the extras.
 */
export function cumpleFiltro(item, filtro) {
  switch (filtro) {
    case 'sin_acceso':
      return item.acceso.status === STATUS.SIN_ACCESO;
    case 'con_overrides':
      return filasConAdicionales(item).some((fila) => fila.override !== null && fila.override !== undefined);
    case 'criticos':
      return filasConAdicionales(item).some((fila) => fila.es_critico);
    case 'depende_de_datos':
      return item.scope === 'data';
    default:
      return true;
  }
}

/** Same predicates applied to a permission with no screen ("Otros permisos"). */
export function permisoCumpleFiltro(permiso, filtro) {
  switch (filtro) {
    case 'sin_acceso':
      return !permiso.efectivo;
    case 'con_overrides':
      return permiso.override !== null && permiso.override !== undefined;
    case 'criticos':
      return Boolean(permiso.es_critico);
    case 'depende_de_datos':
      return false;
    default:
      return true;
  }
}

/**
 * Chip counts = rows each filter would list: matching screens (each once, its
 * extras included) plus matching "Otros permisos" rows, so a chip never shows
 * fewer than what it lists.
 */
export function contarFiltros(items, sueltos = []) {
  return Object.fromEntries(
    FILTROS.map((filtro) => [
      filtro,
      items.filter((i) => cumpleFiltro(i, filtro)).length +
        sueltos.filter((p) => permisoCumpleFiltro(p, filtro)).length,
    ]),
  );
}

const ACCESIBLE = new Set([STATUS.ACCEDE, STATUS.PUBLICA]);

/** Groups by `section` keeping first-seen order; `accesibles` excludes condicional. */
export function agruparPorSeccion(items) {
  const grupos = new Map();
  for (const item of items) {
    if (!grupos.has(item.section)) grupos.set(item.section, { section: item.section, items: [] });
    grupos.get(item.section).items.push(item);
  }
  return [...grupos.values()].map((grupo) => ({
    ...grupo,
    total: grupo.items.length,
    accesibles: grupo.items.filter((i) => ACCESIBLE.has(i.acceso.status)).length,
  }));
}

/**
 * KPI summary of one user's screen view (`construirVistaPorPantalla`): the
 * same statuses the screen list shows, so both always agree. `accesibles`
 * uses the same rule as the section counts (accede + publica).
 */
export function resumenAcceso(vista) {
  const contar = (status) => vista.filter((item) => item.acceso.status === status).length;
  return {
    total: vista.length,
    accesibles: vista.filter((item) => ACCESIBLE.has(item.acceso.status)).length,
    sinAcceso: contar(STATUS.SIN_ACCESO),
    condicionales: contar(STATUS.CONDICIONAL),
  };
}

/** Overrides in the payload: `override: true` adds a permission, `false` removes it. */
export function contarOverrides(permisosDetallados) {
  const permisos = [...indexarPermisos(permisosDetallados).values()];
  const agregados = permisos.filter((p) => p.override === true).length;
  const quitados = permisos.filter((p) => p.override === false).length;
  return { agregados, quitados, total: agregados + quitados };
}

/**
 * Pairs that feed `pm_scope` for one user: titular pairs (`GET /marcas-pm`, an
 * array of { usuario_id }) plus delegated sub-PM grants
 * (`GET /marcas-pm/sub-pms/conteos` -> { conteos: [{ usuario_id, total }] }).
 * In `conteos`, `usuario_id` is the GRANTEE (`marca_sub_pm.usuario_id`, the
 * same column pm_scope reads) and `total` is how many pairs were delegated TO
 * that user, counted within the caller's writable pairs. Both endpoints are
 * complete only for ADMIN/SUPERADMIN callers; `/marcas-pm` 403s for anyone
 * else, which leaves the count unknown (null) instead of undercounting.
 * Only "zero vs. some" matters, so a pair held both ways counting twice is fine.
 * Returns null (unknown) on any unexpected shape: callers never claim
 * `condicional` without a known zero.
 */
export function contarParesEfectivos(pares, conteosResponse, usuarioId) {
  if (!Array.isArray(pares) || !Array.isArray(conteosResponse?.conteos)) return null;
  const titular = pares.filter((par) => par.usuario_id === usuarioId).length;
  const delegados = conteosResponse.conteos.find((c) => c.usuario_id === usuarioId)?.total ?? 0;
  return titular + delegados;
}

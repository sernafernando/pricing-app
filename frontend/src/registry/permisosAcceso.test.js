import { describe, it, expect } from 'vitest';
import {
  PERMISO_FULL_VIEW,
  esFullView,
  indexarPermisos,
  accesoPantalla,
  construirVistaPorPantalla,
  coincideBusqueda,
  cumpleFiltro,
  contarFiltros,
  permisosSinPantalla,
  agruparPorSeccion,
  contarParesEfectivos,
} from './permisosAcceso';

// Shape of GET /permisos/usuario/{id} -> permisos_detallados.
function permiso(codigo, overrides = {}) {
  return {
    codigo,
    nombre: `Nombre ${codigo}`,
    descripcion: `Descripción ${codigo}`,
    es_critico: false,
    tiene_por_rol: false,
    override: null,
    efectivo: false,
    origen: 'sin_permiso',
    ...overrides,
  };
}

const delRol = (codigo, extra = {}) =>
  permiso(codigo, { tiene_por_rol: true, efectivo: true, origen: 'rol', ...extra });

const CATALOGO = [
  { path: '/productos', label: 'Productos', section: 'Productos', permisos: ['productos.ver'], scope: 'permiso' },
  { path: '/metricas-ml', label: 'Métricas ML', section: 'Reportes', permisos: ['ml_metricas.ver'], scope: 'data' },
  {
    path: '/consultas/ranking',
    label: 'Ranking productos',
    section: 'Reportes',
    permisos: ['consultas.ver_ranking', 'consultas.ver_mi_ranking'],
    scope: 'data',
    fullViewPermisos: ['consultas.ver_ranking'],
  },
  { path: '/novedades', label: 'Novedades', section: 'Reportes', permisos: [], scope: 'public' },
];

describe('esFullView (mirrors backend pm_scope.is_full_view)', () => {
  it('is true for SUPERADMIN, ADMIN and GERENTE roles', () => {
    for (const rol of ['SUPERADMIN', 'ADMIN', 'GERENTE']) {
      expect(esFullView({ rol, permisos: indexarPermisos({}) })).toBe(true);
    }
  });

  it('is true for any role holding the full-view permission effectively', () => {
    const permisos = indexarPermisos({ ventas_ml: [delRol(PERMISO_FULL_VIEW)] });
    expect(PERMISO_FULL_VIEW).toBe('ventas_ml.ver_todas_marcas');
    expect(esFullView({ rol: 'PRICING', permisos })).toBe(true);
  });

  it('is false when the full-view permission was removed by override', () => {
    const permisos = indexarPermisos({
      ventas_ml: [permiso(PERMISO_FULL_VIEW, { tiene_por_rol: true, override: false, origen: 'override_quitado' })],
    });
    expect(esFullView({ rol: 'PRICING', permisos })).toBe(false);
  });
});

describe('accesoPantalla', () => {
  const ctx = { esFullView: false, paresDelegados: 3, esSuperadmin: false };

  it('marks a screen without permissions as publica', () => {
    const acceso = accesoPantalla(CATALOGO[3], indexarPermisos({}), ctx);
    expect(acceso.status).toBe('publica');
    expect(acceso.filas).toEqual([]);
  });

  it('grants access when any listed permission is effective, with the granting origin', () => {
    const permisos = indexarPermisos({
      consultas: [permiso('consultas.ver_ranking'), permiso('consultas.ver_mi_ranking', {
        override: true, efectivo: true, origen: 'override_agregado',
      })],
    });
    const acceso = accesoPantalla(CATALOGO[2], permisos, ctx);
    expect(acceso.status).toBe('accede');
    expect(acceso.origen).toBe('override_agregado');
    expect(acceso.filas.map((f) => [f.codigo, f.origen])).toEqual([
      ['consultas.ver_ranking', 'sin_permiso'],
      ['consultas.ver_mi_ranking', 'override_agregado'],
    ]);
  });

  it('reports sin_acceso with origin override_quitado when an override removed it', () => {
    const permisos = indexarPermisos({
      productos: [permiso('productos.ver', { tiene_por_rol: true, override: false, origen: 'override_quitado' })],
    });
    const acceso = accesoPantalla(CATALOGO[0], permisos, ctx);
    expect(acceso.status).toBe('sin_acceso');
    expect(acceso.origen).toBe('override_quitado');
  });

  it('reports sin_acceso with origin sin_permiso when nobody grants it', () => {
    const acceso = accesoPantalla(CATALOGO[0], indexarPermisos({ productos: [permiso('productos.ver')] }), ctx);
    expect(acceso.status).toBe('sin_acceso');
    expect(acceso.origen).toBe('sin_permiso');
  });

  it('flags a permission missing from the payload instead of crashing', () => {
    const acceso = accesoPantalla(CATALOGO[0], indexarPermisos({}), ctx);
    expect(acceso.status).toBe('sin_acceso');
    expect(acceso.filas[0]).toMatchObject({ codigo: 'productos.ver', desconocido: true, efectivo: false });
  });

  it('is condicional for a data-scoped screen when the user has zero delegated pairs', () => {
    const permisos = indexarPermisos({ ventas_ml: [delRol('ml_metricas.ver')] });
    const acceso = accesoPantalla(CATALOGO[1], permisos, { ...ctx, paresDelegados: 0 });
    expect(acceso.status).toBe('condicional');
  });

  it('is accede for a data-scoped screen when the user has pairs', () => {
    const permisos = indexarPermisos({ ventas_ml: [delRol('ml_metricas.ver')] });
    expect(accesoPantalla(CATALOGO[1], permisos, { ...ctx, paresDelegados: 2 }).status).toBe('accede');
  });

  it('never claims condicional when the pair count is unknown (null)', () => {
    const permisos = indexarPermisos({ ventas_ml: [delRol('ml_metricas.ver')] });
    expect(accesoPantalla(CATALOGO[1], permisos, { ...ctx, paresDelegados: null }).status).toBe('accede');
  });

  it('never claims condicional for a full-view user', () => {
    const permisos = indexarPermisos({ ventas_ml: [delRol('ml_metricas.ver')] });
    expect(
      accesoPantalla(CATALOGO[1], permisos, { ...ctx, esFullView: true, paresDelegados: 0 }).status,
    ).toBe('accede');
  });

  it('uses the screen-specific full-view permissions when the screen declares them', () => {
    const conRankingCompleto = indexarPermisos({ consultas: [delRol('consultas.ver_ranking')] });
    expect(
      accesoPantalla(CATALOGO[2], conRankingCompleto, { ...ctx, paresDelegados: 0 }).status,
    ).toBe('accede');

    // A full-view ROLE does not bypass the ranking scope: only the permission does.
    const soloMiRanking = indexarPermisos({ consultas: [delRol('consultas.ver_mi_ranking')] });
    expect(
      accesoPantalla(CATALOGO[2], soloMiRanking, { ...ctx, esFullView: true, paresDelegados: 0 }).status,
    ).toBe('condicional');
  });

  it('shows every screen as accede for a SUPERADMIN target', () => {
    const acceso = accesoPantalla(CATALOGO[1], indexarPermisos({}), {
      ...ctx, esSuperadmin: true, paresDelegados: 0,
    });
    expect(acceso.status).toBe('accede');
    expect(acceso.origen).toBe('superadmin');
  });
});

describe('construirVistaPorPantalla + filters + search', () => {
  const detallados = {
    productos: [permiso('productos.ver', { es_critico: true })],
    ventas_ml: [delRol('ml_metricas.ver')],
    consultas: [
      permiso('consultas.ver_ranking'),
      permiso('consultas.ver_mi_ranking', { override: true, efectivo: true, origen: 'override_agregado' }),
    ],
    admin: [permiso('admin.sincronizar', { es_critico: true })],
  };
  const ctx = { rol: 'PRICING', paresDelegados: 0 };
  const vista = construirVistaPorPantalla(detallados, ctx, CATALOGO);

  it('builds one entry per catalog screen with its status', () => {
    expect(vista.map((v) => [v.path, v.acceso.status])).toEqual([
      ['/productos', 'sin_acceso'],
      ['/metricas-ml', 'condicional'],
      ['/consultas/ranking', 'condicional'],
      ['/novedades', 'publica'],
    ]);
  });

  it('filters sin acceso, con overrides, críticos and depende de datos', () => {
    const paths = (filtro) => vista.filter((v) => cumpleFiltro(v, filtro)).map((v) => v.path);
    expect(paths('todo')).toHaveLength(4);
    expect(paths('sin_acceso')).toEqual(['/productos']);
    expect(paths('con_overrides')).toEqual(['/consultas/ranking']);
    expect(paths('criticos')).toEqual(['/productos']);
    expect(paths('depende_de_datos')).toEqual(['/metricas-ml', '/consultas/ranking']);
  });

  it('counts every filter', () => {
    expect(contarFiltros(vista)).toEqual({
      todo: 4, sin_acceso: 1, con_overrides: 1, criticos: 1, depende_de_datos: 2,
    });
  });

  it('searches label, path, section and permission fields ignoring case and accents', () => {
    const buscar = (q) => vista.filter((v) => coincideBusqueda(v, q)).map((v) => v.path);
    expect(buscar('METRICAS')).toEqual(['/metricas-ml']);
    expect(buscar('/consultas')).toEqual(['/consultas/ranking']);
    expect(buscar('reportes')).toEqual(['/metricas-ml', '/consultas/ranking', '/novedades']);
    expect(buscar('ver_mi_ranking')).toEqual(['/consultas/ranking']);
    expect(buscar('descripcion productos.ver')).toEqual(['/productos']);
    expect(buscar('   ')).toHaveLength(4);
  });

  it('groups by section in catalog order with accessible counts', () => {
    const grupos = agruparPorSeccion(vista);
    expect(grupos.map((g) => [g.section, g.accesibles, g.total])).toEqual([
      ['Productos', 0, 1],
      // condicional counts as not accessible; publica counts as accessible
      ['Reportes', 1, 3],
    ]);
  });

  it('lists payload permissions no screen references, with their category', () => {
    const sueltos = permisosSinPantalla(detallados, CATALOGO);
    expect(sueltos.map((p) => [p.codigo, p.categoria])).toEqual([['admin.sincronizar', 'admin']]);
  });
});

describe('contarParesEfectivos (pm_scope effective scope = titular UNION sub-PM)', () => {
  const pares = [
    { marca: 'A', categoria: 'X', usuario_id: 7 },
    { marca: 'B', categoria: 'X', usuario_id: 8 },
  ];

  it('adds titular pairs and delegated sub-PM grants of the user', () => {
    expect(contarParesEfectivos(pares, { conteos: [{ usuario_id: 7, total: 2 }] }, 7)).toBe(3);
  });

  it('is zero when the user is neither titular nor sub-PM', () => {
    expect(contarParesEfectivos(pares, { conteos: [{ usuario_id: 8, total: 5 }] }, 9)).toBe(0);
  });

  it('is unknown (null) when a response has an unexpected shape', () => {
    expect(contarParesEfectivos(null, { conteos: [] }, 7)).toBeNull();
    expect(contarParesEfectivos(pares, {}, 7)).toBeNull();
  });
});

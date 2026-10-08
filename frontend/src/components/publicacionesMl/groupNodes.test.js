/**
 * The one reader of `GET /ml-publications/view/groups` (publicaciones-ml-vista
 * P12a): node fields, the node aggregates that only exist with `ver_ganancia`,
 * and the requests the tree makes.
 */
import { describe, it, expect } from 'vitest';
import {
  GROUPS_PAGE,
  buildGroupsParams,
  buildLeafParams,
  readGroupsPage,
  readNode,
} from './groupNodes';

const RAW_BRAND = {
  kind: 'marca',
  key: 'TP%2CLINK',
  label: 'TP,LINK',
  count: 12,
  leaf: false,
  params: { marcas: 'TP%2CLINK' },
};

describe('readNode', () => {
  it('keeps the key exactly as it came and shows the label', () => {
    const node = readNode(RAW_BRAND, { canSeeMargin: false });
    expect(node.key).toBe('TP%2CLINK');
    expect(node.label).toBe('TP,LINK');
    expect(node.count).toBe(12);
    expect(node.leaf).toBe(false);
    expect(node.params).toEqual({ marcas: 'TP%2CLINK' });
  });

  it('falls back to the decoded key when the label is empty', () => {
    expect(readNode({ ...RAW_BRAND, label: '' }, { canSeeMargin: false }).label).toBe('TP,LINK');
    expect(readNode({ ...RAW_BRAND, label: null }, { canSeeMargin: false }).label).toBe('TP,LINK');
  });

  it('flags the "Sin producto" node', () => {
    const none = readNode(
      { kind: 'producto', key: '__none__', label: 'Sin producto', count: 3, leaf: true, params: { sin_producto: 'true' } },
      { canSeeMargin: false },
    );
    expect(none.withoutProduct).toBe(true);
    expect(readNode(RAW_BRAND, { canSeeMargin: false }).withoutProduct).toBe(false);
  });

  it('reads the aggregates only with ver_ganancia', () => {
    const raw = { ...RAW_BRAND, negative_count: 2, markup_min: -4.2, markup_max: 31.5 };
    expect(readNode(raw, { canSeeMargin: true })).toMatchObject({ negativeCount: 2, markup: { min: -4.2, max: 31.5 } });
    const hidden = readNode(raw, { canSeeMargin: false });
    expect(hidden.negativeCount).toBeNull();
    expect(hidden.markup).toBeNull();
  });

  it('never invents an aggregate the backend did not send', () => {
    const node = readNode(RAW_BRAND, { canSeeMargin: true });
    expect(node.negativeCount).toBeNull();
    expect(node.markup).toBeNull();
  });

  it('keeps a real 0 and a null-only range apart from a missing field', () => {
    const zero = readNode({ ...RAW_BRAND, negative_count: 0, markup_min: 0, markup_max: 0 }, { canSeeMargin: true });
    expect(zero.negativeCount).toBe(0);
    expect(zero.markup).toEqual({ min: 0, max: 0 });
    const nullOnly = readNode({ ...RAW_BRAND, negative_count: 0, markup_min: null, markup_max: null }, { canSeeMargin: true });
    expect(nullOnly.negativeCount).toBe(0);
    expect(nullOnly.markup).toEqual({ min: null, max: null });
  });

  it('carries the product, family and item ids when present', () => {
    const node = readNode(
      { kind: 'familia', key: '7001', label: 'Archer', count: 2, leaf: true, params: { familia: '7001' }, family_id: 7001 },
      { canSeeMargin: false },
    );
    expect(node.familyId).toBe(7001);
    expect(node.itemId).toBeNull();
  });
});

describe('readGroupsPage', () => {
  it('reads the level, the nodes and the total', () => {
    const page = readGroupsPage({ level: 'marca', path: [], nodes: [RAW_BRAND], total: 150, limit: 100, offset: 0, familias: false }, { canSeeMargin: false });
    expect(page.level).toBe('marca');
    expect(page.nodes).toHaveLength(1);
    expect(page.total).toBe(150);
  });

  it('tolerates a body without nodes', () => {
    expect(readGroupsPage({}, { canSeeMargin: false })).toEqual({ level: null, nodes: [], total: 0 });
  });
});

describe('buildGroupsParams', () => {
  const filters = {
    q: ' router ',
    familia: '',
    evento_desde: '',
    estado: ['active'],
    estado_excluir: [],
    tiendas: ['57997', 'sin_tienda'],
    marcas: [],
    categorias: [],
    subcategorias: [],
    pms: [],
    tipo: [],
    vinculo: [],
    stock: [],
    evento: [],
    markup_neg: '1',
    markup_min: '5',
    markup_max: '',
    orden: 'precio',
    dir: 'asc',
    pagina: 3,
    limite: 25,
  };

  it('sends the user filters, the path as it came and the page, nothing of the list view', () => {
    expect(buildGroupsParams(filters, { path: ['TP%2CLINK', 'CAT'], familias: false, offset: 100 })).toEqual({
      q: 'router',
      estado: 'active',
      tiendas: '57997,none',
      path: 'TP%2CLINK,CAT',
      familias: false,
      limit: GROUPS_PAGE,
      offset: 100,
    });
  });

  it('sends no path for the roots and asks for families when the toggle is on', () => {
    const params = buildGroupsParams(filters, { path: [], familias: true, offset: 0 });
    expect(params).not.toHaveProperty('path');
    expect(params.familias).toBe(true);
    expect(params.offset).toBe(0);
  });
});

describe('buildLeafParams', () => {
  const filters = {
    q: 'router',
    familia: '',
    evento_desde: '',
    estado: ['active'],
    estado_excluir: [],
    tiendas: ['57997'],
    marcas: ['EPSON'],
    categorias: [],
    subcategorias: [],
    pms: [],
    tipo: [],
    vinculo: [],
    stock: [],
    evento: [],
    markup_neg: '',
    markup_min: '',
    markup_max: '',
    orden: '',
    dir: '',
    pagina: 1,
    limite: 50,
  };
  const node = { params: { marcas: 'TP%2CLINK', producto: '4101' } };

  it("merges the node's params over the user's own and pages by 100", () => {
    expect(buildLeafParams(filters, node, 100)).toEqual({
      q: 'router',
      estado: 'active',
      tiendas: '57997',
      marcas: 'TP%2CLINK',
      producto: '4101',
      limit: GROUPS_PAGE,
      offset: 100,
    });
  });
});

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TreeNode from './TreeNode';
import { promocionesAPI } from '../../services/api';
import { useTreeViewStore } from '../../store/treeViewStore';
import { seedTiendasOficiales } from '../../test/tiendasOficialesFixtures';

// Mock the leaf promo panel so prop-threading assertions can inspect exactly
// what reaches it, without depending on its own fetch/reload internals.
vi.mock('./MlaPromocionesPanel', () => ({
  default: (props) => (
    <div
      data-testid={`mla-promos-${props.mla}`}
      data-props={JSON.stringify(Object.keys(props).sort())}
      data-pull-on-open={String(props.pullOnOpen)}
    >
      mocked-promos-for-{props.mla}
    </div>
  ),
}));

vi.mock('./CatalogCompetitionPanel', () => ({
  default: (props) => (
    <div
      data-testid={`catalog-competition-${props.mla}`}
      data-has-cache-ref={props.catalogCompetitionCacheRef ? 'yes' : 'no'}
    >
      mocked-catalog-competition-for-{props.mla}
    </div>
  ),
}));

vi.mock('./PxqPanel', () => ({
  default: (props) => (
    <div data-testid={`pxq-${props.itemId}`} data-has-cache-ref={props.pxqCacheRef ? 'yes' : 'no'}>
      mocked-pxq-for-{props.itemId}
    </div>
  ),
}));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(() => Promise.resolve({ data: [] })) },
  promocionesAPI: {
    refreshItemPromociones: vi.fn(),
    confirmarSinPromosML: vi.fn(() => Promise.resolve({ data: { sin_promos_confirmado: true, promos_en_ml: 0 } })),
  },
}));

// Refresh button is gated on `promos.escribir`; default the mock to granted so
// existing button tests render it, and flip it in the gating test.
const { mockTienePermiso } = vi.hoisted(() => ({ mockTienePermiso: vi.fn(() => true) }));
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: mockTienePermiso }),
}));

function renderNode(node, props = {}) {
  const mlasCacheRef = { current: new Map() };
  const promosCacheRef = { current: new Map() };
  const catalogCompetitionCacheRef = { current: new Map() };
  const pxqCacheRef = { current: new Map() };
  return render(
    <table>
      <tbody>
        <TreeNode
          node={node}
          colSpan={5}
          mlasCacheRef={mlasCacheRef}
          promosCacheRef={promosCacheRef}
          catalogCompetitionCacheRef={catalogCompetitionCacheRef}
          pxqCacheRef={pxqCacheRef}
          promoTipos={[]}
          promoEstado="disponible"
          {...props}
        />
      </tbody>
    </table>,
  );
}

// A 4-level-deep tree: familia -> catalogo -> vinculada -> vinculada (nested).
function buildDeepTree() {
  return {
    level: 1,
    kind: 'familia',
    family_id: 'FAM1',
    label: 'Familia FAM1',
    children: [
      {
        level: 2,
        kind: 'catalogo',
        mla: 'MLA_CAT',
        catalog_product_id: 'CAT1',
        label: 'MLA_CAT',
        matches_filter: true,
        children: [
          {
            level: 3,
            kind: 'vinculada',
            mla: 'MLA_VINC1',
            label: 'MLA_VINC1',
            matches_filter: true,
            children: [
              {
                level: 4,
                kind: 'vinculada',
                mla: 'MLA_VINC2',
                label: 'MLA_VINC2',
                matches_filter: true,
                children: [],
              },
            ],
          },
        ],
      },
    ],
  };
}

describe('TreeNode', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
    useTreeViewStore.setState({ showFamilia: false });
  });

  it('renders a familia grouping node with its label when showFamilia is enabled', () => {
    useTreeViewStore.setState({ showFamilia: true });
    renderNode(buildDeepTree());
    expect(screen.getByText(/familia fam1/i)).toBeInTheDocument();
  });

  it('hides the familia header and renders its children directly when showFamilia is disabled (default)', () => {
    renderNode(buildDeepTree());
    expect(screen.queryByText(/familia fam1/i)).not.toBeInTheDocument();
    // The familia's direct child (catalogo MLA_CAT) is hoisted up one level
    // and rendered immediately, without needing to expand the familia first.
    expect(screen.getByText('MLA_CAT')).toBeInTheDocument();
  });

  it('does not affect a catalogo node outside any familia, regardless of showFamilia', () => {
    const tree = {
      level: 1,
      kind: 'catalogo',
      mla: 'MLA_ROOT_CAT',
      label: 'MLA_ROOT_CAT',
      matches_filter: true,
      children: [],
    };
    renderNode(tree);
    expect(screen.getByText('MLA_ROOT_CAT')).toBeInTheDocument();
    expect(screen.getByText('Catálogo')).toBeInTheDocument();
  });

  it('recursively renders nested catalogo/vinculada kinds down to depth 4', async () => {
    useTreeViewStore.setState({ showFamilia: true });
    renderNode(buildDeepTree());
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: /expandir familia fam1/i }));
    expect(screen.getByText('MLA_CAT')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /expandir mla_cat/i }));
    expect(screen.getByText('MLA_VINC1')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /expandir mla_vinc1/i }));
    expect(screen.getByText('MLA_VINC2')).toBeInTheDocument();
  });

  it('renders catalogo and vinculada kinds with visually distinct badges (same-pricelist dup fix)', async () => {
    useTreeViewStore.setState({ showFamilia: true });
    renderNode(buildDeepTree());
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir familia fam1/i }));
    await user.click(screen.getByRole('button', { name: /expandir mla_cat/i }));

    // Exact, case-sensitive match on the KIND badge label — distinct from
    // the lowercase FE-computed child-kind count ("1 catálogo") a grouping
    // node's header may also render (catalog-tree-node-summary PR).
    expect(screen.getByText('Catálogo')).toBeInTheDocument();
    expect(screen.getByText('Vinculada')).toBeInTheDocument();
  });

  it('renders a plain publicacion leaf node', () => {
    renderNode({ level: 1, kind: 'publicacion', mla: 'MLA_PLAIN', label: 'MLA_PLAIN', matches_filter: true, children: [] });
    expect(screen.getByText('MLA_PLAIN')).toBeInTheDocument();
    expect(screen.getByText(/publicación/i)).toBeInTheDocument();
  });

  it('separates promos into their own sub-spoiler, distinct from vinculada child rows', async () => {
    const tree = {
      level: 2,
      kind: 'catalogo',
      mla: 'MLA_CAT',
      label: 'MLA_CAT',
      matches_filter: true,
      children: [
        { level: 3, kind: 'vinculada', mla: 'MLA_VINC1', label: 'MLA_VINC1', matches_filter: true, children: [] },
      ],
    };
    renderNode(tree);
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: /expandir mla_cat/i }));

    // The promos sub-spoiler is its own separate toggle, not the same
    // expand action as the vinculada child row.
    const promosToggle = screen.getByRole('button', { name: /^promociones/i });
    expect(promosToggle).toBeInTheDocument();
    expect(screen.getByText('MLA_VINC1')).toBeInTheDocument();
    expect(screen.queryByTestId('mla-promos-MLA_CAT')).not.toBeInTheDocument();

    await user.click(promosToggle);
    expect(screen.getByTestId('mla-promos-MLA_CAT')).toBeInTheDocument();
  });

  it('does not render a promos sub-spoiler for grouping nodes (familia has no mla)', async () => {
    useTreeViewStore.setState({ showFamilia: true });
    renderNode(buildDeepTree());
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir familia fam1/i }));
    expect(screen.queryByRole('button', { name: /^promociones/i })).not.toBeInTheDocument();
  });

  it('hides an MLA-bearing node when matches_filter is false and a filter is active', () => {
    const tree = {
      level: 1,
      kind: 'familia',
      label: 'Familia FAM1',
      children: [
        { level: 2, kind: 'catalogo', mla: 'MLA_SHOWN', label: 'MLA_SHOWN', matches_filter: true, children: [] },
        { level: 2, kind: 'catalogo', mla: 'MLA_HIDDEN', label: 'MLA_HIDDEN', matches_filter: false, children: [] },
      ],
    };
    renderNode(tree, { promoTipos: ['SELLER_CAMPAIGN'], promoEstado: 'aplicada' });

    expect(screen.getByText('MLA_SHOWN')).toBeInTheDocument();
    expect(screen.queryByText('MLA_HIDDEN')).not.toBeInTheDocument();
  });

  it('reveals matches_filter:false nodes when revealAll is true', () => {
    const tree = {
      level: 1,
      kind: 'familia',
      label: 'Familia FAM1',
      children: [
        { level: 2, kind: 'catalogo', mla: 'MLA_HIDDEN', label: 'MLA_HIDDEN', matches_filter: false, children: [] },
      ],
    };
    renderNode(tree, { promoTipos: ['SELLER_CAMPAIGN'], promoEstado: 'aplicada', revealAll: true });

    expect(screen.getByText('MLA_HIDDEN')).toBeInTheDocument();
  });

  it('treats matches_filter absent/null as show (fail-open) even when a filter is active', () => {
    const tree = {
      level: 1,
      kind: 'familia',
      label: 'Familia FAM1',
      children: [
        { level: 2, kind: 'catalogo', mla: 'MLA_NOFLAG', label: 'MLA_NOFLAG', children: [] },
      ],
    };
    renderNode(tree, { promoTipos: ['SELLER_CAMPAIGN'], promoEstado: 'aplicada' });

    expect(screen.getByText('MLA_NOFLAG')).toBeInTheDocument();
  });

  it('hides a grouping node entirely only when ALL descendant MLAs are filtered out', () => {
    const tree = {
      level: 1,
      kind: 'familia',
      label: 'Familia ALL_HIDDEN',
      children: [
        { level: 2, kind: 'catalogo', mla: 'MLA_A', label: 'MLA_A', matches_filter: false, children: [] },
        { level: 2, kind: 'catalogo', mla: 'MLA_B', label: 'MLA_B', matches_filter: false, children: [] },
      ],
    };
    renderNode(tree, { promoTipos: ['SELLER_CAMPAIGN'], promoEstado: 'aplicada' });
    expect(screen.queryByText(/familia all_hidden/i)).not.toBeInTheDocument();
  });

  it('forwards promoTipos, promoEstado, mlasCacheRef and promosCacheRef unchanged through every intermediate node down to the deepest leaf MlaPromocionesPanel', async () => {
    useTreeViewStore.setState({ showFamilia: true });
    const deepTree = buildDeepTree();
    const promoTipos = ['SELLER_CAMPAIGN', 'DEAL'];
    const promoEstado = 'aplicada';
    const mlasCacheRef = { current: new Map() };
    const promosCacheRef = { current: new Map() };

    render(
      <table>
        <tbody>
          <TreeNode
            node={deepTree}
            colSpan={5}
            mlasCacheRef={mlasCacheRef}
            promosCacheRef={promosCacheRef}
            promoTipos={promoTipos}
            promoEstado={promoEstado}
          />
        </tbody>
      </table>,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir familia fam1/i }));
    await user.click(screen.getByRole('button', { name: /expandir mla_cat/i }));
    await user.click(screen.getByRole('button', { name: /expandir mla_vinc1/i }));
    await user.click(screen.getByRole('button', { name: /expandir mla_vinc2/i }));
    const promoToggles = screen.getAllByRole('button', { name: /^promociones/i });
    // Deepest node's promos toggle is the last one rendered (catalogo, vinc1,
    // vinc2 are all open by now, each with its own separate promos toggle).
    await user.click(promoToggles[promoToggles.length - 1]);

    // Deepest MLA (MLA_VINC2, depth 4) — assert promosCacheRef made it there
    // by checking the mocked panel actually received a `promosCacheRef` prop.
    const leaf = screen.getByTestId('mla-promos-MLA_VINC2');
    const propKeys = JSON.parse(leaf.getAttribute('data-props'));
    expect(propKeys).toContain('promosCacheRef');
    expect(propKeys).toContain('mla');
  });
});

describe('TreeNode promo refresh button (per-MLA manual refresh)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
    useTreeViewStore.setState({ showFamilia: true });
  });

  function buildMlaTree() {
    return {
      level: 1,
      kind: 'familia',
      label: 'Familia FAM1',
      children: [
        { level: 2, kind: 'catalogo', mla: 'MLA_CAT', label: 'MLA_CAT', matches_filter: true, children: [] },
      ],
    };
  }

  async function expandToMla() {
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir familia fam1/i }));
    return user;
  }

  it('renders the refresh button on MLA-bearing nodes', async () => {
    renderNode(buildMlaTree());
    await expandToMla();
    expect(screen.getByRole('button', { name: /refrescar promociones de mla_cat/i })).toBeInTheDocument();
  });

  it('does not render the refresh button on grouping nodes (familia/catalogo without mla)', () => {
    renderNode(buildMlaTree());
    expect(screen.queryByRole('button', { name: /refrescar promociones/i })).not.toBeInTheDocument();
  });

  it('hides the refresh button when the user lacks promos.escribir', async () => {
    mockTienePermiso.mockReturnValue(false);
    renderNode(buildMlaTree());
    await expandToMla();
    expect(screen.queryByRole('button', { name: /refrescar promociones/i })).not.toBeInTheDocument();
  });

  it('calls the refresh API with the node mla on click', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    renderNode(buildMlaTree());
    const user = await expandToMla();

    await user.click(screen.getByRole('button', { name: /refrescar promociones de mla_cat/i }));

    expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledWith('MLA_CAT');
  });

  it('disables the button while the refresh is in-flight', async () => {
    let resolvePromise;
    promocionesAPI.refreshItemPromociones.mockReturnValue(
      new Promise((resolve) => {
        resolvePromise = resolve;
      }),
    );
    renderNode(buildMlaTree());
    const user = await expandToMla();

    const button = screen.getByRole('button', { name: /refrescar promociones de mla_cat/i });
    await user.click(button);

    expect(button).toBeDisabled();
    expect(screen.getByText(/refrescando/i)).toBeInTheDocument();

    resolvePromise({ data: { ok: true } });
  });

  it('invalidates the promos cache entry on success', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    const promosCacheRef = { current: new Map([['MLA_CAT', { status: 'ok', data: { promotions: [] } }]]) };
    renderNode(buildMlaTree(), { promosCacheRef });
    const user = await expandToMla();

    await user.click(screen.getByRole('button', { name: /refrescar promociones de mla_cat/i }));

    await screen.findByRole('button', { name: /refrescar promociones de mla_cat/i });
    expect(promosCacheRef.current.has('MLA_CAT')).toBe(false);
  });

  it('reloads the open promos panel by remounting it after a successful refresh', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    renderNode(buildMlaTree());
    const user = await expandToMla();

    await user.click(screen.getByRole('button', { name: /expandir mla_cat/i }));
    await user.click(screen.getByRole('button', { name: /^promociones/i }));
    expect(screen.getByTestId('mla-promos-MLA_CAT')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /refrescar promociones de mla_cat/i }));

    // Still rendered (remounted via key bump), not removed.
    expect(await screen.findByTestId('mla-promos-MLA_CAT')).toBeInTheDocument();
  });

  it('shows a soft inline error on refresh failure ({ok: false})', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: false } });
    renderNode(buildMlaTree());
    const user = await expandToMla();

    await user.click(screen.getByRole('button', { name: /refrescar promociones de mla_cat/i }));

    expect(await screen.findByText(/no se pudo refrescar/i)).toBeInTheDocument();
  });

  it('shows a soft inline error when the API call rejects', async () => {
    promocionesAPI.refreshItemPromociones.mockRejectedValue(new Error('network error'));
    renderNode(buildMlaTree());
    const user = await expandToMla();

    await user.click(screen.getByRole('button', { name: /refrescar promociones de mla_cat/i }));

    expect(await screen.findByText(/no se pudo refrescar/i)).toBeInTheDocument();
  });
});

describe('TreeNode collapsed-node promo summary (catalog-tree-node-summary PR)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
    useTreeViewStore.setState({ showFamilia: false });
  });

  it('renders the applied badge, counts and price for an MLA-bearing node with a promo_summary', () => {
    const tree = {
      level: 1,
      kind: 'catalogo',
      mla: 'MLA_SUM',
      label: 'MLA_SUM',
      matches_filter: true,
      children: [],
      promo_summary: {
        started_count: 1,
        candidate_count: 2,
        applied_name: 'Oferta Relámpago',
        applied_price: 850,
      },
    };
    renderNode(tree);

    expect(screen.getByText(/aplicada: oferta relámpago/i)).toBeInTheDocument();
    expect(screen.getByText(/1 aplicada.*2 disponible/i)).toBeInTheDocument();
    expect(screen.getByText(/850/)).toBeInTheDocument();
  });

  it('renders nothing extra for an MLA-bearing node without a promo_summary (fail-open)', () => {
    const tree = {
      level: 1,
      kind: 'catalogo',
      mla: 'MLA_NOSUM',
      label: 'MLA_NOSUM',
      matches_filter: true,
      children: [],
    };
    renderNode(tree);

    expect(screen.queryByText(/aplicada:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/disponible/i)).not.toBeInTheDocument();
  });

  it('shows the counts even when no promo is currently applied (started_count 0)', () => {
    const tree = {
      level: 1,
      kind: 'catalogo',
      mla: 'MLA_SUM2',
      label: 'MLA_SUM2',
      matches_filter: true,
      children: [],
      promo_summary: {
        started_count: 0,
        candidate_count: 3,
        applied_name: null,
        applied_price: null,
      },
    };
    renderNode(tree);

    expect(screen.getByText(/0 aplicada.*3 disponible/i)).toBeInTheDocument();
    expect(screen.queryByText(/aplicada:/i)).not.toBeInTheDocument();
  });

  it('shows a FE-computed child-kind count for a grouping node with children', () => {
    useTreeViewStore.setState({ showFamilia: true });
    const tree = {
      level: 1,
      kind: 'familia',
      family_id: 'FAM1',
      label: 'Familia FAM1',
      children: [
        { level: 2, kind: 'catalogo', mla: 'MLA_A', label: 'MLA_A', matches_filter: true, children: [] },
        { level: 2, kind: 'catalogo', mla: 'MLA_B', label: 'MLA_B', matches_filter: true, children: [] },
        { level: 2, kind: 'vinculada', mla: 'MLA_C', label: 'MLA_C', matches_filter: true, children: [] },
      ],
    };
    renderNode(tree);

    expect(screen.getByText(/2 cat[aá]logos/i)).toBeInTheDocument();
    expect(screen.getByText(/1 vinculada/i)).toBeInTheDocument();
  });

  it('does not show a child-kind count for a leaf grouping node (no children)', () => {
    useTreeViewStore.setState({ showFamilia: true });
    const tree = { level: 1, kind: 'familia', family_id: 'FAM_EMPTY', label: 'Familia FAM_EMPTY', children: [] };
    renderNode(tree);

    expect(screen.queryByText(/cat[aá]logo/i)).not.toBeInTheDocument();
  });
});

describe('TreeNode price-list badge (restores old flat panel lista_nombre)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
  });

  it('renders the lista_nombre badge for an MLA-bearing node', () => {
    const tree = {
      level: 1,
      kind: 'publicacion',
      mla: 'MLA_LISTA',
      label: 'MLA_LISTA',
      matches_filter: true,
      children: [],
      lista_nombre: '3 Cuotas',
      pricelist_id: 17,
    };
    renderNode(tree);

    expect(screen.getByText('3 Cuotas')).toBeInTheDocument();
  });

  it('falls back to getPublicationTypeLabel(pricelist_id) when lista_nombre is absent', () => {
    const tree = {
      level: 1,
      kind: 'publicacion',
      mla: 'MLA_NOLISTA',
      label: 'MLA_NOLISTA',
      matches_filter: true,
      children: [],
      lista_nombre: null,
      pricelist_id: 4,
    };
    renderNode(tree);

    expect(screen.getByText('Clásica')).toBeInTheDocument();
  });

  it('renders nothing extra when both lista_nombre and pricelist_id are absent (fail-open)', () => {
    const tree = {
      level: 1,
      kind: 'publicacion',
      mla: 'MLA_NONE',
      label: 'MLA_NONE',
      matches_filter: true,
      children: [],
    };
    renderNode(tree);

    expect(screen.queryByText(/desconocido/i)).not.toBeInTheDocument();
  });
});

describe('TreeNode publication status badge (from ml_items.status)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
    useTreeViewStore.setState({ showFamilia: false });
  });

  function buildStatusNode(publication_status) {
    return {
      level: 1,
      kind: 'publicacion',
      mla: 'MLA_STATUS',
      label: 'MLA_STATUS',
      matches_filter: true,
      children: [],
      publication_status,
    };
  }

  it('renders the paused badge for an MLA-bearing node', () => {
    renderNode(buildStatusNode('paused'));

    expect(screen.getByText(/pausada/i)).toBeInTheDocument();
  });

  it('uses the shared Publicaciones ML labels for every ml_items status', () => {
    const cases = [
      ['active', 'Activa'],
      ['closed', 'Cerrada'],
      ['under_review', 'En revisión'],
      ['inactive', 'Inactiva'],
      ['gone', 'Eliminada'],
      ['never_existed', 'No existe en ML'],
    ];
    cases.forEach(([status, label]) => {
      const { unmount } = renderNode(buildStatusNode(status), { showDeleted: true }); // 'gone' is hidden otherwise
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    });
  });

  it('says "Sin datos de ML" (never "Activa") when ml_items has no row for the MLA', () => {
    renderNode(buildStatusNode('no_ml_data'));

    expect(screen.getByText('Sin datos de ML')).toBeInTheDocument();
    expect(screen.queryByText('Activa')).not.toBeInTheDocument();
  });

  it('shows the ML sub_status reasons as the chip tooltip', () => {
    renderNode({ ...buildStatusNode('paused'), publication_sub_status: ['paused_by_seller'] });

    expect(screen.getByText('Pausada').closest('span')).toHaveAttribute('title', 'paused_by_seller');
  });

  it('says "Eliminada" for a publication ML keeps inactive with the deleted reason, with ML\'s reasons as tooltip', () => {
    renderNode({ ...buildStatusNode('inactive'), publication_sub_status: ['forbidden', 'deleted'] }, { showDeleted: true });

    expect(screen.getByText('Eliminada').closest('span')).toHaveAttribute('title', 'forbidden, deleted');
    expect(screen.queryByText('Inactiva')).not.toBeInTheDocument();
  });

  it('shows the live publications of a hidden deleted catalog one level up', () => {
    renderNode({
      level: 1,
      kind: 'catalogo',
      mla: 'MLA_CAT',
      label: 'MLA_CAT',
      publication_status: 'gone',
      matches_filter: true,
      children: [{ level: 2, kind: 'vinculada', mla: 'MLA_VIN', label: 'MLA_VIN', publication_status: 'active', matches_filter: true, children: [] }],
    });
    expect(screen.queryByText('MLA_CAT')).not.toBeInTheDocument();
    expect(screen.getByText('MLA_VIN')).toBeInTheDocument();
  });

  it('renders nothing for a deleted publication unless deleted ones are shown', () => {
    renderNode({ ...buildStatusNode('inactive'), publication_sub_status: ['deleted'] });
    expect(screen.queryByText('Eliminada')).not.toBeInTheDocument();
    expect(screen.queryByRole('row')).not.toBeInTheDocument();
  });

  it('renders no status badge when publication_status is absent (store read failed)', () => {
    renderNode(buildStatusNode(undefined));

    expect(screen.queryByText(/activa|pausada|cerrada|en revisión|sin datos de ml/i)).not.toBeInTheDocument();
  });

  it('shows an unknown ML status verbatim instead of hiding it', () => {
    renderNode(buildStatusNode('payment_required'));

    expect(screen.getByText('payment_required')).toBeInTheDocument();
  });

  it('never renders a status badge on a familia grouping node', () => {
    useTreeViewStore.setState({ showFamilia: true });
    const tree = {
      level: 1,
      kind: 'familia',
      family_id: 'FAM_STATUS',
      label: 'Familia FAM_STATUS',
      publication_status: 'paused',
      children: [],
    };
    renderNode(tree);

    expect(screen.getByText(/familia fam_status/i)).toBeInTheDocument();
    expect(screen.queryByText(/pausada/i)).not.toBeInTheDocument();
  });
});

describe('TreeNode official store badge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    seedTiendasOficiales([{ store_id: 57997, nombre: 'Gauss Renombrada', clave: null, orden: 0, activa: true }]);
    mockTienePermiso.mockReturnValue(true);
    useTreeViewStore.setState({ showFamilia: false });
  });

  function buildStoreNode(officialStoreId) {
    return {
      level: 1,
      kind: 'publicacion',
      mla: 'MLA_STORE',
      label: 'MLA_STORE',
      official_store_id: officialStoreId,
      children: [],
    };
  }

  it('renders the admin-defined name for a known store id', () => {
    renderNode(buildStoreNode(57997));

    expect(screen.getByText('Gauss Renombrada')).toBeInTheDocument();
  });

  it('renders "Tienda <id>" for an unknown store id', () => {
    renderNode(buildStoreNode(999999));

    expect(screen.getByText('Tienda 999999')).toBeInTheDocument();
  });

  it('renders "Sin tienda" when official_store_id is null', () => {
    renderNode(buildStoreNode(null));

    expect(screen.getByText(/sin tienda/i)).toBeInTheDocument();
  });

  it('never renders a store badge on a familia grouping node', () => {
    useTreeViewStore.setState({ showFamilia: true });
    const tree = {
      level: 1,
      kind: 'familia',
      family_id: 'FAM_STORE',
      label: 'Familia FAM_STORE',
      official_store_id: 57997,
      children: [],
    };
    renderNode(tree);

    expect(screen.getByText(/familia fam_store/i)).toBeInTheDocument();
    expect(screen.queryByText(/gauss/i)).not.toBeInTheDocument();
  });
});

describe('TreeNode — global collapse epoch sync', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
    useTreeViewStore.setState({ showFamilia: true, collapseEpoch: 0, collapseMode: 'manual' });
  });

  afterEach(() => {
    // These tests bump collapseEpoch — reset it so later describe blocks
    // (which don't touch collapse state) mount TreeNode with epoch 0 (no
    // sync effect firing on mount).
    useTreeViewStore.setState({ collapseEpoch: 0, collapseMode: 'manual' });
  });

  function buildMlaTree() {
    return {
      level: 1,
      kind: 'catalogo',
      mla: 'MLA_CAT',
      label: 'MLA_CAT',
      matches_filter: true,
      children: [
        { level: 2, kind: 'vinculada', mla: 'MLA_VINC1', label: 'MLA_VINC1', matches_filter: true, children: [] },
      ],
    };
  }

  it('global-open opens every node (including nested promo panel) in one action', () => {
    renderNode(buildMlaTree());

    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' })); });

    expect(screen.getByText('MLA_VINC1')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /^promociones/i }).length).toBeGreaterThan(0);
  });

  it('global-close closes every node after being opened', () => {
    renderNode(buildMlaTree());

    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' })); });
    expect(screen.getAllByRole('button', { name: /^promociones/i }).length).toBeGreaterThan(0);

    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-closed' })); });

    expect(screen.queryByRole('button', { name: /^promociones/i })).not.toBeInTheDocument();
  });

  it('global-open also opens the catalog-competition sub-panel, not just promos', () => {
    renderNode(buildMlaTree());

    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' })); });

    const catalogButtons = screen.getAllByRole('button', { name: /^competencia catálogo/i });
    expect(catalogButtons.length).toBeGreaterThan(0);
    catalogButtons.forEach((button) => {
      expect(button).toHaveAttribute('aria-expanded', 'true');
    });
  });

  it('global-close also closes the catalog-competition sub-panel', () => {
    renderNode(buildMlaTree());

    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' })); });
    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-closed' })); });

    expect(screen.queryByRole('button', { name: /^competencia catálogo/i })).not.toBeInTheDocument();
  });

  it('global-open also opens the PxQ sub-panel — the catalog-competition panel was omitted from this same effect once before, this proves the new one joined it', () => {
    renderNode(buildMlaTree());

    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' })); });

    const pxqButtons = screen.getAllByRole('button', { name: /^precios mayoristas/i });
    expect(pxqButtons.length).toBeGreaterThan(0);
    pxqButtons.forEach((button) => {
      expect(button).toHaveAttribute('aria-expanded', 'true');
    });
  });

  it('global-close also closes the PxQ sub-panel', () => {
    renderNode(buildMlaTree());

    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' })); });
    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-closed' })); });

    expect(screen.queryByRole('button', { name: /^precios mayoristas/i })).not.toBeInTheDocument();
  });

  it('global-close really closes the sub-panels, not just the node that hides them', async () => {
    // Asserting the sub-panel buttons are absent right after a global-close is
    // vacuous: `isOpen` alone unmounts the whole section. Reopen the node
    // manually so the sub-panels render again, and assert they came back
    // CLOSED — that is the only way to prove the global-close actually reset
    // promosOpen/catalogCompetitionOpen instead of leaving them stuck open.
    renderNode(buildMlaTree());
    const user = userEvent.setup();

    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' })); });
    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-closed' })); });

    await user.click(screen.getByRole('button', { name: /expandir mla_cat/i }));

    expect(screen.getByRole('button', { name: /^promociones/i })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: /^competencia catálogo/i })).toHaveAttribute('aria-expanded', 'false');
  });

  it('manually reopening a node after a global-open does not re-explode its subtree', async () => {
    // Children only mount once their parent is open, so "expand all" reaches an
    // unmounted subtree through the mount cascade. That cascade must stop once
    // the user takes manual control: otherwise every node the user opens by hand
    // for the rest of the session force-opens its whole subtree, and a normal
    // single-level expand becomes impossible.
    renderNode(buildMlaTree());
    const user = userEvent.setup();

    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' })); });
    expect(screen.getByText('MLA_VINC1')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /colapsar mla_cat/i }));
    await user.click(screen.getByRole('button', { name: /expandir mla_cat/i }));

    // Two MLA-bearing nodes are mounted again (MLA_CAT and its child
    // MLA_VINC1). MLA_CAT's own panels stay open — the user never closed
    // those, they only collapsed and reopened the node, so preserving them is
    // correct. The child is the one that must come back CLOSED: it remounts,
    // and without the manual-mode reset the stale 'all-open' would force it and
    // its whole subtree open again.
    expect(screen.getByText('MLA_VINC1')).toBeInTheDocument();

    // A node's own sections only render while that node is open, so the child
    // coming back closed means exactly ONE promos button is in the document —
    // MLA_CAT's. Before the manual-mode reset there were TWO, both expanded,
    // because the remounted child force-opened itself from the stale mode.
    expect(screen.getAllByRole('button', { name: /^promociones/i })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: /^competencia catálogo/i })).toHaveLength(1);
    expect(screen.getByRole('button', { name: /^promociones/i })).toHaveAttribute('aria-expanded', 'true');
  });

  it('a manual toggle switches collapseMode back to manual', async () => {
    renderNode(buildMlaTree());
    const user = userEvent.setup();

    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' })); });
    expect(useTreeViewStore.getState().collapseMode).toBe('all-open');

    await user.click(screen.getByRole('button', { name: /colapsar mla_cat/i }));

    expect(useTreeViewStore.getState().collapseMode).toBe('manual');
    // The epoch must NOT move: already-mounted nodes keep the state the user gave them.
    expect(useTreeViewStore.getState().collapseEpoch).toBe(1);
  });

  it('a manual toggle after a global-open survives (does not get overridden back)', async () => {
    renderNode(buildMlaTree());
    const user = userEvent.setup();

    act(() => { useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' })); });
    expect(screen.getByText('MLA_VINC1')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /colapsar mla_cat/i }));

    expect(screen.queryByText('MLA_VINC1')).not.toBeInTheDocument();
  });
});

describe('TreeNode — catalogCompetitionCacheRef threading', () => {
  beforeEach(() => {
    mockTienePermiso.mockReturnValue(true);
    useTreeViewStore.setState({ showFamilia: false });
  });

  it('forwards catalogCompetitionCacheRef to children hoisted out of a hidden familia', async () => {
    // showFamilia is false BY DEFAULT, so this hoisting branch is the common
    // path, not an edge case. A prop dropped here reaches every MLA under a
    // familia with an undefined cache ref, and the panel's refresh then dies
    // on `catalogCompetitionCacheRef.current.delete(mla)`.
    const user = userEvent.setup();
    renderNode(buildDeepTree());

    // MLA_CAT is hoisted out of the hidden familia, so it is reached without
    // ever expanding a familia row — the branch that drops the prop.
    await user.click(screen.getByRole('button', { name: /expandir mla_cat/i }));
    await user.click(screen.getByRole('button', { name: /^competencia catálogo/i }));

    const panel = screen.getByTestId('catalog-competition-MLA_CAT');
    expect(panel.getAttribute('data-has-cache-ref')).toBe('yes');
  });

  it('keeps the catalog competition panel reachable for a view-only user', async () => {
    // Reading the stored snapshot only needs promos.ver; the panel itself
    // must stay available even when the refresh inside it is not.
    mockTienePermiso.mockImplementation((perm) => perm !== 'promos.escribir');
    const user = userEvent.setup();
    renderNode(buildDeepTree());

    await user.click(screen.getByRole('button', { name: /expandir mla_cat/i }));
    await user.click(screen.getByRole('button', { name: /^competencia catálogo/i }));

    expect(screen.getByTestId('catalog-competition-MLA_CAT')).toBeInTheDocument();
  });
});

describe('TreeNode — official store filter hides non-matching MLAs', () => {
  beforeEach(() => {
    mockTienePermiso.mockReturnValue(true);
    useTreeViewStore.setState({ showFamilia: false });
  });

  it('hides an MLA with matches_filter false when ONLY the store filter is active', async () => {
    // The most common case and the one that was broken: a store is selected
    // and NO promo filter is. The backend composes the store result into
    // matches_filter (it does not drop the nodes), so a Gauss MLA comes back
    // as matches_filter:false — but the hiding logic used to key off the
    // promo filter alone, so it rendered anyway and the filter did nothing.
    const tree = {
      level: 1,
      kind: 'catalogo',
      mla: 'MLA_TPLINK',
      label: 'MLA_TPLINK',
      matches_filter: true,
      children: [
        {
          level: 2,
          kind: 'vinculada',
          mla: 'MLA_GAUSS',
          label: 'MLA_GAUSS',
          matches_filter: false,
          children: [],
        },
      ],
    };

    const user = userEvent.setup();
    renderNode(tree, { promoTipos: [], promoEstado: 'disponible', tiendaOficial: '2645' });

    expect(screen.getByText('MLA_TPLINK')).toBeInTheDocument();
    // Children only mount once the parent row is expanded — without this the
    // assertion below would pass merely because the row is collapsed.
    await user.click(screen.getByRole('button', { name: /expandir mla_tplink/i }));

    expect(screen.queryByText('MLA_GAUSS')).not.toBeInTheDocument();
  });

  it('still shows everything when no filter at all is active', () => {
    const tree = {
      level: 1,
      kind: 'catalogo',
      mla: 'MLA_A',
      label: 'MLA_A',
      matches_filter: false,
      children: [],
    };

    renderNode(tree, { promoTipos: [], promoEstado: 'disponible', tiendaOficial: null });

    // matches_filter false with no active filter must stay visible — the
    // fail-open rule; only an ACTIVE filter may hide a node.
    expect(screen.getByText('MLA_A')).toBeInTheDocument();
  });


  it('hides a non-matching MLA hoisted out of a hidden familia', async () => {
    // showFamilia is false by default, so children of a familia are hoisted
    // through a separate recursive branch. A prop dropped there means the
    // store filter stops applying below any familia — the same class of gap
    // that already bit catalogCompetitionCacheRef on this component.
    const user = userEvent.setup();
    const tree = {
      level: 1,
      kind: 'catalogo',
      mla: 'MLA_ROOT',
      label: 'MLA_ROOT',
      matches_filter: true,
      children: [
        {
          level: 2,
          kind: 'familia',
          family_id: 'FAM_X',
          label: 'familia FAM_X',
          children: [
            // One matching sibling is essential: if EVERY child were hidden,
            // nodeHasVisibleContent would prune the whole familia upstream and
            // the hoisting branch would never run, making the bug invisible.
            {
              level: 3,
              kind: 'vinculada',
              mla: 'MLA_MISMA_TIENDA',
              label: 'MLA_MISMA_TIENDA',
              matches_filter: true,
              children: [],
            },
            {
              level: 3,
              kind: 'vinculada',
              mla: 'MLA_OTRA_TIENDA',
              label: 'MLA_OTRA_TIENDA',
              matches_filter: false,
              children: [],
            },
          ],
        },
      ],
    };

    renderNode(tree, { promoTipos: [], promoEstado: 'disponible', tiendaOficial: '2645' });
    await user.click(screen.getByRole('button', { name: /expandir mla_root/i }));

    expect(screen.getByText('MLA_MISMA_TIENDA')).toBeInTheDocument();
    expect(screen.queryByText('MLA_OTRA_TIENDA')).not.toBeInTheDocument();
  });
});

describe('TreeNode — sub-spoiler toggles look like buttons', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
    useTreeViewStore.setState({ showFamilia: true, collapseEpoch: 0, collapseMode: 'manual' });
  });

  function buildMlaNode() {
    return {
      level: 1,
      kind: 'catalogo',
      mla: 'MLA_BTN',
      label: 'MLA_BTN',
      matches_filter: true,
      children: [],
    };
  }

  const TOGGLES = [/^promociones/i, /^competencia catálogo/i, /^precios mayoristas/i];

  it.each(TOGGLES)('renders %s with a visible button variant, not the invisible ghost one', async (name) => {
    renderNode(buildMlaNode());
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir mla_btn/i }));

    const button = screen.getByRole('button', { name });

    // `ghost` is transparent background AND transparent border, so on the
    // panel's own background it reads as loose text. Users reported exactly
    // that: they could not tell these were buttons.
    expect(button.className).not.toMatch(/\bghost\b/);
    expect(button.className).toMatch(/outline-subtle-primary/);
  });

  it.each(TOGGLES)('marks %s as active while its section is open', async (name) => {
    renderNode(buildMlaNode());
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir mla_btn/i }));

    const button = screen.getByRole('button', { name });
    expect(button.className).not.toMatch(/toggle-active/);

    await user.click(button);

    expect(screen.getByRole('button', { name }).className).toMatch(/toggle-active/);
  });
});


describe('TreeNode — who decides whether the promos panel pulls from ML', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
    useTreeViewStore.setState({ showFamilia: true, collapseEpoch: 0, collapseMode: 'manual' });
  });

  afterEach(() => {
    useTreeViewStore.setState({ collapseEpoch: 0, collapseMode: 'manual' });
  });

  function buildMlaNode() {
    return { level: 1, kind: 'catalogo', mla: 'MLA_PULL', label: 'MLA_PULL', matches_filter: true, children: [] };
  }

  it('pulls when the user opens the panel themselves', async () => {
    renderNode(buildMlaNode());
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir mla_pull/i }));
    await user.click(screen.getByRole('button', { name: /^promociones/i }));

    expect(screen.getByTestId('mla-promos-MLA_PULL').dataset.pullOnOpen).toBe('true');
  });

  it('does NOT pull when a global expand mounted it', async () => {
    // One click on "Expandir todo" mounts every MLA panel in the tree. Each
    // pulling would turn that into N concurrent hits on a throttle shared
    // with sales-webhook processing.
    renderNode(buildMlaNode());

    act(() => {
      useTreeViewStore.setState((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' }));
    });

    expect(screen.getByTestId('mla-promos-MLA_PULL').dataset.pullOnOpen).toBe('false');
  });

  it('goes back to pulling on a later open after a manual refresh', async () => {
    // The skip flag is meant to cover exactly one remount — the one the
    // refresh button causes. Left sticky, a single click on refresh stopped
    // this node from ever pulling on open again for the rest of its life.
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    renderNode(buildMlaNode());
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir mla_pull/i }));
    await user.click(screen.getByRole('button', { name: /^promociones/i }));

    await user.click(screen.getByRole('button', { name: /refrescar promociones/i }));
    await waitFor(() =>
      expect(screen.getByTestId('mla-promos-MLA_PULL').dataset.pullOnOpen).toBe('false'),
    );

    // Close and reopen: this is a fresh open and must pull again.
    await user.click(screen.getByRole('button', { name: /^promociones/i }));
    await user.click(screen.getByRole('button', { name: /^promociones/i }));

    expect(screen.getByTestId('mla-promos-MLA_PULL').dataset.pullOnOpen).toBe('true');
  });
});

// `collapseMode` is global (one store for the whole page), so an "Expandir
// todo" clicked inside one product's tree is still 'all-open' while another
// product's tree mounts. That is not a leak of the no-pull decision: the same
// mode is what force-opens the whole freshly mounted subtree, so the mass
// expansion and the suppressed pulls always travel together. And the first
// manual toggle calls markManual(), which restores pulling before the panel
// re-renders.
describe('TreeNode — a leftover global expand mode stays self-consistent', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
    useTreeViewStore.setState({ showFamilia: true, collapseEpoch: 3, collapseMode: 'all-open' });
  });

  afterEach(() => {
    useTreeViewStore.setState({ collapseEpoch: 0, collapseMode: 'manual' });
  });

  function buildMlaNode() {
    return { level: 1, kind: 'catalogo', mla: 'MLA_LEFT', label: 'MLA_LEFT', matches_filter: true, children: [] };
  }

  it('force-opens a newly mounted panel and suppresses its pull together', () => {
    renderNode(buildMlaNode());

    // Nobody opened this by hand — the leftover mode did, exactly as it does
    // for the tree the button was clicked in. Pulling here would be the same
    // N-concurrent-pulls burst the flag exists to prevent.
    expect(screen.getByTestId('mla-promos-MLA_LEFT').dataset.pullOnOpen).toBe('false');
  });

  it('pulls again as soon as the user toggles the panel by hand', async () => {
    renderNode(buildMlaNode());
    const user = userEvent.setup();

    // Close and reopen by hand: markManual() runs on the first click, so the
    // reopen is a genuine user-opened panel and must pull.
    await user.click(screen.getByRole('button', { name: /^promociones/i }));
    await user.click(screen.getByRole('button', { name: /^promociones/i }));

    expect(useTreeViewStore.getState().collapseMode).toBe('manual');
    expect(screen.getByTestId('mla-promos-MLA_LEFT').dataset.pullOnOpen).toBe('true');
  });
});

describe('TreeNode — opening a publication (onOpenPublication)', () => {
  const PUBLICATION = { level: 1, kind: 'publicacion', mla: 'MLA_OPEN', label: 'Router abierto', publication_status: 'active', children: [] };
  const FAMILY = {
    level: 1,
    kind: 'familia',
    family_id: 'FAM_OPEN',
    label: 'Familia abierta',
    children: [{ level: 2, kind: 'vinculada', mla: 'MLA_CHILD', label: 'Vinculada abierta', children: [] }],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useTreeViewStore.setState({ showFamilia: true, collapseEpoch: 0, collapseMode: 'manual' });
  });

  // Productos passes no `onOpenPublication`: its rows must stay exactly as they were.
  it('without it, a publication row renders as before: same DOM, its only buttons expand and refresh', async () => {
    const { container } = renderNode(PUBLICATION);
    expect(container.innerHTML).toMatchInlineSnapshot(`"<table><tbody><tr><td class="_spoilerToggleCell_03bd49"><button type="button" class="_spoilerToggle_03bd49" aria-label="Expandir Router abierto" aria-expanded="false"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-chevron-right" aria-hidden="true"><path d="m9 18 6-6-6-6"></path></svg></button></td><td class="_treeNodeLabelCell_03bd49"><span class="_badge_03bd49 _badgeKindPublicacion_03bd49">Publicación</span><span class="_treeNodeLabel_03bd49">Router abierto</span><span class="_badge_03bd49 _badgeStatusActive_03bd49"><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-circle-check" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><path d="m9 12 2 2 4-4"></path></svg>Activa</span><span class="_badge_03bd49 _badgeReadonly_03bd49">Sin tienda</span><button type="button" class="btn-tesla outline-subtle-primary icon-only sm" aria-label="Refrescar promociones de Router abierto"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-refresh-cw" aria-hidden="true"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path><path d="M8 16H3v5"></path></svg></button></td></tr></tbody></table>"`);
    expect(screen.getAllByRole('button').map((button) => button.getAttribute('aria-label'))).toEqual([
      'Expandir Router abierto',
      'Refrescar promociones de Router abierto',
    ]);
    await userEvent.click(screen.getByText('Router abierto'));
    expect(screen.getByRole('button', { name: 'Expandir Router abierto' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('without it, a familia row and its children render as before', async () => {
    const { container } = renderNode(FAMILY);
    await userEvent.click(screen.getByRole('button', { name: 'Expandir Familia abierta' }));
    expect(container.innerHTML).toMatchInlineSnapshot(`"<table><tbody><tr class="_rowTintFamilia_03bd49"><td class="_spoilerToggleCell_03bd49"><button type="button" class="_spoilerToggle_03bd49" aria-label="Colapsar Familia abierta" aria-expanded="true"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-chevron-down" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg></button></td><td class="_treeNodeLabelCell_03bd49"><span class="_badge_03bd49 _badgeKindFamilia_03bd49">Familia</span><span class="_treeNodeLabel_03bd49">Familia abierta</span><span class="_treeNodeChildKindCount_03bd49">1 vinculada</span></td></tr><tr class="_filaDetalle_03bd49"><td colspan="5"><div class="_filaDetalleContent_03bd49"><div class="_treeNodeChildrenSection_03bd49"><table class="_innerTable_03bd49"><tbody><tr class="_rowTintVinculada_03bd49"><td class="_spoilerToggleCell_03bd49"><button type="button" class="_spoilerToggle_03bd49" aria-label="Expandir Vinculada abierta" aria-expanded="false"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-chevron-right" aria-hidden="true"><path d="m9 18 6-6-6-6"></path></svg></button></td><td class="_treeNodeLabelCell_03bd49"><span class="_badge_03bd49 _badgeKindVinculada_03bd49">Vinculada</span><span class="_treeNodeLabel_03bd49">Vinculada abierta</span><span class="_badge_03bd49 _badgeReadonly_03bd49">Sin tienda</span><button type="button" class="btn-tesla outline-subtle-primary icon-only sm" aria-label="Refrescar promociones de Vinculada abierta"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-refresh-cw" aria-hidden="true"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path><path d="M8 16H3v5"></path></svg></button></td></tr></tbody></table></div></div></td></tr></tbody></table>"`);
    expect(screen.queryByRole('button', { name: /^Abrir / })).not.toBeInTheDocument();
  });

  it('with it, a publication row offers "Abrir <mla>", which opens it without expanding the row', async () => {
    const onOpenPublication = vi.fn();
    renderNode(PUBLICATION, { onOpenPublication });
    await userEvent.click(screen.getByRole('button', { name: 'Abrir MLA_OPEN' }));
    expect(onOpenPublication).toHaveBeenCalledWith('MLA_OPEN');
    expect(screen.getByRole('button', { name: 'Expandir Router abierto' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('with it, a familia (no publication of its own) offers nothing, its publications do, hoisted or nested', async () => {
    const onOpenPublication = vi.fn();
    renderNode(FAMILY, { onOpenPublication });
    expect(screen.queryByRole('button', { name: /^Abrir / })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Expandir Familia abierta' }));
    await userEvent.click(screen.getByRole('button', { name: 'Abrir MLA_CHILD' }));
    expect(onOpenPublication).toHaveBeenCalledWith('MLA_CHILD');

    act(() => useTreeViewStore.setState({ showFamilia: false }));
    expect(screen.getByRole('button', { name: 'Abrir MLA_CHILD' })).toBeInTheDocument();
  });
});

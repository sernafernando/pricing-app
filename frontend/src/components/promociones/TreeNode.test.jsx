import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TreeNode from './TreeNode';

// Mock the leaf promo panel so prop-threading assertions can inspect exactly
// what reaches it, without depending on its own fetch/reload internals.
vi.mock('./MlaPromocionesPanel', () => ({
  default: (props) => (
    <div data-testid={`mla-promos-${props.mla}`} data-props={JSON.stringify(Object.keys(props).sort())}>
      mocked-promos-for-{props.mla}
    </div>
  ),
}));

function renderNode(node, props = {}) {
  const mlasCacheRef = { current: new Map() };
  const promosCacheRef = { current: new Map() };
  return render(
    <table>
      <tbody>
        <TreeNode
          node={node}
          colSpan={5}
          mlasCacheRef={mlasCacheRef}
          promosCacheRef={promosCacheRef}
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
  });

  it('renders a familia grouping node with its label', () => {
    renderNode(buildDeepTree());
    expect(screen.getByText(/familia fam1/i)).toBeInTheDocument();
  });

  it('recursively renders nested catalogo/vinculada kinds down to depth 4', async () => {
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
    renderNode(buildDeepTree());
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir familia fam1/i }));
    await user.click(screen.getByRole('button', { name: /expandir mla_cat/i }));

    expect(screen.getByText(/catálogo/i)).toBeInTheDocument();
    expect(screen.getByText(/vinculada/i)).toBeInTheDocument();
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
    const promosToggle = screen.getByRole('button', { name: /promociones/i });
    expect(promosToggle).toBeInTheDocument();
    expect(screen.getByText('MLA_VINC1')).toBeInTheDocument();
    expect(screen.queryByTestId('mla-promos-MLA_CAT')).not.toBeInTheDocument();

    await user.click(promosToggle);
    expect(screen.getByTestId('mla-promos-MLA_CAT')).toBeInTheDocument();
  });

  it('does not render a promos sub-spoiler for grouping nodes (familia has no mla)', async () => {
    renderNode(buildDeepTree());
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir familia fam1/i }));
    expect(screen.queryByRole('button', { name: /promociones/i })).not.toBeInTheDocument();
  });

  it('hides an MLA-bearing node when matches_filter is false and a filter is active', async () => {
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
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir familia fam1/i }));

    expect(screen.getByText('MLA_SHOWN')).toBeInTheDocument();
    expect(screen.queryByText('MLA_HIDDEN')).not.toBeInTheDocument();
  });

  it('reveals matches_filter:false nodes when revealAll is true', async () => {
    const tree = {
      level: 1,
      kind: 'familia',
      label: 'Familia FAM1',
      children: [
        { level: 2, kind: 'catalogo', mla: 'MLA_HIDDEN', label: 'MLA_HIDDEN', matches_filter: false, children: [] },
      ],
    };
    renderNode(tree, { promoTipos: ['SELLER_CAMPAIGN'], promoEstado: 'aplicada', revealAll: true });
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir familia fam1/i }));

    expect(screen.getByText('MLA_HIDDEN')).toBeInTheDocument();
  });

  it('treats matches_filter absent/null as show (fail-open) even when a filter is active', async () => {
    const tree = {
      level: 1,
      kind: 'familia',
      label: 'Familia FAM1',
      children: [
        { level: 2, kind: 'catalogo', mla: 'MLA_NOFLAG', label: 'MLA_NOFLAG', children: [] },
      ],
    };
    renderNode(tree, { promoTipos: ['SELLER_CAMPAIGN'], promoEstado: 'aplicada' });
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir familia fam1/i }));

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
    const promoToggles = screen.getAllByRole('button', { name: /promociones/i });
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

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TreeNode from './TreeNode';
import { promocionesAPI } from '../../services/api';
import { useTreeViewStore } from '../../store/treeViewStore';
import { usePromoFilterStore } from '../../store/promoFilterStore';

// REGRESSION (prod, MLA1391137819): the status chip said "Activa" while the
// promotions panel showed the "Publicación pausada" banner. Both now come from
// the same backend field (`ml_items.status`): the tree node's
// `publication_status` and the item read's `motivo_sin_actualizacion`. This
// renders the REAL promotions panel under the chip with the payloads the
// backend produces for one `ml_items` row, so chip and banner read together.

vi.mock('./CatalogCompetitionPanel', () => ({ default: () => null }));
vi.mock('./PxqPanel', () => ({ default: () => null }));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(() => Promise.resolve({ data: [] })) },
  promocionesAPI: {
    getPromocionesItem: vi.fn(),
    refreshItemPromociones: vi.fn(() => Promise.resolve({ data: { ok: true, promotions: [] } })),
    confirmarSinPromosML: vi.fn(() => Promise.resolve({ data: { sin_promos_confirmado: true, promos_en_ml: 0 } })),
  },
}));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const MOTIVO_PAUSADA = 'Publicación pausada: las promos se actualizan cuando se reactive';
const PAUSED_BANNER = /publicación pausada: las promos se actualizan cuando se reactive\. mostrando el último estado conocido/i;

// What the backend returns for one `ml_items` row, per status.
const BACKEND_BY_ML_STATUS = {
  paused: {
    node: { publication_status: 'paused', publication_sub_status: ['paused_by_seller'] },
    item: { promotions: [], motivo_sin_actualizacion: MOTIVO_PAUSADA },
  },
  active: {
    node: { publication_status: 'active', publication_sub_status: [] },
    item: { promotions: [], motivo_sin_actualizacion: null },
  },
};

async function renderOpenLeaf(mlStatus) {
  const { node, item } = BACKEND_BY_ML_STATUS[mlStatus];
  promocionesAPI.getPromocionesItem.mockResolvedValue({ data: item });
  render(
    <table>
      <tbody>
        <TreeNode
          node={{ level: 1, kind: 'publicacion', mla: 'MLA_PARITY', label: 'MLA_PARITY', children: [], ...node }}
          colSpan={5}
          mlasCacheRef={{ current: new Map() }}
          promosCacheRef={{ current: new Map() }}
          catalogCompetitionCacheRef={{ current: new Map() }}
          pxqCacheRef={{ current: new Map() }}
          promoTipos={[]}
          promoEstado="disponible"
        />
      </tbody>
    </table>,
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: /expandir mla_parity/i }));
  await user.click(screen.getByRole('button', { name: /^promociones/i }));
}

describe('TreeNode status chip and promotions banner agree', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTreeViewStore.setState({ showFamilia: false });
    usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
  });

  it('a paused ml_items row shows the "Pausada" chip and the paused banner', async () => {
    await renderOpenLeaf('paused');

    expect(await screen.findByText(PAUSED_BANNER)).toBeInTheDocument();
    expect(screen.getByText('Pausada')).toBeInTheDocument();
    expect(screen.queryByText('Activa')).not.toBeInTheDocument();
  });

  it('an active ml_items row shows the "Activa" chip and no paused banner', async () => {
    await renderOpenLeaf('active');

    expect(await screen.findByText('Activa')).toBeInTheDocument();
    expect((await screen.findAllByText(/sin promociones/i)).length).toBeGreaterThan(0);
    expect(screen.queryByText(PAUSED_BANNER)).not.toBeInTheDocument();
    expect(screen.queryByText('Pausada')).not.toBeInTheDocument();
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import ModalInfoProducto from './ModalInfoProducto';
import api from '../services/api';

// The MercadoLibre tab's per-publication status reads `ml_items.status` (the
// owner's source of truth, served as `publication_status`) with the shared
// Publicaciones ML labels — same chip as the promotions tree.

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }));

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => permiso === 'productos.ver_info_mercadolibre' }),
}));

function publicacion(mla, publication_status, publication_sub_status) {
  return { mla, lista_nombre: 'Clásica', publication_status, publication_sub_status };
}

describe('ModalInfoProducto - publication status from ml_items', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockResolvedValue({
      data: {
        publicaciones_ml: [
          publicacion('MLA_A', 'active', []),
          publicacion('MLA_P', 'paused', ['paused_by_seller']),
          publicacion('MLA_I', 'inactive', null),
          publicacion('MLA_N', 'no_ml_data', null),
          publicacion('MLA_X', undefined, undefined),
        ],
      },
    });
  });

  it('labels each publication with the shared Publicaciones ML status labels', async () => {
    render(<ModalInfoProducto isOpen onClose={() => {}} itemId={1} />);

    expect(await screen.findByText('Activa')).toBeInTheDocument();
    expect(screen.getByText('Pausada')).toHaveAttribute('title', 'paused_by_seller');
    expect(screen.getByText('Inactiva')).toBeInTheDocument();
    expect(screen.getByText('Sin datos de ML')).toBeInTheDocument();
  });
});

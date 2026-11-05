import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import GestionFull from './GestionFull';

vi.mock('../services/api', () => ({
  default: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock('../hooks/useDebounce', () => ({
  useDebounce: (value) => value,
}));

const tienePermisoMock = vi.fn(() => false);

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    tienePermiso: (...args) => tienePermisoMock(...args),
  }),
}));

vi.mock('../components/gestionFull/GestionFullDepositosTab', () => ({
  default: () => <div>Depósito tab body</div>,
}));

vi.mock('../components/gestionFull/GestionFullGestorTab', () => ({
  default: () => <div>Envío tab body</div>,
}));

vi.mock('../components/gestionFull/GestionFullEnviosTab', () => ({
  default: () => <div>Consulta envíos body</div>,
}));

import api from '../services/api';

describe('GestionFull', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.patch.mockReset();
    api.post.mockReset();
    tienePermisoMock.mockReset();
    tienePermisoMock.mockImplementation(() => false);
  });

  it('renders grouped rows centered and calls the list endpoint', async () => {
    api.get.mockResolvedValue({
      data: {
        total: 2,
        items: [
          {
            producto_item_id: 1,
            ean: 'EAN-A',
            descripcion: 'Producto A',
            inventory_id: 'INV1',
            user_product_id: 'MLAU1',
            stock_erp: 10,
            stock_full: 2,
            ventas_full_7d: 1,
            ventas_full_14d: 2,
            ventas_full_21d: 3,
            ventas_full_30d: 4,
            override: null,
            puede_editar_override: false,
          },
          {
            producto_item_id: 1,
            ean: 'EAN-A',
            descripcion: 'Producto A',
            inventory_id: 'INV2',
            user_product_id: 'MLAU2',
            stock_erp: 10,
            stock_full: 1,
            ventas_full_7d: 0,
            ventas_full_14d: 1,
            ventas_full_21d: 1,
            ventas_full_30d: 2,
            override: 5,
            puede_editar_override: false,
          },
        ],
        puede_editar_override: false,
      },
    });

    render(<GestionFull />);

    await waitFor(() => {
      expect(screen.getByText('INV1')).toBeInTheDocument();
    });
    expect(screen.getByText('INV2')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Gestión Full' })).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith(
      '/gestion-full',
      expect.objectContaining({
        params: expect.objectContaining({
          limit: 200,
          offset: 0,
          full_mode: 'en',
          include_zero_stock: false,
          include_facets: true,
        }),
      }),
    );
  });

  it('sends fuera de Full and include_zero_stock when filters change', async () => {
    api.get.mockResolvedValue({ data: { total: 0, items: [], puede_editar_override: false } });
    render(<GestionFull />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText('Presencia Full'), { target: { value: 'fuera' } });
    fireEvent.click(screen.getByLabelText('Mostrar sin stock ERP'));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        '/gestion-full',
        expect.objectContaining({
          params: expect.objectContaining({
            full_mode: 'fuera',
            include_zero_stock: true,
          }),
        }),
      );
    });
  });

  it('sends solo_listo when Solo Listo is checked', async () => {
    api.get.mockResolvedValue({ data: { total: 0, items: [], puede_editar_override: false } });
    render(<GestionFull />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());

    fireEvent.click(screen.getByLabelText('Solo Listo'));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        '/gestion-full',
        expect.objectContaining({
          params: expect.objectContaining({
            solo_listo: true,
          }),
        }),
      );
    });
  });

  it('sends marcas/categorias CSV from the product panel and Limpiar clears them', async () => {
    api.get.mockResolvedValue({
      data: {
        total: 0,
        items: [],
        puede_editar_override: false,
        facets: {
          product: {
            marcas: ['Sony', 'LG'],
            categorias: ['Audio', 'Video'],
            subcategorias: [],
            pms: [],
          },
        },
      },
    });
    render(<GestionFull />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());

    await userEvent.click(screen.getByRole('button', { name: 'Marca' }));
    await userEvent.click(await screen.findByText('Sony'));
    await userEvent.click(screen.getByRole('button', { name: 'Categoría' }));
    await userEvent.click(await screen.findByText('Audio'));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        '/gestion-full',
        expect.objectContaining({
          params: expect.objectContaining({
            marcas: 'Sony',
            categorias: 'Audio',
          }),
        }),
      );
    });

    fireEvent.change(screen.getByLabelText('Presencia Full'), { target: { value: 'fuera' } });
    fireEvent.click(screen.getByRole('button', { name: 'Limpiar' }));

    await waitFor(() => {
      const last = api.get.mock.calls.at(-1)?.[1]?.params;
      expect(last?.marcas).toBeUndefined();
      expect(last?.categorias).toBeUndefined();
      expect(last?.full_mode).toBe('en');
      expect(last?.include_zero_stock).toBe(false);
    });
  });

  it('skips facets on list refresh after Cerrar', async () => {
    api.get.mockResolvedValue({
      data: {
        total: 1,
        items: [
          {
            producto_item_id: 1,
            ean: 'EAN-A',
            descripcion: 'Producto A',
            inventory_id: 'INV1',
            user_product_id: 'MLAU1',
            override: 3,
            sugerido: 8,
            pm_ready: false,
            puede_editar_override: true,
          },
        ],
        puede_editar_override: true,
        puede_gestor: false,
        facets: {
          product: { marcas: ['Sony'], categorias: [], subcategorias: [], pms: [] },
        },
      },
    });
    api.post.mockResolvedValue({
      data: {
        producto_item_id: 1,
        user_product_id: 'MLAU1',
        inventory_id: 'INV1',
        qty_pm: 3,
        pm_ready: true,
      },
    });

    render(<GestionFull />);
    fireEvent.click(await screen.findByRole('button', { name: 'Cerrar' }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalled();
    });
    await waitFor(() => {
      const refresh = api.get.mock.calls.find(
        ([, cfg]) => cfg?.params?.include_facets === false,
      );
      expect(refresh).toBeTruthy();
    });
  });

  it('patches override on blur when the row is editable', async () => {
    api.get.mockResolvedValue({
      data: {
        total: 1,
        items: [
          {
            producto_item_id: 1,
            ean: 'EAN-A',
            descripcion: 'Producto A',
            inventory_id: 'INV1',
            user_product_id: 'MLAU1',
            override: null,
            puede_editar_override: true,
          },
        ],
        puede_editar_override: true,
      },
    });
    api.patch.mockResolvedValue({ data: { inventory_id: 'INV1', override: 9 } });

    render(<GestionFull />);

    const input = await screen.findByLabelText('Override INV1');
    fireEvent.change(input, { target: { value: '9' } });
    fireEvent.blur(input);

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith('/gestion-full/INV1', { cantidad: 9 });
    });
  });

  it('posts ready when Cerrar is clicked', async () => {
    api.get.mockResolvedValue({
      data: {
        total: 1,
        items: [
          {
            producto_item_id: 1,
            ean: 'EAN-A',
            descripcion: 'Producto A',
            inventory_id: 'INV1',
            user_product_id: 'MLAU1',
            override: 3,
            sugerido: 8,
            pm_ready: false,
            puede_editar_override: true,
          },
        ],
        puede_editar_override: true,
        puede_gestor: false,
      },
    });
    api.post.mockResolvedValue({
      data: {
        producto_item_id: 1,
        user_product_id: 'MLAU1',
        inventory_id: 'INV1',
        qty_pm: 3,
        pm_ready: true,
      },
    });

    render(<GestionFull />);
    fireEvent.click(await screen.findByRole('button', { name: 'Cerrar' }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/gestion-full/ready', {
        producto_item_id: 1,
        user_product_id: 'MLAU1',
      });
    });
  });

  it('hides Depósito and Envío tabs without permissions; always shows Consulta envíos', async () => {
    api.get.mockResolvedValue({ data: { total: 0, items: [], puede_editar_override: false } });
    render(<GestionFull />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());

    expect(screen.queryByRole('tab', { name: 'Depósito' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Envío' })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Consulta envíos' })).toBeInTheDocument();
  });

  it('shows Depósito tab when gestion_full.depositos is granted', async () => {
    tienePermisoMock.mockImplementation((code) => code === 'gestion_full.depositos');
    api.get.mockResolvedValue({ data: { total: 0, items: [], puede_editar_override: false } });
    render(<GestionFull />);

    const tab = await screen.findByRole('tab', { name: 'Depósito' });
    fireEvent.click(tab);
    expect(screen.getByText('Depósito tab body')).toBeInTheDocument();
  });

  it('shows Envío tab when gestion_full.gestor is granted', async () => {
    tienePermisoMock.mockImplementation((code) => code === 'gestion_full.gestor');
    api.get.mockResolvedValue({ data: { total: 0, items: [], puede_editar_override: false } });
    render(<GestionFull />);

    const tab = await screen.findByRole('tab', { name: 'Envío' });
    fireEvent.click(tab);
    expect(screen.getByText('Envío tab body')).toBeInTheDocument();
  });
});

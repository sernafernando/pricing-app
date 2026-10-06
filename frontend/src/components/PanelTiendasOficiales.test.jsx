import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelTiendasOficiales from './PanelTiendasOficiales';
import api from '../services/api';
import { useTiendasOficialesStore } from '../store/tiendasOficialesStore';

const STORES = [
  { store_id: 57997, nombre: 'Gauss', clave: null, orden: 0, activa: true },
  { store_id: 2645, nombre: 'TP-Link', clave: 'tplink', orden: 1, activa: false },
];

beforeEach(() => {
  vi.clearAllMocks();
  useTiendasOficialesStore.setState({ tiendas: [], loaded: false, loading: false });
  api.get.mockImplementation((url) =>
    url === '/tiendas-oficiales' ? Promise.resolve({ data: STORES }) : Promise.resolve({ data: {} }),
  );
  api.post.mockResolvedValue({ data: {} });
  api.put.mockResolvedValue({ data: {} });
});

describe('PanelTiendasOficiales', () => {
  it('lists every store with its id, name, clave and state', async () => {
    render(<PanelTiendasOficiales />);
    const row = (await screen.findByText('Gauss')).closest('tr');
    expect(within(row).getByText('57997')).toBeInTheDocument();
    const inactive = screen.getByText('2645').closest('tr');
    expect(within(inactive).getByText('tplink')).toBeInTheDocument();
    expect(within(inactive).getByText('Inactiva')).toBeInTheDocument();
  });

  it('creates a store from the form and reloads the shared list', async () => {
    const user = userEvent.setup();
    render(<PanelTiendasOficiales />);
    await screen.findByText('Gauss');

    await user.type(screen.getByLabelText('ID de tienda (ML)'), '471846');
    await user.type(screen.getByLabelText('Nombre'), 'TP-Link');
    await user.type(screen.getByLabelText('Clave'), 'tplink');
    await user.click(screen.getByRole('button', { name: /crear/i }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/tiendas-oficiales', {
        store_id: 471846,
        nombre: 'TP-Link',
        clave: 'tplink',
        orden: 0,
        activa: true,
      }),
    );
    // Reloaded: initial load + after-save reload.
    await waitFor(() =>
      expect(api.get.mock.calls.filter(([url]) => url === '/tiendas-oficiales').length).toBeGreaterThanOrEqual(2),
    );
  });

  it('edits the name of an existing store (id is not editable)', async () => {
    const user = userEvent.setup();
    render(<PanelTiendasOficiales />);
    const row = (await screen.findByText('Gauss')).closest('tr');
    await user.click(within(row).getByRole('button', { name: 'Editar tienda' }));

    expect(screen.getByLabelText('ID de tienda (ML)')).toBeDisabled();
    const nombre = screen.getByLabelText('Nombre');
    await user.clear(nombre);
    await user.type(nombre, 'Gauss Oficial');
    await user.click(screen.getByRole('button', { name: /actualizar/i }));

    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith('/tiendas-oficiales/57997', {
        nombre: 'Gauss Oficial',
        clave: null,
        orden: 0,
        activa: true,
      }),
    );
  });

  it('deactivates an active store without deleting it', async () => {
    const user = userEvent.setup();
    render(<PanelTiendasOficiales />);
    const row = (await screen.findByText('Gauss')).closest('tr');
    await user.click(within(row).getByRole('button', { name: 'Desactivar tienda' }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/tiendas-oficiales/57997', { activa: false }));
  });

  it('shows the backend error when saving fails', async () => {
    const user = userEvent.setup();
    api.post.mockRejectedValue({ response: { data: { error: { message: 'Ya existe la tienda 5' } } } });
    render(<PanelTiendasOficiales />);
    await screen.findByText('Gauss');
    await user.type(screen.getByLabelText('ID de tienda (ML)'), '5');
    await user.type(screen.getByLabelText('Nombre'), 'X');
    await user.click(screen.getByRole('button', { name: /crear/i }));
    expect(await screen.findByText('Ya existe la tienda 5')).toBeInTheDocument();
  });
});

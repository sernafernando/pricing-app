import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelMarcasVisibles from './PanelMarcasVisibles';
import api from '../services/api';

const PAYLOAD = {
  excepciones: [
    { id: 7, marca: 'Vieja', creado_por: 'Ana', created_at: '2026-11-13T12:00:00Z', con_stock: false },
  ],
  marcas: [
    { marca: 'Epson', con_stock: true, en_excepcion: false },
    { marca: 'Epsilon', con_stock: false, en_excepcion: false },
    { marca: 'Vieja', con_stock: false, en_excepcion: true },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockResolvedValue({ data: PAYLOAD });
  api.post.mockResolvedValue({ data: {} });
  api.delete.mockResolvedValue({ data: {} });
});

describe('PanelMarcasVisibles', () => {
  it('lists the exceptions with their current stock state, who added them and when', async () => {
    render(<PanelMarcasVisibles />);
    const row = (await screen.findByText('Vieja')).closest('tr');
    expect(within(row).getByText('sin stock')).toBeInTheDocument();
    expect(within(row).getByText('Ana')).toBeInTheDocument();
    expect(within(row).getByText('13/11/2026')).toBeInTheDocument();
  });

  it('searches every brand, hidden ones included, and adds one', async () => {
    const user = userEvent.setup();
    render(<PanelMarcasVisibles />);
    await screen.findByText('Vieja');

    await user.type(screen.getByLabelText('Agregar una marca'), 'eps');
    const results = screen.getByRole('list', { name: 'Marcas encontradas' });
    expect(within(results).getByText('Epson')).toBeInTheDocument();
    const epsilon = within(results).getByText('Epsilon').closest('li');
    expect(within(epsilon).getByText('sin stock')).toBeInTheDocument();

    await user.click(within(epsilon).getByRole('button', { name: 'Agregar Epsilon' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/marcas-visibles/excepciones', { marca: 'Epsilon' }));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  });

  it('marks a brand already in the list instead of offering to add it again', async () => {
    const user = userEvent.setup();
    render(<PanelMarcasVisibles />);
    await screen.findByText('Vieja');
    await user.type(screen.getByLabelText('Agregar una marca'), 'vie');
    const results = screen.getByRole('list', { name: 'Marcas encontradas' });
    expect(within(results).getByText('En la lista')).toBeInTheDocument();
    expect(within(results).queryByRole('button')).not.toBeInTheDocument();
  });

  it('removes a brand from the list', async () => {
    const user = userEvent.setup();
    render(<PanelMarcasVisibles />);
    await user.click(await screen.findByRole('button', { name: 'Quitar Vieja' }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/marcas-visibles/excepciones/7'));
  });

  it('shows the server error when adding fails', async () => {
    api.post.mockRejectedValueOnce({ response: { data: { detail: 'La marca Epson ya está en la lista' } } });
    const user = userEvent.setup();
    render(<PanelMarcasVisibles />);
    await screen.findByText('Vieja');
    await user.type(screen.getByLabelText('Agregar una marca'), 'epson');
    await user.click(screen.getByRole('button', { name: 'Agregar Epson' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('La marca Epson ya está en la lista');
  });
});

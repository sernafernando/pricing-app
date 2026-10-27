/**
 * VistaPorMarca — "Por marca / par" tab: pick a marca, see titular and
 * sub-PMs per category.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import VistaPorMarca from './VistaPorMarca';

const PARES = [
  { id: 1, marca: 'Samsung', categoria: 'Celulares', usuario_id: 1, usuario_nombre: 'Titular' },
  { id: 2, marca: 'Samsung', categoria: 'Monitores', usuario_id: 1, usuario_nombre: 'Titular' },
  { id: 3, marca: 'Samsung', categoria: 'Tablets', usuario_id: null, usuario_nombre: null },
  { id: 4, marca: 'LG', categoria: 'Televisores', usuario_id: 1, usuario_nombre: 'Titular' },
];

const GRANTS = [
  { id: 70, marca: 'Samsung', categoria: 'Celulares', usuario_id: 6, usuario_nombre: 'Beto' },
  { id: 71, marca: 'LG', categoria: 'Televisores', usuario_id: 5, usuario_nombre: 'Ana' },
];

function renderVista() {
  render(<VistaPorMarca pares={PARES} grantsScope={GRANTS} />);
}

function filaDe(categoria) {
  return screen.getByRole('cell', { name: categoria }).closest('tr');
}

describe('VistaPorMarca', () => {
  it('lists marcas with their category count and opens the first one', () => {
    renderVista();
    expect(screen.getByRole('button', { name: 'LG (1)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Samsung (3)' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'LG' })).toBeInTheDocument();
  });

  it('shows titular and sub-PMs per category of the selected marca', async () => {
    const user = userEvent.setup();
    renderVista();
    await user.click(screen.getByRole('button', { name: /^Samsung/ }));

    expect(within(filaDe('Celulares')).getByText('Titular')).toBeInTheDocument();
    expect(within(filaDe('Celulares')).getByText('Beto')).toBeInTheDocument();
    expect(within(filaDe('Tablets')).getByText('Sin titular')).toBeInTheDocument();
    expect(within(filaDe('Monitores')).getByText('—')).toBeInTheDocument();
  });

  it('moves the detail to a listed marca when the search hides the picked one', async () => {
    const user = userEvent.setup();
    renderVista();
    await user.click(screen.getByRole('button', { name: 'LG (1)' }));
    await user.type(screen.getByRole('searchbox', { name: 'Buscar marca' }), 'sam');
    expect(screen.getByRole('heading', { name: 'Samsung' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'LG' })).not.toBeInTheDocument();
  });

  it('filters marcas by the search term', async () => {
    const user = userEvent.setup();
    renderVista();
    await user.type(screen.getByRole('searchbox', { name: 'Buscar marca' }), 'sam');
    expect(screen.queryByRole('button', { name: /^LG/ })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Samsung' })).toBeInTheDocument();

    await user.clear(screen.getByRole('searchbox', { name: 'Buscar marca' }));
    await user.type(screen.getByRole('searchbox', { name: 'Buscar marca' }), 'zzz');
    expect(screen.getByText('Ninguna marca coincide.')).toBeInTheDocument();
  });
});

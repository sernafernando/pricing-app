/**
 * VistaPorMarca — "Por marca / par" tab: pick a marca, see titular and
 * sub-PMs per category, add one user to several categories with a single
 * atomic PUT (their current grants plus the new ones).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import VistaPorMarca from './VistaPorMarca';
import { marcasPmAPI } from '../../services/api';

const PARES = [
  { id: 1, marca: 'Samsung', categoria: 'Celulares', usuario_id: 1, usuario_nombre: 'Titular' },
  { id: 2, marca: 'Samsung', categoria: 'Monitores', usuario_id: 1, usuario_nombre: 'Titular' },
  { id: 3, marca: 'Samsung', categoria: 'Tablets', usuario_id: null, usuario_nombre: null },
  { id: 4, marca: 'LG', categoria: 'Televisores', usuario_id: 1, usuario_nombre: 'Titular' },
];

const USUARIOS = [
  { id: 5, nombre: 'Ana' },
  { id: 6, nombre: 'Beto' },
];

const GRANTS = [
  { id: 70, marca: 'Samsung', categoria: 'Celulares', usuario_id: 6, usuario_nombre: 'Beto' },
  { id: 71, marca: 'LG', categoria: 'Televisores', usuario_id: 5, usuario_nombre: 'Ana' },
];

function renderVista(props = {}) {
  const onCambio = vi.fn();
  render(<VistaPorMarca pares={PARES} usuarios={USUARIOS} grantsScope={GRANTS} onCambio={onCambio} {...props} />);
  return { onCambio };
}

function filaDe(categoria) {
  return screen.getByRole('cell', { name: categoria }).closest('tr');
}

beforeEach(() => {
  marcasPmAPI.asignarSubPMsBulk.mockReset().mockResolvedValue({ data: { otorgados: 2, revocados: 0, total: 3 } });
});

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

  it('adds the user to the selected categories keeping every grant they already have', async () => {
    const user = userEvent.setup();
    const { onCambio } = renderVista();
    await user.click(screen.getByRole('button', { name: /^Samsung/ }));

    const agregar = screen.getByRole('button', { name: /^Agregar a/ });
    expect(agregar).toBeDisabled();
    await user.click(screen.getByLabelText('Seleccionar Monitores'));
    await user.click(screen.getByLabelText('Seleccionar Tablets'));
    expect(agregar).toBeDisabled(); // no user yet
    await user.selectOptions(screen.getByLabelText('Agregar como sub-PM'), '5');
    expect(agregar).toHaveTextContent('Agregar a 2 categorías');
    await user.click(agregar);

    expect(marcasPmAPI.asignarSubPMsBulk).toHaveBeenCalledTimes(1);
    const [usuarioId, pares] = marcasPmAPI.asignarSubPMsBulk.mock.calls[0];
    expect(usuarioId).toBe(5);
    expect(pares).toHaveLength(3);
    expect(pares).toEqual(
      expect.arrayContaining([
        { marca: 'LG', categoria: 'Televisores' },
        { marca: 'Samsung', categoria: 'Monitores' },
        { marca: 'Samsung', categoria: 'Tablets' },
      ]),
    );
    expect(await screen.findByText('Ana agregado como sub-PM en 2 categorías de Samsung.')).toBeInTheDocument();
    expect(onCambio).toHaveBeenCalledWith([5]);
    expect(screen.getByLabelText('Seleccionar Monitores')).not.toBeChecked();
  });

  it('selects every category of the marca at once', async () => {
    const user = userEvent.setup();
    renderVista();
    await user.click(screen.getByRole('button', { name: /^Samsung/ }));
    await user.click(screen.getByRole('button', { name: 'Seleccionar todas' }));
    expect(screen.getByRole('button', { name: /^Agregar a/ })).toHaveTextContent('Agregar a 3 categorías');
    await user.click(screen.getByRole('button', { name: 'Deseleccionar todas' }));
    expect(screen.getByRole('button', { name: /^Agregar a/ })).toHaveTextContent('Agregar a 0 categorías');
  });

  it('says nothing was applied when the PUT is rejected', async () => {
    const user = userEvent.setup();
    marcasPmAPI.asignarSubPMsBulk.mockRejectedValue({
      response: { status: 403, data: { detail: { mensaje: 'Pares fuera de tu scope', pares_rechazados: [] } } },
    });
    const { onCambio } = renderVista();
    await user.click(screen.getByLabelText('Seleccionar Televisores'));
    await user.selectOptions(screen.getByLabelText('Agregar como sub-PM'), '6');
    await user.click(screen.getByRole('button', { name: /^Agregar a/ }));

    expect(await screen.findByText('Pares fuera de tu scope No se aplicó ningún cambio.')).toBeInTheDocument();
    expect(onCambio).not.toHaveBeenCalled();
  });

});

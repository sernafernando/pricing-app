/**
 * "Compras a revisar" (owner L29; odd/tasks/costo-si-compras-sospechosas.md S5): the purchases held out of costo SI
 * for a suspicious price, with the item 23 / invoice 00128199 case, and a reviewer's accept / keep-excluded decision.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { costoSiSospechasAPI } from '../../services/sellInAPI';
import SellInComprasRevisar, { ratioLabel } from './SellInComprasRevisar';

vi.mock('../../services/sellInAPI', () => ({
  costoSiSospechasAPI: { listar: vi.fn(), resumen: vi.fn(), aceptar: vi.fn(), excluir: vi.fn() },
}));

const ITEM_23 = {
  id: 1,
  item_id: 23,
  codigo: 'TL-WA850RE',
  descripcion: 'EXTENSOR DE RANGO WIFI TP LINK TL-WA850RE 300MBPS',
  ct_transaction: 935025,
  factura: '00128199',
  fecha: '2026-10-27',
  cantidad: 312,
  precio: '0.00971',
  moneda: 'USD',
  referencia: '13.53550',
  fuente_ref: 'costo_si',
  ratio: '0.000717',
  estado: 'pendiente',
  revisor: null,
  revisado_at: null,
  nota: null,
};

/** ModalTesla has no dialog role: the open modal is the one holding its title. */
const modal = async (titulo) => within((await screen.findByRole('heading', { name: titulo })).closest('.modal-tesla'));

beforeEach(() => {
  vi.clearAllMocks();
  costoSiSospechasAPI.listar.mockResolvedValue({ data: [ITEM_23] });
});

describe('SellInComprasRevisar', () => {
  it('lists the item 23 purchase with its invoice, price, reference and deviation', async () => {
    render(<SellInComprasRevisar puedeRevisar />);

    const fila = (await screen.findByText('00128199')).closest('tr');
    expect(costoSiSospechasAPI.listar).toHaveBeenCalledWith({ estado: 'pendiente' });
    expect(within(fila).getByText('EXTENSOR DE RANGO WIFI TP LINK TL-WA850RE 300MBPS')).toBeInTheDocument();
    expect(within(fila).getByText('27/10/2026')).toBeInTheDocument();
    expect(within(fila).getByText('312 u')).toBeInTheDocument();
    expect(within(fila).getByText('USD 0,00971')).toBeInTheDocument();
    expect(within(fila).getByText('USD 13,5355')).toBeInTheDocument();
    expect(within(fila).getByText('costo SI')).toBeInTheDocument();
    expect(within(fila).getByText(/1\/1\.395 de la referencia/)).toBeInTheDocument();
    expect(within(fila).getByText('Pendiente')).toBeInTheDocument();
  });

  it('reads the list again with the chosen state, and all of them with Todas', async () => {
    const user = userEvent.setup();
    render(<SellInComprasRevisar puedeRevisar />);
    await screen.findByText('00128199');

    await user.selectOptions(screen.getByRole('combobox', { name: 'Estado' }), 'Excluidas');
    await waitFor(() => expect(costoSiSospechasAPI.listar).toHaveBeenLastCalledWith({ estado: 'excluida' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Estado' }), 'Todas');
    await waitFor(() => expect(costoSiSospechasAPI.listar).toHaveBeenLastCalledWith({}));
  });

  it('accepts after a confirmation with a note, sends the price it showed and reads the list again', async () => {
    const user = userEvent.setup();
    const onDecidido = vi.fn();
    costoSiSospechasAPI.aceptar.mockResolvedValue({ data: { ...ITEM_23, estado: 'aceptada' } });
    render(<SellInComprasRevisar puedeRevisar onDecidido={onDecidido} />);

    await user.click(await screen.findByRole('button', { name: /^Aceptar la compra de EXTENSOR/ }));
    const dialogo = await modal('Aceptar la compra');
    expect(dialogo.getByText(/se recalcula la historia del producto/)).toBeInTheDocument();
    await user.type(dialogo.getByRole('textbox', { name: 'Nota (opcional)' }), 'Precio verificado');
    await user.click(dialogo.getByRole('button', { name: 'Aceptar' }));

    await waitFor(() => expect(costoSiSospechasAPI.aceptar).toHaveBeenCalledWith(1, '0.00971', 'Precio verificado'));
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Aceptar la compra' })).not.toBeInTheDocument());
    expect(onDecidido).toHaveBeenCalledTimes(1);
    expect(costoSiSospechasAPI.listar).toHaveBeenCalledTimes(2);
  });

  it('keeps it excluded', async () => {
    const user = userEvent.setup();
    costoSiSospechasAPI.excluir.mockResolvedValue({ data: { ...ITEM_23, estado: 'excluida' } });
    render(<SellInComprasRevisar puedeRevisar />);

    await user.click(await screen.findByRole('button', { name: /^Mantener excluida la compra/ }));
    await user.click((await modal('Mantener excluida')).getByRole('button', { name: 'Mantener excluida' }));

    await waitFor(() => expect(costoSiSospechasAPI.excluir).toHaveBeenCalledWith(1, '0.00971', ''));
  });

  it('explains a corrected invoice (409) and keeps the dialog open', async () => {
    const user = userEvent.setup();
    costoSiSospechasAPI.aceptar.mockRejectedValue({ response: { status: 409 } });
    render(<SellInComprasRevisar puedeRevisar />);

    await user.click(await screen.findByRole('button', { name: /^Aceptar la compra/ }));
    await user.click((await modal('Aceptar la compra')).getByRole('button', { name: 'Aceptar' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('La factura se corrigió desde que se cargó la lista');
    expect(screen.getByRole('heading', { name: 'Aceptar la compra' })).toBeInTheDocument();
  });

  it('is read only without costo_si.revisar', async () => {
    render(<SellInComprasRevisar puedeRevisar={false} />);
    await screen.findByText('00128199');

    expect(screen.queryByRole('button', { name: /^Aceptar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Mantener excluida/ })).not.toBeInTheDocument();
  });

  it('offers only the decision a row does not have yet, and shows who reviewed it', async () => {
    costoSiSospechasAPI.listar.mockResolvedValue({
      data: [{ ...ITEM_23, estado: 'excluida', revisor: 'Alejandro', revisado_at: '2026-11-22T10:00:00Z' }],
    });
    render(<SellInComprasRevisar puedeRevisar />);

    expect(await screen.findByText('Alejandro · 22/11/2026')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Aceptar la compra/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Mantener excluida la compra/ })).not.toBeInTheDocument();
  });

  it('says when there is nothing to review, and offers a retry on an error', async () => {
    const user = userEvent.setup();
    costoSiSospechasAPI.listar.mockResolvedValueOnce({ data: [] });
    const { unmount } = render(<SellInComprasRevisar puedeRevisar />);
    expect(await screen.findByText('No hay compras pendientes.')).toBeInTheDocument();
    unmount();

    costoSiSospechasAPI.listar.mockRejectedValueOnce(new Error('boom'));
    render(<SellInComprasRevisar puedeRevisar />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar las compras a revisar.');
    await user.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByText('00128199')).toBeInTheDocument();
  });

  it('labels the deviation as a fraction below 1 and a multiple above it', () => {
    expect([ratioLabel('0.000717'), ratioLabel('12.5'), ratioLabel(null)]).toEqual([
      '1/1.395 de la referencia',
      '13× la referencia',
      '—',
    ]);
  });
});

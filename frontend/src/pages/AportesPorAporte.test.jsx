import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../services/api';
import AportesPorAporte from './AportesPorAporte';
import { APORTES_VIEW } from './aportesFixtures';

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }));

const RANGE = { from: '2026-10-01', to: '2026-10-31' };

const renderView = (props = {}) =>
  render(
    <AportesPorAporte range={RANGE} canManage refreshKey={0} onEdit={vi.fn()} onDelete={vi.fn()} {...props} />,
  );

const table = () => screen.getByRole('table', { name: 'Aportes del período' });
const bodyRows = () => within(table()).getAllByRole('row').slice(1, -1);

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockResolvedValue({ data: APORTES_VIEW });
});

describe('AportesPorAporte', () => {
  it('asks for the aportes of the range', async () => {
    renderView();
    await screen.findByText('Lucía Fernández · 02/10');
    expect(api.get).toHaveBeenCalledWith('/ml-ads/contributions', {
      params: { date_from: '2026-10-01', date_to: '2026-10-31' },
    });
  });

  it('sums the period in tiles, each channel against its own cost, and the cost no aporte can cover', async () => {
    renderView();
    const tiles = await screen.findByRole('region', { name: 'Resumen de aportes por aporte' });
    await waitFor(() => expect(tiles).toHaveTextContent('$ 510,15'));
    expect(within(tiles).getByText('3 marcas · 3 aportes')).toBeInTheDocument();
    expect(within(tiles).getByText('26,4 % del costo de Product Ads')).toBeInTheDocument();
    expect(within(tiles).getByText('25 % del costo de Display')).toBeInTheDocument();
    expect(tiles).toHaveTextContent('Sin campaña');
    expect(tiles).toHaveTextContent('$ 94,30');
    expect(within(tiles).getByText('Costo de Product Ads sin campaña: ningún aporte lo cubre')).toBeInTheDocument();
  });

  it('splits the period by brand, largest first, with each share and the total', async () => {
    renderView();
    const brands = await screen.findByRole('region', { name: 'Por marca' });
    await waitFor(() => expect(within(brands).getAllByRole('listitem')).toHaveLength(3));
    expect(within(brands).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Xerox$ 300,00(58,8 %)',
      'Epson$ 150,00(29,4 %)',
      'TP-Link$ 60,15(11,8 %)',
    ]);
    expect(brands).toHaveTextContent('Total $ 510,15');
  });

  it('lists one row per aporte with its channel, scope, type, value, range, coverage and who loaded it', async () => {
    renderView();
    await screen.findByText('Lucía Fernández · 02/10');
    const [pct, display, fixed] = bodyRows();
    expect(within(pct).getByText('Product Ads')).toBeInTheDocument();
    expect(pct).toHaveTextContent('TP-Link Deco');
    expect(pct).toHaveTextContent('351001');
    expect(pct).toHaveTextContent('Porcentaje');
    expect(pct).toHaveTextContent('20 %');
    expect(pct).toHaveTextContent('01/10 → 31/10');
    expect(pct).toHaveTextContent('$ 60,15');
    expect(pct).toHaveTextContent('Editado 18/10');
    expect(within(display).getByText('Display')).toBeInTheDocument();
    expect(display).toHaveTextContent('Toda la cuenta Display · GAUSS');
    expect(display).toHaveTextContent('Cuenta completa');
    expect(within(fixed).getByText('Se recibe todo')).toBeInTheDocument();
    expect(fixed).toHaveTextContent('Monto fijo');
    expect(fixed).toHaveTextContent('$ 150,00');
    expect(fixed).toHaveTextContent('Martín Gómez · 03/10');
    const total = within(table()).getAllByRole('row').at(-1);
    expect(total).toHaveTextContent('Total (3 aportes)');
    expect(total).toHaveTextContent('$ 510,15');
  });

  it('filters by brand or campaign text, by brand and by channel, without asking again', async () => {
    const user = userEvent.setup();
    renderView();
    await screen.findByText('Lucía Fernández · 02/10');
    await user.type(screen.getByRole('searchbox', { name: 'Buscar marca o campaña' }), 'deco');
    expect(bodyRows()).toHaveLength(1);
    await user.clear(screen.getByRole('searchbox', { name: 'Buscar marca o campaña' }));
    await user.selectOptions(screen.getByLabelText('Marca'), 'Epson');
    expect(bodyRows()).toHaveLength(1);
    await user.selectOptions(screen.getByLabelText('Marca'), '');
    await user.click(screen.getByRole('button', { name: 'Display' }));
    expect(bodyRows().map((row) => within(row).getAllByRole('cell')[0].textContent)).toEqual(['Xerox']);
    expect(within(table()).getAllByRole('row').at(-1)).toHaveTextContent('Total (1 aporte)');
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('edits Product Ads aportes and deletes any, with the permission to manage them', async () => {
    const onEdit = vi.fn();
    const onDelete = vi.fn();
    const user = userEvent.setup();
    renderView({ onEdit, onDelete });
    await screen.findByText('Lucía Fernández · 02/10');
    const [pct, display] = bodyRows();
    await user.click(within(pct).getByRole('button', { name: 'Editar aporte de TP-Link' }));
    expect(onEdit).toHaveBeenCalledWith(APORTES_VIEW.contributions[0]);
    // No form loads a Display aporte yet (pending its Stitch screen): no pencil on that row.
    expect(within(display).queryByRole('button', { name: /Editar/ })).not.toBeInTheDocument();
    await user.click(within(display).getByRole('button', { name: 'Borrar aporte de Xerox' }));
    expect(onDelete).toHaveBeenCalledWith(APORTES_VIEW.contributions[1]);
  });

  it('offers no action without the permission to manage aportes', async () => {
    renderView({ canManage: false });
    await screen.findByText('Lucía Fernández · 02/10');
    expect(within(table()).queryAllByRole('button')).toEqual([]);
  });

  it('waits for a whole range before asking, like the campaigns view', async () => {
    renderView({ range: { from: '2026-10-31', to: '2026-10-01' } });
    renderView({ range: { from: '2026-10-01', to: '' } });
    await waitFor(() => expect(screen.queryAllByRole('alert')).toEqual([]));
    expect(api.get).not.toHaveBeenCalled();
  });

  it('asks again when the page says something changed', async () => {
    const { rerender } = renderView();
    await screen.findByText('Lucía Fernández · 02/10');
    rerender(<AportesPorAporte range={RANGE} canManage refreshKey={1} onEdit={vi.fn()} onDelete={vi.fn()} />);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  });

  it('explains what a deleted aporte and "Devuelve diferencia" mean', async () => {
    renderView();
    expect(
      await screen.findByText(
        "Un aporte borrado deja de contar pero queda en el historial con quién lo borró y cuándo. 'Devuelve diferencia' cuenta como máximo lo gastado en el rango.",
      ),
    ).toBeInTheDocument();
  });

  it('groups an aporte saved before the brand was required under "Sin marca"', async () => {
    const legacy = { ...APORTES_VIEW.contributions[0], brand: null };
    api.get.mockResolvedValue({ data: { ...APORTES_VIEW, contributions: [legacy] } });
    renderView();
    const brands = await screen.findByRole('region', { name: 'Por marca' });
    await waitFor(() => expect(within(brands).getAllByRole('listitem')).toHaveLength(1));
    expect(within(brands).getByRole('listitem')).toHaveTextContent('Sin marca$ 60,15(100 %)');
    expect(within(bodyRows()[0]).getAllByRole('cell')[0]).toHaveTextContent('Sin marca');
  });

  it('says so when the aportes cannot be loaded', async () => {
    api.get.mockRejectedValue({ response: { data: { error: { message: 'boom' } } } });
    renderView();
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../services/api';
import AportesHistorial from './AportesHistorial';
import { APORTE_HISTORY, HISTORY_ROW } from './aportesFixtures';

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }));

const renderModal = (props = {}) => render(<AportesHistorial aporte={HISTORY_ROW} onClose={vi.fn()} {...props} />);
const events = async () => [...(await screen.findByRole('list', { name: 'Eventos del aporte' })).children];

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockResolvedValue({ data: APORTE_HISTORY });
});

describe('AportesHistorial (Stitch 973006a2)', () => {
  it('asks for the history of the aporte and names it by brand, campaign and id', async () => {
    renderModal();
    await events();
    expect(api.get).toHaveBeenCalledWith('/ml-ads/contributions/5/history');
    expect(screen.getByText('Historial del aporte')).toBeInTheDocument();
    expect(screen.getByText('Logitech · Logitech MX Master & Periféricos · 353110945')).toBeInTheDocument();
  });

  it('shows the load with who, when in Argentine time, and what was loaded', async () => {
    renderModal();
    const [created] = await events();
    expect(within(created).getByText('Cargado')).toBeInTheDocument();
    expect(created).toHaveTextContent('Martín Gómez · 16/10/2026 15:20');
    expect(within(created).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Tipo: Monto fijo',
      'Monto: $ 120.000,00',
      'Cómo se liquida: Se recibe todo',
      'Rango: 16/10 → 25/10',
    ]);
  });

  it('shows an edit with only the fields that changed, before and after', async () => {
    renderModal();
    const [, edited] = await events();
    expect(within(edited).getByText('Editado')).toBeInTheDocument();
    expect(edited).toHaveTextContent('Martín Gómez · 18/10/2026 10:05');
    const lines = within(edited).getAllByRole('listitem');
    expect(lines.map((li) => li.textContent)).toEqual([
      'Monto: $ 120.000,00 → $ 150.000,00',
      'Rango: 16/10 → 25/10 → 16/10 → 31/10',
    ]);
    expect(within(lines[0]).getByText('$ 120.000,00').tagName).toBe('DEL');
  });

  it('shows a deletion with who deleted it and when', async () => {
    const deleted = APORTE_HISTORY.events[1].after;
    api.get.mockResolvedValue({
      data: { events: [{ action: 'deleted', user: 'Lucía Fernández', at: '2026-10-20T12:00:00+00:00', before: deleted, after: null }] },
    });
    renderModal();
    const [event] = await events();
    expect(within(event).getByText('Borrado')).toBeInTheDocument();
    expect(event).toHaveTextContent('Lucía Fernández · 20/10/2026 09:00');
  });

  it('names a percentage, a Display account aporte and a changed brand or note', async () => {
    const before = { ...APORTE_HISTORY.events[0].after, kind: 'percentage', value: '30.00', settlement: null };
    api.get.mockResolvedValue({
      data: {
        events: [
          { action: 'created', user: null, at: '2026-10-16T18:20:00+00:00', before: null, after: before },
          {
            action: 'edited',
            user: 'Martín Gómez',
            at: '2026-10-17T18:20:00+00:00',
            before,
            after: { ...before, value: '25.00', brand: 'Logi', note: 'Q4' },
          },
        ],
      },
    });
    renderModal({ aporte: { ...HISTORY_ROW, channel: 'display', campaign_id: null, campaign_name: null } });
    const [created, edited] = await events();
    expect(created).toHaveTextContent('Sin dato · 16/10/2026 15:20');
    expect(within(created).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Tipo: Porcentaje',
      'Porcentaje: 30 %',
      'Rango: 16/10 → 25/10',
    ]);
    expect(within(edited).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Marca: Logitech → Logi',
      'Porcentaje: 30 % → 25 %',
      'Nota: Sin nota → Q4',
    ]);
    expect(screen.getByText('Logitech · Toda la cuenta Display · GAUSS')).toBeInTheDocument();
  });

  it('explains what a deletion leaves and closes', async () => {
    const onClose = vi.fn();
    renderModal({ onClose });
    await events();
    expect(screen.getByText('Si el aporte se borra, el historial lo muestra con quién lo borró y cuándo.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cerrar' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('says so when the history cannot be loaded', async () => {
    api.get.mockRejectedValue({ response: { data: { error: { message: 'boom' } } } });
    renderModal();
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});

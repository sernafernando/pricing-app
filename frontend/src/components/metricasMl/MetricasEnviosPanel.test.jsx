import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MetricasEnviosPanel from './MetricasEnviosPanel';
import api from '../../services/api';

vi.mock('../../services/api', () => ({ default: { get: vi.fn() } }));

const ROWS = [
  { modo: 'self_service', operations: 120, units: 150, gross: 3000000 },
  { modo: 'fulfillment', operations: 40, units: 44, gross: 1000000 },
  { modo: 'xd_drop_off', operations: 2, units: 2, gross: 0 },
];
const PARAMS = { fecha_desde: '2026-09-01', fecha_hasta: '2026-09-30', marcas: 'Epson' };

const open = async () => userEvent.click(screen.getByRole('button', { name: /Por tipo de envío/ }));

describe('MetricasEnviosPanel (audit B8)', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockResolvedValue({ data: { rows: ROWS } });
  });

  it('asks nothing until it is opened', () => {
    render(<MetricasEnviosPanel params={PARAMS} />);
    expect(api.get).not.toHaveBeenCalled();
  });

  it('opened, it reads the sales by shipping type under the board filters', async () => {
    render(<MetricasEnviosPanel params={PARAMS} />);
    await open();

    expect(api.get).toHaveBeenCalledWith('/ml-metricas/board/envios', { params: PARAMS });
    const flex = within(await screen.findByRole('row', { name: /Flex/ }));
    expect(flex.getByText('$ 3.000.000,00')).toBeInTheDocument();
    expect(flex.getByText('75,0%')).toBeInTheDocument();
    expect(flex.getByText('120')).toBeInTheDocument();
    expect(flex.getByText('150')).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /Full/ })).toBeInTheDocument();
  });

  it('shows an unknown ML type verbatim, never as "Desconocido"', async () => {
    render(<MetricasEnviosPanel params={PARAMS} />);
    await open();

    expect(await screen.findByRole('row', { name: /xd_drop_off/ })).toBeInTheDocument();
  });

  it('reloads when the filters change while open', async () => {
    const { rerender } = render(<MetricasEnviosPanel params={PARAMS} />);
    await open();
    await screen.findByRole('row', { name: /Flex/ });

    rerender(<MetricasEnviosPanel params={{ ...PARAMS, marcas: 'Lenovo' }} />);

    await vi.waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/ml-metricas/board/envios', { params: { ...PARAMS, marcas: 'Lenovo' } }));
  });

  it('an equal filter object does not read again', async () => {
    const { rerender } = render(<MetricasEnviosPanel params={PARAMS} />);
    await open();
    await screen.findByRole('row', { name: /Flex/ });

    rerender(<MetricasEnviosPanel params={{ ...PARAMS }} />);

    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('says so when there are no sales, and when the request fails', async () => {
    api.get.mockResolvedValueOnce({ data: { rows: [] } });
    const { unmount } = render(<MetricasEnviosPanel params={PARAMS} />);
    await open();
    expect(await screen.findByText('Sin ventas en el período')).toBeInTheDocument();
    unmount();

    api.get.mockRejectedValueOnce(new Error('boom'));
    render(<MetricasEnviosPanel params={PARAMS} />);
    await open();
    expect(await screen.findByText('No se pudo cargar el desglose por tipo de envío')).toBeInTheDocument();
  });
});

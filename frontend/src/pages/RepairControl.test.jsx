import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import RepairControl from './RepairControl';
import { publicacionRepairAPI } from '../services/api';

vi.mock('../services/api', async () => {
  const actual = await vi.importActual('../services/api');
  return {
    ...actual,
    publicacionRepairAPI: {
      runs: vi.fn(),
      run: vi.fn(),
      eventsByMla: vi.fn(),
    },
  };
});

const RUN = {
  id: 1,
  job_type: 'envio',
  status: 'success',
  trigger: 'tick',
  started_at: new Date().toISOString(),
  finished_at: new Date().toISOString(),
  scanned: 10,
  changed: 2,
  skipped: 7,
  errors: 1,
  error_message: null,
};

const DETAIL = {
  run: RUN,
  events: [
    {
      id: 11,
      run_id: 1,
      mla_id: 'MLA1',
      item_id: 42,
      action: 'changed',
      before: { a: 1 },
      after: { a: 2 },
      detail: 'shipping_put',
      title: 'Cable HDMI 2m',
      descripcion: 'CABLE HDMI 2 METROS',
      created_at: new Date().toISOString(),
    },
  ],
  total: 1,
  page: 1,
  page_size: 50,
  breakdown: [{ action: 'changed', detail: 'shipping_put', count: 1 }, { action: 'skipped', detail: 'flex_refused', count: 1 }],
};

describe('RepairControl', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    publicacionRepairAPI.runs.mockResolvedValue({ data: { items: [], total: 0 } });
    publicacionRepairAPI.run.mockResolvedValue({ data: DETAIL });
    publicacionRepairAPI.eventsByMla.mockResolvedValue({ data: { mla_id: 'MLA9', events: [], total: 0, page: 1, page_size: 100, ml_writes: [] } });
  });

  it('renders empty state', async () => {
    renderWithRouter(<RepairControl />);
    await waitFor(() => expect(screen.getByText(/Sin corridas/i)).toBeInTheDocument());
  });

  it('sends filter params when filters change', async () => {
    renderWithRouter(<RepairControl />);
    await waitFor(() => expect(publicacionRepairAPI.runs).toHaveBeenCalled());
    const sel = screen.getByLabelText(/Tipo/i);
    fireEvent.change(sel, { target: { value: 'sku' } });
    await waitFor(() => {
      const last = publicacionRepairAPI.runs.mock.calls.at(-1)[0];
      expect(last.job_type).toBe('sku');
    });
  });

  it('loads run detail and breakdown on row click', async () => {
    publicacionRepairAPI.runs.mockResolvedValue({ data: { items: [RUN], total: 1 } });
    const { container } = renderWithRouter(<RepairControl />);
    await waitFor(() => expect(screen.getByText('10')).toBeInTheDocument());
    const row = container.querySelector('[data-row-key="1"]');
    fireEvent.click(row);
    await waitFor(() => expect(publicacionRepairAPI.run).toHaveBeenCalled());
    await waitFor(() => expect(screen.getAllByText(/shipping_put/i).length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getAllByText(/a: 1/).length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByText('Cable HDMI 2m')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText('CABLE HDMI 2 METROS')).toBeInTheDocument());
  });

  it('filters events when a motivo chip is clicked', async () => {
    publicacionRepairAPI.runs.mockResolvedValue({ data: { items: [RUN], total: 1 } });
    const { container } = renderWithRouter(<RepairControl />);
    await waitFor(() => expect(screen.getByText('10')).toBeInTheDocument());
    const row = container.querySelector('[data-row-key="1"]');
    fireEvent.click(row);
    await waitFor(() => expect(publicacionRepairAPI.run).toHaveBeenCalled());
    const chip = await screen.findByText(/Cambiado.*shipping_put/i);
    fireEvent.click(chip);
    await waitFor(() => {
      const last = publicacionRepairAPI.run.mock.calls.at(-1)[1];
      expect(last.action).toBe('changed');
      expect(last.detail).toBe('shipping_put');
    });
  });

  it('shows events and ml writes on MLA search', async () => {
    publicacionRepairAPI.eventsByMla.mockResolvedValue({
      data: {
        mla_id: 'MLA9',
        events: [{ id: 21, run_id: 1, mla_id: 'MLA9', item_id: null, action: 'changed', before: null, after: null, detail: 'shipping_put', created_at: new Date().toISOString(), run_job_type: 'envio', run_started_at: new Date().toISOString() }],
        total: 1,
        page: 1,
        page_size: 100,
        ml_writes: [{ id: 1, action: 'update_shipping', payload: { shipping: { x: 1 } }, created_at: new Date().toISOString() }],
      },
    });
    renderWithRouter(<RepairControl />);
    const input = screen.getByPlaceholderText(/Buscar MLA/i);
    await userEvent.type(input, 'MLA9');
    fireEvent.submit(input.closest('form'));
    await waitFor(() => expect(publicacionRepairAPI.eventsByMla).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText('MLA9')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText('update_shipping')).toBeInTheDocument());
  });

  it('highlights failed or error rows', async () => {
    const failedRun = { ...RUN, id: 2, status: 'failed', errors: 3 };
    publicacionRepairAPI.runs.mockResolvedValue({ data: { items: [failedRun], total: 1 } });
    const { container } = renderWithRouter(<RepairControl />);
    await waitFor(() => expect(container.querySelector('[data-row-key="2"][data-marker]')).not.toBeNull());
    await waitFor(() => {
      const span = [...container.querySelectorAll('span')].find((s) => s.textContent === '3');
      expect(span).not.toBeNull();
      expect(span.style.color).toBe('var(--cf-danger)');
      expect(span.style.fontWeight).toBe('600');
    });
  });

  it('shows error state when runs fail', async () => {
    publicacionRepairAPI.runs.mockRejectedValue({ response: { status: 500 } });
    renderWithRouter(<RepairControl />);
    await waitFor(() => expect(screen.getByText(/Error al cargar las corridas/i)).toBeInTheDocument());
  });
});

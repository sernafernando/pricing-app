import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TicketCreateModal from './TicketCreateModal';
import { sectoresAPI, ticketsAPI } from '../services/api';

/**
 * Regression coverage for PR 3 (tickets-ai-triage):
 *  1. Single-box submit — the minimal payload sent to the backend when only
 *     `texto` is filled (advanced fields omitted, not empty-string-sent).
 *  2. Attachment failure surfacing — the silent swallow previously at
 *     TicketCreateModal.jsx:249-253 (a rejected `subirAdjunto` call must show
 *     an inline Spanish error with a retry action, and the ticket stays
 *     usable — `onCreated` is only called once every attachment succeeds).
 *  3. Metadata-preserving type change — the wipe previously at
 *     TicketCreateModal.jsx:182-184 (changing tipo now keeps metadata keys
 *     present in the new schema_campos and lists the dropped ones inline,
 *     with no confirm() — banned by AGENTS.md).
 *
 * NOTE: vite.config.js sets `css: false` for the test run, so CSS Module
 * class names do NOT resolve — never assert on className, only text/roles.
 */

vi.mock('../services/api', () => ({
  sectoresAPI: {
    listar: vi.fn(),
    listarTiposTicket: vi.fn(),
  },
  ticketsAPI: {
    crear: vi.fn(),
    subirAdjunto: vi.fn(),
  },
}));

const SECTOR = { id: 1, nombre: 'Soporte' };
const TIPO_BUG = {
  id: 10,
  nombre: 'Bug',
  schema_campos: {
    motivo: { tipo: 'text', label: 'Motivo', descripcion: 'motivo-field' },
    navegador: { tipo: 'string', label: 'Navegador', descripcion: 'navegador-field' },
  },
};
const TIPO_CONSULTA = {
  id: 11,
  nombre: 'Consulta',
  schema_campos: { motivo: { tipo: 'text', label: 'Motivo', descripcion: 'motivo-field' } },
};

beforeEach(() => {
  vi.clearAllMocks();
  sectoresAPI.listar.mockResolvedValue({ data: [SECTOR] });
  sectoresAPI.listarTiposTicket.mockResolvedValue({ data: [TIPO_BUG, TIPO_CONSULTA] });
});

async function fillTexto(texto = 'No puedo facturar desde ayer') {
  // `findBy` + `fireEvent.change` (not `user.type`, character by character)
  // deliberately: a real flake was observed on the first render in this
  // file (only reproduced there, never on later renders) where keystrokes
  // sent via `user.type` immediately after `render()` were dropped from
  // React state despite landing in the DOM's uncontrolled `.value` — some
  // async resource (lucide-react icons / CSS module) resolving mid-typing
  // on a cold render. `fireEvent.change` sets the value and fires `onChange`
  // atomically inside one `act()`, sidestepping the race entirely.
  const box = await screen.findByPlaceholderText(/Describí el problema/i);
  fireEvent.change(box, { target: { value: texto } });
  return userEvent.setup();
}

describe('TicketCreateModal — single-box submit path', () => {
  it('sends only texto + defaults, omitting sector/tipo/titulo when not chosen', async () => {
    ticketsAPI.crear.mockResolvedValue({ data: { id: 99, titulo: 'No puedo facturar desde ayer' } });
    const onCreated = vi.fn();

    const user = await (async () => {
      render(<TicketCreateModal isOpen onClose={vi.fn()} onCreated={onCreated} />);
      return fillTexto();
    })();

    await user.click(screen.getByRole('button', { name: /Crear Ticket/i }));

    await waitFor(() => expect(ticketsAPI.crear).toHaveBeenCalledTimes(1));
    const payload = ticketsAPI.crear.mock.calls[0][0];
    expect(payload.texto).toBe('No puedo facturar desde ayer');
    expect(payload).not.toHaveProperty('sector_id');
    expect(payload).not.toHaveProperty('tipo_ticket_id');
    expect(payload).not.toHaveProperty('titulo');
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 99, titulo: 'No puedo facturar desde ayer' }));
  });
});

describe('TicketCreateModal — attachment failure is surfaced, never swallowed', () => {
  it('shows an inline error with retry when subirAdjunto rejects, and does not call onCreated', async () => {
    ticketsAPI.crear.mockResolvedValue({ data: { id: 5, titulo: 'x' } });
    ticketsAPI.subirAdjunto.mockRejectedValue({
      response: { data: { error: { message: 'El archivo excede el tamaño máximo' } } },
    });
    const onCreated = vi.fn();

    const user = await (async () => {
      render(<TicketCreateModal isOpen onClose={vi.fn()} onCreated={onCreated} />);
      return fillTexto();
    })();

    const file = new File(['x'], 'captura.png', { type: 'image/png' });
    const fileInput = document.querySelector('input[type="file"]');
    await user.upload(fileInput, file);

    await user.click(screen.getByRole('button', { name: /Crear Ticket/i }));

    await screen.findByText('El archivo excede el tamaño máximo');
    expect(onCreated).not.toHaveBeenCalled();

    // Retry — this time the upload succeeds.
    ticketsAPI.subirAdjunto.mockResolvedValueOnce({ data: {} });
    await user.click(screen.getByRole('button', { name: /Reintentar/i }));

    await waitFor(() => expect(screen.queryByText('El archivo excede el tamaño máximo')).not.toBeInTheDocument());
    expect(ticketsAPI.subirAdjunto).toHaveBeenCalledTimes(2);
  });
});

describe('TicketCreateModal — type change preserves overlapping metadata', () => {
  it('keeps shared keys, drops the rest, and lists what was dropped', async () => {
    const user = userEvent.setup();
    render(<TicketCreateModal isOpen onClose={vi.fn()} onCreated={vi.fn()} />);
    await fillTexto();

    await user.click(screen.getByRole('button', { name: /Opciones avanzadas/i }));
    const [sectorSelect] = screen.getAllByRole('combobox');
    await user.selectOptions(sectorSelect, String(SECTOR.id));
    await screen.findByText(TIPO_BUG.nombre);

    const tipoSelect = screen.getAllByRole('combobox')[1];
    await user.selectOptions(tipoSelect, String(TIPO_BUG.id));

    const motivoInput = await screen.findByPlaceholderText('motivo-field');
    fireEvent.change(motivoInput, { target: { value: 'no anda' } });
    fireEvent.change(screen.getByPlaceholderText('navegador-field'), { target: { value: 'Chrome 120' } });

    await user.selectOptions(tipoSelect, String(TIPO_CONSULTA.id));

    // "navegador" isn't in TIPO_CONSULTA's schema — dropped, and listed inline.
    await screen.findByText(/Navegador/);
    expect(screen.queryByPlaceholderText('navegador-field')).not.toBeInTheDocument();

    // "motivo" is in both schemas — preserved with its value intact.
    expect(screen.getByPlaceholderText('motivo-field')).toHaveValue('no anda');
  });
});

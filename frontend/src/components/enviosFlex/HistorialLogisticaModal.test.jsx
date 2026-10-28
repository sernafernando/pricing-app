import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../../services/api';
import HistorialLogisticaModal from './HistorialLogisticaModal';

const RAYO = { id: 1, nombre: 'Rayo Express', color: '#2563eb' };
const MOTO = { id: 2, nombre: 'Moto Sur', color: '#16a34a' };

// Local-time ISO strings so the dd/mm HH:MM rendering is timezone-independent.
const iso = (d, h, m) => new Date(2026, 9, d, h, m).toISOString();

const HISTORIAL = {
  shipping_id: '44812345678',
  logistica_actual: RAYO,
  puede_deshacer: true,
  deshacer_a: MOTO,
  cambios: [
    {
      id: 3,
      cambiado_en: iso(27, 14, 32),
      origen: 'pistoleado',
      anterior: MOTO,
      nueva: RAYO,
      usuario_nombre: 'Juan Pérez',
      operador_nombre: 'Carla',
    },
    {
      id: 2,
      cambiado_en: iso(27, 13, 10),
      origen: 'masivo',
      anterior: null,
      nueva: MOTO,
      usuario_nombre: 'Ana Gómez',
      operador_nombre: null,
    },
    {
      id: 1,
      cambiado_en: iso(26, 9, 5),
      origen: null,
      anterior: RAYO,
      nueva: null,
      usuario_nombre: null,
      operador_nombre: null,
    },
  ],
};

const renderModal = (props = {}) => {
  const onClose = vi.fn();
  render(<HistorialLogisticaModal shippingId="44812345678" onClose={onClose} {...props} />);
  return { onClose };
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('HistorialLogisticaModal', () => {
  it('renders the changes newest first with chips, origin badges and author', async () => {
    api.get.mockResolvedValue({ data: HISTORIAL });
    renderModal();

    const filas = await screen.findAllByRole('listitem');
    expect(api.get).toHaveBeenCalledWith('/etiquetas-envio/44812345678/logistica/historial');
    expect(screen.getByText('Historial de logística')).toBeInTheDocument();
    expect(screen.getByText('Envío 44812345678')).toBeInTheDocument();
    expect(screen.getByText('Logística actual:')).toBeInTheDocument();

    expect(filas).toHaveLength(3);
    const [primera, segunda, tercera] = filas;

    expect(within(primera).getByText('27/10 14:32')).toBeInTheDocument();
    expect(within(primera).getByText('Moto Sur')).toBeInTheDocument();
    expect(within(primera).getByText('Rayo Express')).toBeInTheDocument();
    expect(within(primera).getByText('PISTOLEADO')).toBeInTheDocument();
    expect(within(primera).getByText('Juan Pérez · Op. Carla')).toBeInTheDocument();

    expect(within(segunda).getByText('27/10 13:10')).toBeInTheDocument();
    expect(within(segunda).getByText('Sin asignar')).toBeInTheDocument();
    expect(within(segunda).getByText('MASIVO')).toBeInTheDocument();
    expect(within(segunda).getByText('Ana Gómez')).toBeInTheDocument();

    // No origin -> no badge; no author -> em dash.
    expect(within(tercera).getByText('26/10 09:05')).toBeInTheDocument();
    expect(within(tercera).getByText('Sin asignar')).toBeInTheDocument();
    expect(within(tercera).queryByText(/^(ASIGNAR|MASIVO|PISTOLEADO|MANUAL|DESHACER)$/)).toBeNull();
    expect(within(tercera).getByText('—')).toBeInTheDocument();
  });

  it('shows an em dash, not the epoch, when the change has no date', async () => {
    api.get.mockResolvedValue({
      data: { ...HISTORIAL, cambios: [{ ...HISTORIAL.cambios[0], cambiado_en: null }] },
    });
    renderModal();

    const [fila] = await screen.findAllByRole('listitem');
    expect(within(fila).getByText('—')).toBeInTheDocument();
    expect(within(fila).queryByText(/^01\/01/)).toBeNull();
  });

  it('shows the empty state when there are no changes', async () => {
    api.get.mockResolvedValue({
      data: { ...HISTORIAL, puede_deshacer: false, deshacer_a: null, cambios: [] },
    });
    renderModal();

    expect(await screen.findByText('Sin cambios de logística registrados.')).toBeInTheDocument();
  });

  it('shows an error when the history cannot be loaded', async () => {
    api.get.mockRejectedValue({ response: { status: 500, data: { detail: 'boom' } } });
    renderModal();

    expect(await screen.findByText('No se pudo cargar el historial de logística.')).toBeInTheDocument();
  });

  it('is read-only: only a Cerrar button, which closes the modal', async () => {
    const user = userEvent.setup();
    api.get.mockResolvedValue({ data: HISTORIAL });
    const { onClose } = renderModal();

    await screen.findAllByRole('listitem');
    expect(screen.queryByRole('button', { name: /Deshacer/ })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Cerrar' }));
    expect(onClose).toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });
});

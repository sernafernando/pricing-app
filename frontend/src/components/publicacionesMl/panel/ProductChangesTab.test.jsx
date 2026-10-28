/**
 * The product's changes made in the app (publicaciones-ml-paridad-productos S12b), the same log Productos' "Historial
 * de Cambios" reads (`GET /productos/{id}/auditoria`): when, who, what kind of change and each value before → after.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductChangesTab from './ProductChangesTab';
import { productosAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  productosAPI: { auditoria: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });

const entry = (overrides = {}) => ({
  id: 1,
  item_id: 4101,
  usuario_nombre: 'Ana Pérez',
  usuario_email: 'ana@example.com',
  tipo_accion: 'modificar_precio_clasica',
  valores_anteriores: { precio_lista_ml: 98500 },
  valores_nuevos: { precio_lista_ml: 102000.5 },
  // Naive UTC, as the server stores it: 14:30 UTC is 11:30 in Buenos Aires.
  fecha_cambio: '2026-10-20T14:30:00',
  comentario: null,
  ...overrides,
});

const renderTab = () => render(<ProductChangesTab productItemId={4101} />);

beforeEach(() => {
  productosAPI.auditoria.mockReset();
  productosAPI.auditoria.mockResolvedValue({ data: [entry()] });
});

describe('each change', () => {
  it('says when, who and what changed, value by value', async () => {
    renderTab();
    const card = await screen.findByRole('article');

    expect(productosAPI.auditoria).toHaveBeenCalledWith(4101);
    expect(card).toHaveTextContent('Precio Clásica');
    expect(card).toHaveTextContent('Ana Pérez');
    expect(card).toHaveTextContent('ana@example.com');
    expect(card).toHaveTextContent('20/10/2026');
    expect(card).toHaveTextContent('11:30');
    const line = within(card).getByText('Precio lista ml').closest('[data-line]');
    expect(line).toHaveTextContent('98.500');
    expect(line).toHaveTextContent('102.000,5');
  });

  it('lists the changes newest first, as the server sends them', async () => {
    productosAPI.auditoria.mockResolvedValue({
      data: [entry({ id: 2, tipo_accion: 'activar_rebate' }), entry({ id: 1 })],
    });
    renderTab();
    const cards = await screen.findAllByRole('article');
    expect(cards.map((card) => card.querySelector('h4').textContent)).toEqual(['Activar rebate', 'Precio Clásica']);
  });

  it('a value only before or only after, a yes/no and a nested value all read in words', async () => {
    productosAPI.auditoria.mockResolvedValue({
      data: [
        entry({
          tipo_accion: 'ml_vinculo_manual',
          valores_anteriores: { out_of_cards: false, quitado: 'X' },
          valores_nuevos: { out_of_cards: true, vinculo: { mla: 'MLA1' } },
        }),
      ],
    });
    renderTab();
    const card = await screen.findByRole('article');
    expect(card).toHaveTextContent('Vínculo manual a publicación');
    expect(within(card).getByText('Out of cards').closest('[data-line]')).toHaveTextContent(/No\s*→\s*Sí/);
    expect(within(card).getByText('Quitado').closest('[data-line]')).toHaveTextContent(/X\s*→\s*—/);
    expect(within(card).getByText('Vinculo').closest('[data-line]')).toHaveTextContent('{"mla":"MLA1"}');
  });

  it('an unknown kind of change gets a generic label, never its code', async () => {
    productosAPI.auditoria.mockResolvedValue({ data: [entry({ tipo_accion: 'algo_nuevo' })] });
    renderTab();
    const card = await screen.findByRole('article');
    expect(card.querySelector('h4')).toHaveTextContent('Otro cambio');
    expect(card).not.toHaveTextContent('algo_nuevo');
  });

  it('shows the comment when there is one', async () => {
    productosAPI.auditoria.mockResolvedValue({ data: [entry({ comentario: 'Ajuste por lista nueva' })] });
    renderTab();
    expect(await screen.findByRole('article')).toHaveTextContent('Ajuste por lista nueva');
  });
});

describe('the tab', () => {
  it('says so when the app has no change for the product', async () => {
    productosAPI.auditoria.mockResolvedValue({ data: [] });
    renderTab();
    expect(await screen.findByText('No hay cambios hechos desde la app en este producto.')).toBeInTheDocument();
  });

  it('a failure says so and retries', async () => {
    productosAPI.auditoria.mockRejectedValueOnce(httpError(500));
    const user = userEvent.setup();
    renderTab();
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo cargar el historial de cambios.');
    await user.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByRole('article')).toBeInTheDocument();
    expect(productosAPI.auditoria).toHaveBeenCalledTimes(2);
  });

  it('a 403 names the permission', async () => {
    productosAPI.auditoria.mockRejectedValue(httpError(403));
    renderTab();
    expect(await screen.findByRole('alert')).toHaveTextContent('No tenés permiso para ver el historial de cambios.');
  });
});

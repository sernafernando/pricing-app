/**
 * ProductEnvioChoice: the product's shipping-cost choice (S7b) in the product panel's Precios tab. The API client is
 * mocked at its boundary; the permission comes from the mocked `usePermisos`.
 *
 * Costs are RE200's production figures (MLA1173065146 = 7290, MLA2517958828 = 10890, one publication at 8290 whose id
 * is unknown, `MLA_A` here); the units and the other synthetic ids (`MLA_B`...) are synthetic.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductEnvioChoice from './ProductEnvioChoice';
import { publicacionesMlAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  publicacionesMlAPI: { productEnvio: vi.fn(), saveProductEnvio: vi.fn() },
}));

let granted = new Set();
vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

const EDITAR = 'productos.editar_precio_clasica';

const publication = (mla, extra = {}) => ({
  mla,
  costo: 8290,
  unidades: 0,
  mas_vendida: false,
  tipo: 'gold_special',
  logistica: 'drop_off',
  ...extra,
});

function options(overrides = {}) {
  return {
    item_id: 22,
    date_from: '2026-10-13',
    date_to: '2026-11-11',
    publicaciones: [
      publication('MLA1173065146', { costo: 7290, unidades: 42, mas_vendida: true }),
      publication('MLA2517958828', { costo: 10890, unidades: 18, tipo: 'gold_pro', logistica: 'cross_docking' }),
      publication('MLA_A', { unidades: 10, logistica: 'fulfillment' }),
    ],
    promedio: 8823.33,
    ponderado: 8140.86,
    max: 10890,
    eleccion: { modo: 'max', mla: null, costo: 10890, warning: null, usuario_id: null, usuario_nombre: null, updated_at: null },
    ...overrides,
  };
}

const row = (name) => screen.getByRole('radio', { name: new RegExp(name) }).closest('label');
const save = () => screen.getByRole('button', { name: 'Guardar elección' });

function renderChoice(data = options(), props = {}) {
  publicacionesMlAPI.productEnvio.mockResolvedValue({ data });
  const onSaved = vi.fn();
  render(<ProductEnvioChoice productItemId={22} onSaved={onSaved} {...props} />);
  return { onSaved };
}

describe('ProductEnvioChoice', () => {
  beforeEach(() => {
    publicacionesMlAPI.productEnvio.mockReset();
    publicacionesMlAPI.saveProductEnvio.mockReset();
    granted = new Set([EDITAR]);
  });

  it('reads the options of the product for the default period', async () => {
    renderChoice();
    await screen.findByText('Máximo (actual)');
    expect(publicacionesMlAPI.productEnvio).toHaveBeenCalledWith(22);
    expect(screen.getByText(/Período:/).textContent).toBe('Período: últimos 30 días · 70 unidades');
  });

  it('shows every option with its amount, the publications with their chips and the most sold flagged', async () => {
    renderChoice();
    await screen.findByText('Máximo (actual)');
    expect(row('Máximo')).toHaveTextContent('Valor por defecto si no elegís otro');
    expect(row('Máximo')).toHaveTextContent('$ 10.890,00');
    expect(row('Promedio')).toHaveTextContent('Promedio simple de 3 publicaciones activas');
    expect(row('Promedio')).toHaveTextContent('$ 8.823,33');
    expect(row('Ponderado')).toHaveTextContent('Según ventas del período seleccionado · se guarda con los últimos 30 días');
    expect(row('Ponderado')).toHaveTextContent('$ 8.140,86');
    expect(screen.getByText('3 publicaciones')).toBeInTheDocument();

    const top = row('MLA1173065146');
    for (const text of ['Clásica', 'Mercado Envíos', '42 u.', '(más vendida)', '$ 7.290,00']) expect(top).toHaveTextContent(text);
    const outlier = row('MLA2517958828');
    for (const text of ['Premium', 'Colecta', '18 u.', '$ 10.890,00']) expect(outlier).toHaveTextContent(text);
    expect(outlier).not.toHaveTextContent('más vendida');
    expect(row('MLA_A')).toHaveTextContent('Full');
  });

  it('marks the stored choice as selected and checks it', async () => {
    renderChoice(options({ eleccion: { ...options().eleccion, modo: 'mla', mla: 'MLA1173065146', costo: 7290 } }));
    await screen.findByText('Máximo (actual)');
    expect(within(row('MLA1173065146')).getByText('Seleccionado')).toBeInTheDocument();
    expect(screen.getAllByText('Seleccionado')).toHaveLength(1);
    expect(screen.getByRole('radio', { name: /MLA1173065146/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: /Máximo/ })).not.toBeChecked();
  });

  it('a publication without a cost cannot be chosen and says so', async () => {
    renderChoice(options({ publicaciones: [...options().publicaciones, publication('MLA_B', { costo: null })] }));
    await screen.findByText('Máximo (actual)');
    expect(screen.getByRole('radio', { name: /MLA_B/ })).toBeDisabled();
    expect(row('MLA_B')).toHaveTextContent('Sin costo');
    expect(row('Promedio')).toHaveTextContent('Promedio simple de 3 publicaciones activas');
  });

  it('Guardar is disabled until the selection differs from the stored one', async () => {
    renderChoice();
    await screen.findByText('Máximo (actual)');
    expect(save()).toBeDisabled();
    await userEvent.click(screen.getByRole('radio', { name: /Promedio/ }));
    expect(save()).toBeEnabled();
    await userEvent.click(screen.getByRole('radio', { name: /Máximo/ }));
    expect(save()).toBeDisabled();
  });

  it('saves promedio, reads the options again and asks the panel to reload its list', async () => {
    const { onSaved } = renderChoice();
    await screen.findByText('Máximo (actual)');
    publicacionesMlAPI.saveProductEnvio.mockResolvedValue({ data: {} });
    publicacionesMlAPI.productEnvio.mockResolvedValue({
      data: options({
        eleccion: { ...options().eleccion, modo: 'promedio', costo: 8823.33, usuario_id: 7, usuario_nombre: 'Ana Pérez', updated_at: '2026-11-11T14:05:00' },
      }),
    });
    await userEvent.click(screen.getByRole('radio', { name: /Promedio/ }));
    await userEvent.click(save());
    expect(publicacionesMlAPI.saveProductEnvio).toHaveBeenCalledWith(22, { modo: 'promedio' });
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(publicacionesMlAPI.productEnvio).toHaveBeenCalledTimes(2);
    expect(await screen.findByText('Último cambio: Ana Pérez · 11/11 14:05')).toBeInTheDocument();
    expect(within(row('Promedio')).getByText('Seleccionado')).toBeInTheDocument();
    expect(save()).toBeDisabled();
  });

  it('saves a publication with its MLA', async () => {
    renderChoice();
    await screen.findByText('Máximo (actual)');
    publicacionesMlAPI.saveProductEnvio.mockResolvedValue({ data: {} });
    await userEvent.click(screen.getByRole('radio', { name: /MLA1173065146/ }));
    await userEvent.click(save());
    expect(publicacionesMlAPI.saveProductEnvio).toHaveBeenCalledWith(22, { modo: 'mla', mla: 'MLA1173065146' });
  });

  it("shows the server's message when the save fails, and keeps the selection", async () => {
    const { onSaved } = renderChoice();
    await screen.findByText('Máximo (actual)');
    publicacionesMlAPI.saveProductEnvio.mockRejectedValue({
      response: { status: 422, data: { error: { code: 'validation_error', message: 'La publicación MLA_A no es de este producto' } } },
    });
    await userEvent.click(screen.getByRole('radio', { name: /MLA_A/ }));
    await userEvent.click(save());
    expect(await screen.findByRole('alert')).toHaveTextContent('La publicación MLA_A no es de este producto');
    expect(screen.getByRole('radio', { name: /MLA_A/ })).toBeChecked();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('says when nothing was ever chosen', async () => {
    renderChoice();
    expect(await screen.findByText('Sin elección guardada: usa el máximo')).toBeInTheDocument();
  });

  it('warns, with the backend data, when the chosen publication fell back to the maximum', async () => {
    renderChoice(
      options({
        eleccion: { ...options().eleccion, modo: 'mla', mla: 'MLA_C', warning: 'La publicación MLA_C elegida no está activa...' },
      }),
    );
    const warning = await screen.findByRole('note');
    expect(warning).toHaveTextContent(
      'La publicación elegida (MLA_C) está pausada o sin costo: se usa el máximo ($ 10.890,00) hasta que elijas otra.',
    );
  });

  it('without sales in the period ponderado says it uses the promedio and shows its amount', async () => {
    renderChoice(options({ ponderado: null }));
    await screen.findByText('Máximo (actual)');
    expect(row('Ponderado')).toHaveTextContent('Sin ventas en el período: usa el promedio');
    expect(row('Ponderado')).toHaveTextContent('$ 8.823,33');
  });

  it('a read-only user sees the stored choice but cannot change it', async () => {
    granted = new Set();
    renderChoice(options({ eleccion: { ...options().eleccion, modo: 'promedio' } }));
    await screen.findByText('Máximo (actual)');
    expect(within(row('Promedio')).getByText('Seleccionado')).toBeInTheDocument();
    for (const radio of screen.getAllByRole('radio')) expect(radio).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Guardar elección' })).not.toBeInTheDocument();
  });

  it('shows the first 4 publications and expands the rest', async () => {
    const many = ['MLA_A', 'MLA_B', 'MLA_C', 'MLA_D', 'MLA_E', 'MLA_F'].map((mla, i) => publication(mla, { unidades: 10 - i }));
    renderChoice(options({ publicaciones: many }));
    await screen.findByText('Máximo (actual)');
    expect(screen.getByRole('radio', { name: /MLA_D/ })).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: /MLA_E/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Ver las 2 restantes' }));
    expect(screen.getByRole('radio', { name: /MLA_F/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Ver menos' }));
    expect(screen.queryByRole('radio', { name: /MLA_E/ })).not.toBeInTheDocument();
  });

  it("a failed read shows the server's message and retries", async () => {
    publicacionesMlAPI.productEnvio.mockRejectedValueOnce({
      response: {
        status: 503,
        data: { error: { code: 'envio_no_disponible', message: 'No se pudieron leer los costos de envío de Mercado Libre; reintentá.' } },
      },
    });
    publicacionesMlAPI.productEnvio.mockResolvedValueOnce({ data: options() });
    render(<ProductEnvioChoice productItemId={22} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron leer los costos de envío de Mercado Libre; reintentá.');
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByText('Máximo (actual)')).toBeInTheDocument();
  });
});

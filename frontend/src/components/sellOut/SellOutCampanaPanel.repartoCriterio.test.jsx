/**
 * SellOutCampanaPanel: (re)split a `monto_total` campaign by a criterion (S3, S6): equal parts, by units sold, or by
 * cost, previewed per product (`GET /reparto/vista-previa`) before saving with the existing `PUT /reparto`
 * (`{ repartos: [], criterio }`). Only a user without brand restriction (admin or `sell_out.gestionar`) gets it; a PM
 * with `sell_out.repartir` keeps the manual reparto.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api, { productosAPI } from '../../services/api';
import { CAMPANA_MONTO_TOTAL, CONSUMOS_USD, VISTAS_PREVIAS } from './sellOutFixtures';
import SellOutCampanaPanel from './SellOutCampanaPanel';

// The HTTP layer, so the real `sellOutAPI` sends what is asserted (URL, query, body).
vi.mock('../../services/api', () => ({ default: { get: vi.fn(), put: vi.fn() }, productosAPI: { listar: vi.fn() } }));
const permisosActuales = vi.hoisted(() => ({ lista: [] }));
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (p) => permisosActuales.lista.includes(p) }),
}));

const GRUPOS = [{ id: 1, nombre: 'TP-Link redes' }];

const URL = '/sell-out/campanas/70';
const servidor = vi.hoisted(() => ({ campanas: [], vista: null }));

/** `GET`s as the API answers them: the campaign (the next stored one on each read), its credits, the preview. */
function responder(url, config) {
  if (url === `${URL}/consumos`) return Promise.resolve({ data: CONSUMOS_USD });
  if (url === `${URL}/reparto/vista-previa`) return servidor.vista(config.params.criterio);
  if (url === URL) return Promise.resolve({ data: servidor.campanas.length > 1 ? servidor.campanas.shift() : servidor.campanas[0] });
  return Promise.reject(new Error(`unexpected GET ${url}`));
}

function abrir(campana, { permisos = [], puedeGestionar = false, onSaved = () => {}, despues } = {}) {
  servidor.campanas = despues ? [campana, despues] : [campana];
  permisosActuales.lista = permisos;
  return render(
    <SellOutCampanaPanel campanaId={campana.id} grupos={GRUPOS} puedeGestionar={puedeGestionar} onSaved={onSaved} onClose={() => {}} />,
  );
}

const reparto = () => screen.getByRole('region', { name: 'Reparto del monto total' });
const resumen = (label) => within(reparto()).getByText(label, { selector: 'dt' }).nextElementSibling;
const GESTOR = { puedeGestionar: true, permisos: ['sell_out.ver', 'sell_out.gestionar'] };

beforeEach(() => {
  vi.clearAllMocks();
  permisosActuales.lista = [];
  servidor.vista = (criterio) => Promise.resolve({ data: VISTAS_PREVIAS[criterio] });
  api.get.mockImplementation(responder);
  productosAPI.listar.mockResolvedValue({ data: { productos: [], total: 0, page: 1, page_size: 10 } });
});

describe('SellOutReparto — split by criterion (S3, S6)', () => {
  it('shows the stored criterion; none stored is the manual reparto', async () => {
    abrir({ ...CAMPANA_MONTO_TOTAL, reparto_criterio: null }, { permisos: ['sell_out.ver'] });
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(resumen('Criterio')).toHaveTextContent('Manual');
  });

  it('shows the stored criterion by its name', async () => {
    abrir({ ...CAMPANA_MONTO_TOTAL, reparto_criterio: 'unidades' }, { permisos: ['sell_out.ver'] });
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(resumen('Criterio')).toHaveTextContent('Según unidades vendidas');
  });

  it.each([
    ['iguales', 'Partes iguales por modelo', ['$ 1.000.000,00', '$ 1.000.000,00']],
    ['unidades', 'Según unidades vendidas', ['$ 1.500.000,00', '$ 500.000,00']],
    ['costo', 'Proporcional al costo', ['$ 1.296.551,72', '$ 703.448,28']],
  ])('%s: previews the split per product, then saves it with the PUT and its criterion', async (criterio, label, montos) => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    const guardada = { ...CAMPANA_MONTO_TOTAL, reparto_criterio: criterio, updated_at: '2026-11-07T12:00:00Z' };
    api.put.mockResolvedValue({ data: guardada });
    abrir(CAMPANA_MONTO_TOTAL, { ...GESTOR, onSaved, despues: guardada });
    await screen.findByRole('region', { name: 'Reparto del monto total' });

    const selector = within(reparto()).getByLabelText('Repartir según');
    expect(within(selector).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Partes iguales por modelo',
      'Según unidades vendidas',
      'Proporcional al costo',
    ]);
    await user.selectOptions(selector, label);
    await user.click(within(reparto()).getByRole('button', { name: 'Ver reparto' }));
    expect(api.get).toHaveBeenCalledWith(`${URL}/reparto/vista-previa`, { params: { criterio } });

    const vista = await within(reparto()).findByRole('table', { name: 'Vista previa del reparto' });
    const filas = within(vista).getAllByRole('row').slice(1);
    expect(filas.map((f) => within(f).getAllByRole('cell').map((c) => c.textContent))).toEqual([
      ['C13T00R120', '12', montos[0]],
      ['C11CJ21301', '4', montos[1]],
    ]);
    expect(within(reparto()).getByTestId('vista-sin-asignar')).toHaveTextContent('Sin asignar $ 0,00');
    expect(api.put).not.toHaveBeenCalled();

    await user.click(within(reparto()).getByRole('button', { name: 'Aplicar reparto' }));
    expect(api.put).toHaveBeenCalledTimes(1);
    expect(api.put).toHaveBeenCalledWith(`${URL}/reparto`, { repartos: [], criterio });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(guardada));
  });

  it('by units sold, the preview says it follows sales and returns in the dates', async () => {
    const user = userEvent.setup();
    abrir(CAMPANA_MONTO_TOTAL, GESTOR);
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    await user.selectOptions(within(reparto()).getByLabelText('Repartir según'), 'unidades');
    await user.click(within(reparto()).getByRole('button', { name: 'Ver reparto' }));
    await within(reparto()).findByRole('table', { name: 'Vista previa del reparto' });
    expect(within(reparto()).getByText(/se recalcula con cada venta o devolución/)).toBeInTheDocument();
  });

  it('in equal parts, the preview says only the products with sales get a part', async () => {
    const user = userEvent.setup();
    abrir(CAMPANA_MONTO_TOTAL, GESTOR);
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    await user.selectOptions(within(reparto()).getByLabelText('Repartir según'), 'iguales');
    await user.click(within(reparto()).getByRole('button', { name: 'Ver reparto' }));
    await within(reparto()).findByRole('table', { name: 'Vista previa del reparto' });
    expect(within(reparto()).getByText(/un producto sin ventas no recibe parte/)).toBeInTheDocument();
  });

  it('a split in equal parts is provisional until the range ends', async () => {
    abrir({ ...CAMPANA_MONTO_TOTAL, reparto_criterio: 'iguales', items: [], fecha_hasta: '2999-12-31' }, GESTOR);
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(within(reparto()).getByTestId('reparto-provisional')).toHaveTextContent(
      'Provisional: se reparte en partes iguales entre los productos con ventas hasta hoy; al terminar el rango queda entre los que vendieron.',
    );
  });

  it('once the range is over, a split in equal parts is no longer provisional', async () => {
    abrir({ ...CAMPANA_MONTO_TOTAL, reparto_criterio: 'iguales', items: [], fecha_hasta: '2000-01-31' }, { permisos: ['sell_out.ver', 'sell_out.repartir'] });
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(within(reparto()).queryByTestId('reparto-provisional')).not.toBeInTheDocument();
    expect(within(reparto()).queryByText(/Todavía no se repartió/)).not.toBeInTheDocument();
    expect(within(reparto()).getByText(/entre los productos que vendieron/)).toBeInTheDocument();
  });

  it('a split by units sold is never labeled provisional', async () => {
    abrir({ ...CAMPANA_MONTO_TOTAL, reparto_criterio: 'unidades', items: [], fecha_hasta: '2999-12-31' }, GESTOR);
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(within(reparto()).queryByTestId('reparto-provisional')).not.toBeInTheDocument();
  });

  it('cancelling the preview saves nothing', async () => {
    const user = userEvent.setup();
    abrir(CAMPANA_MONTO_TOTAL, GESTOR);
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    await user.click(within(reparto()).getByRole('button', { name: 'Ver reparto' }));
    await within(reparto()).findByRole('table', { name: 'Vista previa del reparto' });
    await user.click(within(reparto()).getByRole('button', { name: 'Cancelar' }));
    expect(within(reparto()).queryByRole('table', { name: 'Vista previa del reparto' })).not.toBeInTheDocument();
    expect(api.put).not.toHaveBeenCalled();
  });

  it("shows the API's message when the preview is refused", async () => {
    const user = userEvent.setup();
    servidor.vista = () => Promise.reject({ response: { status: 403, data: { detail: 'No podés repartir por criterio' } } });
    abrir(CAMPANA_MONTO_TOTAL, GESTOR);
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    await user.click(within(reparto()).getByRole('button', { name: 'Ver reparto' }));
    expect(await within(reparto()).findByRole('alert')).toHaveTextContent('No podés repartir por criterio');
  });

  it('the manual reparto still saves its shares with no criterion', async () => {
    const user = userEvent.setup();
    api.put.mockResolvedValue({ data: CAMPANA_MONTO_TOTAL });
    abrir(CAMPANA_MONTO_TOTAL, GESTOR);
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    await user.click(within(reparto()).getByRole('button', { name: 'Guardar reparto' }));
    // As today: the shares only, no `criterio` (the API then stores the reparto as manual).
    expect(api.put).toHaveBeenCalledWith(`${URL}/reparto`, {
      repartos: [
        { item_id: 4172, reparto_porcentaje: '60.0000' },
        { item_id: 4173, reparto_monto: '500000.00' },
      ],
    });
  });

  it('a PM with only sell_out.repartir keeps the manual reparto, without the criterion split', async () => {
    abrir(CAMPANA_MONTO_TOTAL, { permisos: ['sell_out.ver', 'sell_out.repartir'] });
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(within(reparto()).getByRole('button', { name: 'Guardar reparto' })).toBeInTheDocument();
    expect(within(reparto()).queryByLabelText('Repartir según')).not.toBeInTheDocument();
    expect(within(reparto()).queryByRole('button', { name: 'Ver reparto' })).not.toBeInTheDocument();
  });

  it('a PM with only sell_out.repartir sees a criterion split read-only: no manual editor, the API would refuse it', async () => {
    abrir({ ...CAMPANA_MONTO_TOTAL, reparto_criterio: 'costo' }, { permisos: ['sell_out.ver', 'sell_out.repartir'] });
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(resumen('Criterio')).toHaveTextContent('Proporcional al costo');
    expect(within(reparto()).queryByRole('button', { name: 'Guardar reparto' })).not.toBeInTheDocument();
    expect(within(reparto()).queryByRole('group', { name: 'Agregar producto' })).not.toBeInTheDocument();
    expect(within(reparto()).queryByLabelText('Repartir según')).not.toBeInTheDocument();
    expect(within(reparto()).getByText(/Solo un administrador o quien gestiona campañas puede cambiarlo/)).toBeInTheDocument();
    // The stored shares stay visible, read-only.
    expect(within(reparto()).getByRole('table')).toHaveTextContent('C13T00R120');
  });

  it('a split by units sold with no stored shares does not read as "not split yet"', async () => {
    abrir({ ...CAMPANA_MONTO_TOTAL, reparto_criterio: 'unidades', items: [] }, { permisos: ['sell_out.ver', 'sell_out.repartir'] });
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(within(reparto()).queryByText(/Todavía no se repartió/)).not.toBeInTheDocument();
    expect(within(reparto()).getByText(/sigue las ventas y devoluciones/)).toBeInTheDocument();
    expect(within(reparto()).queryByRole('button', { name: 'Guardar reparto' })).not.toBeInTheDocument();
  });

  it('with a criterion stored, a manager keeps both the criterion split and the manual editor', async () => {
    abrir({ ...CAMPANA_MONTO_TOTAL, reparto_criterio: 'iguales' }, GESTOR);
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(within(reparto()).getByLabelText('Repartir según')).toHaveValue('iguales');
    expect(within(reparto()).getByRole('button', { name: 'Guardar reparto' })).toBeInTheDocument();
  });

  it('a voided campaign offers no criterion split', async () => {
    abrir({ ...CAMPANA_MONTO_TOTAL, estado: 'anulada' }, GESTOR);
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(within(reparto()).queryByLabelText('Repartir según')).not.toBeInTheDocument();
  });
});

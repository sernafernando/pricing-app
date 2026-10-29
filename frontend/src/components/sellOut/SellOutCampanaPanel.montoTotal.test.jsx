/**
 * SellOutCampanaPanel: `monto_total` campaigns (T26d, S34/S35): one amount (negative = a deduction) split by hand
 * per product, each share a % of the total or a fixed amount, by the PM (`sell_out.repartir`) or a manager.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { productosAPI } from '../../services/api';
import { sellOutAPI } from '../../services/sellOutAPI';
import { CAMPANA_MONTO_TOTAL, CAMPANA_MONTO_TOTAL_NEGATIVA, CONSUMOS_USD } from './sellOutFixtures';
import SellOutCampanaPanel from './SellOutCampanaPanel';
import SellOutCampanasTable from './SellOutCampanasTable';

vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: {
    listar: vi.fn(),
    detalle: vi.fn(),
    crear: vi.fn(),
    editar: vi.fn(),
    anular: vi.fn(),
    definirTipoCambio: vi.fn(),
    consumos: vi.fn(),
    repartir: vi.fn(),
  },
}));
vi.mock('../../services/api', () => ({ productosAPI: { listar: vi.fn() } }));
const permisosActuales = vi.hoisted(() => ({ lista: [] }));
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (p) => permisosActuales.lista.includes(p) }),
}));

const GRUPOS = [
  { id: 1, nombre: 'TP-Link redes' },
  { id: 2, nombre: 'LENOVO' },
];
const PRODUCTOS = [{ item_id: 4180, codigo: 'ARCHER-C6', descripcion: 'TP-Link Archer C6', marca: 'TP-LINK' }];

function abrir(campana, { permisos = [], puedeGestionar = false, onSaved = () => {} } = {}) {
  sellOutAPI.detalle.mockResolvedValue({ data: campana });
  permisosActuales.lista = permisos;
  return render(
    <SellOutCampanaPanel campanaId={campana.id} grupos={GRUPOS} puedeGestionar={puedeGestionar} onSaved={onSaved} onClose={() => {}} />,
  );
}

const reparto = () => screen.getByRole('region', { name: 'Reparto del monto total' });
const resumen = (label) => within(reparto()).getByText(label, { selector: 'dt' }).nextElementSibling;
const enVivo = () => within(reparto()).getByTestId('reparto-en-vivo');

beforeEach(() => {
  vi.clearAllMocks();
  permisosActuales.lista = [];
  sellOutAPI.consumos.mockResolvedValue({ data: CONSUMOS_USD });
  productosAPI.listar.mockResolvedValue({ data: { productos: PRODUCTOS, total: 1, page: 1, page_size: 10 } });
});

describe('SellOutCampanaForm — monto total kind (T26d)', () => {
  it('a third kind: one total that accepts a negative, no caps, no per-product amounts; sends no items', async () => {
    const user = userEvent.setup();
    sellOutAPI.crear.mockResolvedValue({ data: { ...CAMPANA_MONTO_TOTAL_NEGATIVA, id: 96 } });
    render(<SellOutCampanaPanel campanaId={null} grupos={GRUPOS} puedeGestionar onSaved={() => {}} onClose={() => {}} />);

    await user.click(screen.getByRole('button', { name: 'Monto total' }));
    expect(screen.queryByLabelText('Monto por unidad')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Porcentaje')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Tope de unidades')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Tope de monto/)).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Montos por producto' })).not.toBeInTheDocument();
    expect(screen.getByText(/Negativo: descuenta de la ganancia/)).toBeInTheDocument();

    await user.type(screen.getByLabelText('Nombre'), 'LENOVO cta y orden');
    await user.type(screen.getByLabelText('Monto total (USD)'), '-13662075');
    await user.type(screen.getByLabelText('Desde'), '2026-07-01');
    await user.type(screen.getByLabelText('Hasta'), '2026-09-30');
    await user.click(screen.getByRole('checkbox', { name: 'LENOVO' }));
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));

    const body = sellOutAPI.crear.mock.calls[0][0];
    expect(body).toEqual(
      expect.objectContaining({
        tipo: 'monto_total',
        monto_total: '-13662075',
        monto_unit: null,
        porcentaje: null,
        tope_unidades: null,
        tope_monto: null,
        grupo_ids: [2],
      }),
    );
    expect(body).not.toHaveProperty('items');
  });

  it('asks for the total when it is empty or 0', async () => {
    const user = userEvent.setup();
    render(<SellOutCampanaPanel campanaId={null} grupos={GRUPOS} puedeGestionar onSaved={() => {}} onClose={() => {}} />);
    await user.click(screen.getByRole('button', { name: 'Monto total' }));
    await user.type(screen.getByLabelText('Monto total (USD)'), '0');
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Faltan datos: nombre, fechas, monto total, productos alcanzados.');
    expect(sellOutAPI.crear).not.toHaveBeenCalled();
  });

  it('editing a monto total campaign keeps its shares: the body sends no items', async () => {
    const user = userEvent.setup();
    sellOutAPI.editar.mockResolvedValue({ data: CAMPANA_MONTO_TOTAL });
    abrir(CAMPANA_MONTO_TOTAL, { puedeGestionar: true, permisos: ['sell_out.gestionar'] });

    const total = await screen.findByLabelText('Monto total (ARS)');
    expect(total).toHaveValue(2000000);
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));
    const [, body] = sellOutAPI.editar.mock.calls[0];
    expect(body).toEqual(expect.objectContaining({ tipo: 'monto_total', monto_total: '2000000.00' }));
    expect(body).not.toHaveProperty('items');
  });
});

describe('SellOutCampanaPanel — reparto of a monto total campaign (T26d)', () => {
  it('read-only with sell_out.ver: the server summary, the note and the shares, nothing to edit', async () => {
    abrir(CAMPANA_MONTO_TOTAL);

    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(screen.getByText('Beneficio', { selector: 'dt' }).nextElementSibling).toHaveTextContent('Monto total $ 2.000.000,00');
    expect(resumen('Asignado')).toHaveTextContent('$ 1.700.000,00');
    expect(resumen('Asignado sin ventas')).toHaveTextContent('$ 500.000,00');
    expect(resumen('Sin asignar')).toHaveTextContent('$ 300.000,00');
    expect(within(reparto()).getByText(/suma en los totales el 31\/12\/2026, no en la fila de ningún producto/)).toBeInTheDocument();
    const fila = within(reparto()).getByText('C13T00R120').closest('tr');
    expect(fila).toHaveTextContent('60 %');
    expect(fila).toHaveTextContent('$ 1.200.000,00');
    expect(within(reparto()).getByText('C11CJ21301').closest('tr')).toHaveTextContent('$ 500.000,00');
    expect(within(reparto()).queryByRole('button', { name: 'Guardar reparto' })).not.toBeInTheDocument();
    expect(within(reparto()).queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('shows the reason when the stored split cannot be computed', async () => {
    abrir({
      ...CAMPANA_MONTO_TOTAL,
      resumen: {
        ...CAMPANA_MONTO_TOTAL.resumen,
        reparto: { asignado: null, asignado_sin_ventas: null, sin_asignar: null, motivo: 'El producto 4172 no tiene IVA y el monto se cargó con IVA' },
      },
    });
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(resumen('Asignado')).toHaveTextContent('—');
    expect(within(reparto()).getByText('El producto 4172 no tiene IVA y el monto se cargó con IVA')).toBeInTheDocument();
  });

  it('with sell_out.repartir: % / fixed rows, live totals, add a product and save with the PUT', async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    const guardada = { ...CAMPANA_MONTO_TOTAL, updated_at: '2026-10-29T18:00:00Z' };
    sellOutAPI.repartir.mockResolvedValue({ data: { ...guardada, items: [] } });
    abrir(CAMPANA_MONTO_TOTAL, { permisos: ['sell_out.ver', 'sell_out.repartir'], onSaved });
    sellOutAPI.detalle.mockResolvedValueOnce({ data: guardada }); // the read after saving (the mount already read)

    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(screen.queryByRole('region', { name: 'Definición' })).not.toBeInTheDocument(); // repartir does not edit the terms
    expect(enVivo()).toHaveTextContent('Asignado $ 1.700.000,00');
    expect(enVivo()).toHaveTextContent('Sin asignar $ 300.000,00');

    await user.selectOptions(within(reparto()).getByLabelText('Tipo de reparto de C13T00R120'), 'monto');
    const valor = within(reparto()).getByLabelText('Reparto de C13T00R120');
    await user.clear(valor);
    await user.type(valor, '1000000');
    expect(enVivo()).toHaveTextContent('Asignado $ 1.500.000,00');
    expect(enVivo()).toHaveTextContent('Sin asignar $ 500.000,00');

    const buscador = within(reparto()).getByRole('group', { name: 'Agregar producto' });
    await user.type(within(buscador).getByRole('searchbox'), 'archer');
    await user.click(await within(buscador).findByRole('button', { name: /ARCHER-C6/ }));
    await user.type(within(reparto()).getByLabelText('Reparto de ARCHER-C6'), '10');
    expect(enVivo()).toHaveTextContent('Asignado $ 1.700.000,00');
    await user.click(within(reparto()).getByRole('button', { name: 'Quitar C11CJ21301' }));
    expect(enVivo()).toHaveTextContent('Sin asignar $ 800.000,00');

    await user.click(within(reparto()).getByRole('button', { name: 'Guardar reparto' }));
    expect(sellOutAPI.repartir).toHaveBeenCalledWith(70, [
      { item_id: 4172, reparto_monto: '1000000' },
      { item_id: 4180, reparto_porcentaje: '10' },
    ]);
    // The campaign is read again: a scoped PM's PUT answers only their shares, never what the others see.
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(guardada));
    expect(sellOutAPI.detalle).toHaveBeenLastCalledWith(70);
  });

  it('a brand-scoped PM: the other brands\' shares the server keeps count in the live totals and the guard', async () => {
    const user = userEvent.setup();
    // The server assigned 1.700.000; this PM sees only the 60 % share (1.200.000): 500.000 are other brands'.
    abrir({ ...CAMPANA_MONTO_TOTAL, items: [CAMPANA_MONTO_TOTAL.items[0]] }, { permisos: ['sell_out.repartir'] });
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(enVivo()).toHaveTextContent('Asignado $ 1.700.000,00');
    expect(enVivo()).toHaveTextContent('Sin asignar $ 300.000,00');
    expect(within(reparto()).getByText(/\$ 500\.000,00 de productos de otras marcas/)).toBeInTheDocument();

    const valor = within(reparto()).getByLabelText('Reparto de C13T00R120');
    await user.clear(valor);
    await user.type(valor, '80');
    await user.click(within(reparto()).getByRole('button', { name: 'Guardar reparto' }));
    expect(within(reparto()).getByRole('alert')).toHaveTextContent(
      'El reparto ($ 2.100.000,00) supera el monto total ($ 2.000.000,00) en $ 100.000,00',
    );
    expect(sellOutAPI.repartir).not.toHaveBeenCalled();
  });

  it('a negative total: shares and the unassigned part keep its sign', async () => {
    const user = userEvent.setup();
    abrir(CAMPANA_MONTO_TOTAL_NEGATIVA, { permisos: ['sell_out.repartir'] });

    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(resumen('Sin asignar')).toHaveTextContent('$ -13.662.075,00');
    const buscador = within(reparto()).getByRole('group', { name: 'Agregar producto' });
    await user.type(within(buscador).getByRole('searchbox'), 'archer');
    await user.click(await within(buscador).findByRole('button', { name: /ARCHER-C6/ }));
    await user.type(within(reparto()).getByLabelText('Reparto de ARCHER-C6'), '60');
    expect(enVivo()).toHaveTextContent('Asignado $ -8.197.245,00');
    expect(enVivo()).toHaveTextContent('Sin asignar $ -5.464.830,00');
  });

  it('guards like the API: a share over the total, or a fixed share with the opposite sign, sends nothing', async () => {
    const user = userEvent.setup();
    abrir(CAMPANA_MONTO_TOTAL, { permisos: ['sell_out.repartir'] });
    await screen.findByRole('region', { name: 'Reparto del monto total' });

    const valor = within(reparto()).getByLabelText('Reparto de C11CJ21301');
    await user.clear(valor);
    await user.type(valor, '900000');
    await user.click(within(reparto()).getByRole('button', { name: 'Guardar reparto' }));
    expect(within(reparto()).getByRole('alert')).toHaveTextContent(
      'El reparto ($ 2.100.000,00) supera el monto total ($ 2.000.000,00) en $ 100.000,00',
    );

    await user.clear(valor);
    await user.type(valor, '-5');
    await user.click(within(reparto()).getByRole('button', { name: 'Guardar reparto' }));
    expect(within(reparto()).getByRole('alert')).toHaveTextContent('El reparto del producto C11CJ21301 tiene que tener el signo del monto total');
    expect(sellOutAPI.repartir).not.toHaveBeenCalled();
  });

  it('shows the API 422 / 403 message', async () => {
    const user = userEvent.setup();
    sellOutAPI.repartir.mockRejectedValueOnce({
      response: { status: 403, data: { detail: 'El producto 4173 (C11CJ21301) no es de tus marcas' } },
    });
    abrir(CAMPANA_MONTO_TOTAL, { permisos: ['sell_out.repartir'] });
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    await user.click(within(reparto()).getByRole('button', { name: 'Guardar reparto' }));
    expect(await within(reparto()).findByRole('alert')).toHaveTextContent('El producto 4173 (C11CJ21301) no es de tus marcas');
  });

  it('a voided campaign is read-only even with sell_out.repartir', async () => {
    abrir({ ...CAMPANA_MONTO_TOTAL, estado: 'anulada' }, { permisos: ['sell_out.repartir'] });
    await screen.findByRole('region', { name: 'Reparto del monto total' });
    expect(within(reparto()).queryByRole('button', { name: 'Guardar reparto' })).not.toBeInTheDocument();
  });
});

describe('SellOutCampanasTable — monto total (T26d)', () => {
  it('shows the kind and the total, a negative one as a deduction', () => {
    render(<SellOutCampanasTable campanas={[CAMPANA_MONTO_TOTAL, CAMPANA_MONTO_TOTAL_NEGATIVA]} onSelect={() => {}} />);
    const positiva = screen.getByText('TP-Link bono Q4').closest('tr');
    expect(positiva).toHaveTextContent('Monto total $ 2.000.000,00');
    expect(positiva).toHaveTextContent('2 productos con reparto');
    expect(within(positiva).queryByText('Deducción de ganancia')).not.toBeInTheDocument();
    const negativa = screen.getByText('LENOVO cta y orden').closest('tr');
    expect(negativa).toHaveTextContent('Monto total $ -13.662.075,00');
    expect(within(negativa).getByText('Deducción de ganancia')).toBeInTheDocument();
    expect(within(negativa).getByText(/-13\.662\.075/)).toHaveAttribute('data-deduccion', 'true');
  });
});

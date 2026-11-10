/**
 * TacticalNuevo — the "Nuevo tactical" screen (tactical T2), built from the owner-approved OpenDesign screens
 * handoffs/diseno-tactical/nuevo-tactical-aprobado.html (sell out) and nuevo-tactical-sell-in-aprobado.html (sell in).
 * It posts the tactical and all its lines at once to `POST /tacticals` (handoffs/tactical-tarea.md, API contract).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import TacticalNuevo from './TacticalNuevo';
import api, { productosAPI } from '../services/api';
import { CATALOGO, OPERACIONES } from '../components/tactical/tacticalFixtures';
import { TACTICAL_BPS } from '../components/tacticals/tacticalsFixtures';

const mockTienePermiso = vi.fn();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: (codigo) => mockTienePermiso(codigo), cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

/** The list Nuevo tactical goes back to, with the query it lands on (the Tacticals tab). */
function Listado() {
  return <p>{`Listado de sell in${useLocation().search}`}</p>;
}

function renderAt(url) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/sell-in/tactical/nuevo" element={<TacticalNuevo />} />
        <Route path="/sell-in" element={<Listado />} />
      </Routes>
    </MemoryRouter>,
  );
}

const linea = (n) => screen.getByRole('group', { name: `Línea ${n}` });
const crear = () => screen.getAllByRole('button', { name: 'Crear tactical' })[0];

async function fillHeader(user, { nombre = 'Tacticals BPS Noviembre Q1FY27', marca = 'HP' } = {}) {
  await user.type(screen.getByLabelText('Nombre'), nombre);
  await screen.findByRole('option', { name: marca });
  await user.selectOptions(screen.getByLabelText('Marca'), marca);
  await user.type(screen.getByLabelText('Desde'), '2026-11-01');
  await user.type(screen.getByLabelText('Hasta'), '2026-11-30');
}

async function pickProducts(user, n, query, descripciones) {
  await user.click(within(linea(n)).getByRole('button', { name: '+ Producto' }));
  const picker = screen.getByRole('dialog', { name: 'Agregar productos a la línea' });
  await user.type(within(picker).getByLabelText('Buscar productos'), query);
  for (const descripcion of descripciones) {
    await user.click(await within(picker).findByRole('checkbox', { name: new RegExp(descripcion) }));
  }
  await user.click(within(picker).getByRole('button', { name: 'Agregar a la línea' }));
}

beforeEach(() => {
  vi.clearAllMocks();
  mockTienePermiso.mockReturnValue(true);
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['HP', 'TP-Link'] } });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: ['Monitores', 'Notebooks', 'Redes'] } });
  api.get.mockImplementation((url, config) => {
    if (url === '/buscar-productos-catalogo') {
      const words = config.params.q.toLowerCase().split(/\s+/);
      const hits = CATALOGO.filter((p) => words.every((w) => `${p.codigo} ${p.descripcion}`.toLowerCase().includes(w)));
      return Promise.resolve({ data: hits });
    }
    if (url === '/sell-in/compras/operaciones') return Promise.resolve({ data: { items: OPERACIONES } });
    return Promise.resolve({ data: {} });
  });
  api.post.mockResolvedValue({ data: { id: 7 } });
});

describe('the header', () => {
  it('opens on sell out from the Sell out tab, in USD with the exchange-rate mode, and offers no invoice scope', async () => {
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out');
    expect(screen.getByRole('heading', { name: 'Nuevo tactical' })).toBeInTheDocument();
    expect(
      screen.getByText('La marca te paga por cada unidad vendida en el rango. Cargá el tactical y sus líneas en un solo paso.'),
    ).toBeInTheDocument();
    const tipo = screen.getByRole('group', { name: 'Tipo' });
    expect(within(tipo).getByRole('button', { name: 'Sell out' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(screen.getByRole('group', { name: 'Moneda' })).getByRole('button', { name: 'USD' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByLabelText('Tipo de cambio')).toBeInTheDocument();
    expect(screen.getByLabelText('Se acumula con otras campañas')).toBeChecked();
    expect(screen.getByLabelText('Los montos incluyen IVA')).not.toBeChecked();
    expect(within(linea(1)).queryByRole('button', { name: 'Factura' })).not.toBeInTheDocument();
    expect(within(linea(1)).getByRole('button', { name: 'monto total' })).toBeEnabled();
  });

  it('opens on sell in from the Sell in tab, in ARS without the exchange rate, with the invoice scope and total amount', async () => {
    renderAt('/sell-in/tactical/nuevo?tipo=sell_in');
    expect(
      screen.getByText('Baja el costo de lo que vendés en el rango. Cargá el tactical y sus líneas en un solo paso.'),
    ).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: 'Moneda' })).getByRole('button', { name: 'ARS' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.queryByLabelText('Tipo de cambio')).not.toBeInTheDocument();
    expect(within(linea(1)).getByRole('button', { name: 'Factura' })).toBeInTheDocument();
    // In ARS a total amount is offered on products, a brand or a category too, split by a criterion (S4).
    expect(within(linea(1)).getByRole('button', { name: 'monto total' })).toBeEnabled();
  });

  it('on sell in in USD offers a total amount over products only with a fixed exchange rate (S4)', async () => {
    const user = userEvent.setup();
    renderAt('/sell-in/tactical/nuevo?tipo=sell_in');
    await user.click(within(screen.getByRole('group', { name: 'Moneda' })).getByRole('button', { name: 'USD' }));
    await user.click(within(linea(1)).getByRole('button', { name: 'Productos' }));
    expect(within(linea(1)).getByRole('button', { name: 'monto total' })).toBeDisabled();

    await user.selectOptions(screen.getByLabelText('Tipo de cambio'), 'fijo');
    expect(within(linea(1)).getByRole('button', { name: 'monto total' })).toBeEnabled();
  });

  it('offers only the type the user can manage', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.gestionar');
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out');
    const tipo = screen.getByRole('group', { name: 'Tipo' });
    expect(within(tipo).getByRole('button', { name: 'Sell in' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(tipo).getByRole('button', { name: 'Sell out' })).toBeDisabled();
  });

  it('without sell_in.gestionar nor sell_out.gestionar it says so and offers nothing to create', async () => {
    mockTienePermiso.mockImplementation((codigo) => !codigo.endsWith('.gestionar'));
    renderAt('/sell-in/tactical/nuevo?tipo=sell_in');
    expect(screen.getByText('No tenés permiso para crear tacticals.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Crear tactical' })).not.toBeInTheDocument();
  });
});

describe('creating a tactical', () => {
  it('posts a sell out tactical with one product per line, its amount per unit and its unit cap', async () => {
    const user = userEvent.setup();
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out');
    await fillHeader(user);
    await user.type(screen.getByLabelText('Referencia de la marca'), 'Q1 FY27 · BPS');
    await pickProducts(user, 1, 'aio hp g2', ['AIO HP G2 R5 16G 512 W11H']);
    await user.type(within(linea(1)).getByLabelText('Monto de la línea 1'), '220');
    await user.type(within(linea(1)).getByLabelText('Tope de unidades, línea 1'), '90');
    expect(within(linea(1)).getByText('USD 19.800')).toBeInTheDocument();

    await user.click(crear());
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/tacticals', {
        tipo: 'sell_out',
        nombre: 'Tacticals BPS Noviembre Q1FY27',
        marca: 'HP',
        referencia: 'Q1 FY27 · BPS',
        fecha_desde: '2026-11-01',
        fecha_hasta: '2026-11-30',
        moneda: 'USD',
        tc_modo: 'al_cobro',
        incluye_iva: false,
        acumulable: true,
        nota: null,
        todas_tiendas: true,
        tope_compartido: false,
        tiendas: [],
        lineas: [
          {
            alcance: 'productos',
            item_ids: [101],
            modo_monto: 'por_unidad',
            valor: 220,
            tope_unidades: 90,
            tope_monto: null,
            tope_por_producto: true,
          },
        ],
      }),
    );
    expect(await screen.findByText('Listado de sell in?tab=tacticals')).toBeInTheDocument();
  });

  it('posts a sell out total amount split among the line\'s products by the chosen criterion (S1)', async () => {
    const user = userEvent.setup();
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out');
    await fillHeader(user);
    await pickProducts(user, 1, 'notebook hp', ['Notebook HP 250RG10', 'Notebook HP 255r G10']);
    await user.click(within(linea(1)).getByRole('button', { name: 'monto total' }));
    await user.type(within(linea(1)).getByLabelText('Monto de la línea 1'), '1200');

    await user.click(crear());
    expect(await screen.findByText('Hay 1 línea sin reparto del monto total. Completala o eliminala.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();

    await user.selectOptions(within(linea(1)).getByLabelText('Reparto del monto total, línea 1'), 'costo');
    await user.click(crear());
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post.mock.calls[0][1].lineas).toEqual([
      {
        alcance: 'productos',
        item_ids: [103, 104],
        modo_monto: 'monto_total',
        valor: 1200,
        tope_unidades: null,
        tope_monto: null,
        reparto_criterio: 'costo',
      },
    ]);
  });

  it('shares the caps of a line with several products only when asked, and says what it can charge at most', async () => {
    const user = userEvent.setup();
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out');
    await fillHeader(user);
    await pickProducts(user, 1, 'monitor hp', ['Monitor HP V24i G5', 'Monitor HP V27i G5', 'Monitor HP P24 G5']);
    expect(within(linea(1)).getAllByRole('button', { name: /^Quitar Monitor/ })).toHaveLength(3);
    await user.type(within(linea(1)).getByLabelText('Monto de la línea 1'), '12');
    await user.type(within(linea(1)).getByLabelText('Tope de unidades, línea 1'), '300');
    // Per product: each of the three products has its own 300-unit cap.
    expect(within(linea(1)).getByText('USD 10.800')).toBeInTheDocument();
    await user.click(within(linea(1)).getByRole('button', { name: 'Por producto' }));
    expect(within(linea(1)).getByRole('button', { name: 'Compartido' })).toBeInTheDocument();
    await user.type(within(linea(1)).getByLabelText('Tope de monto en USD, línea 1'), '3000');
    expect(within(linea(1)).getByText('USD 3.000')).toBeInTheDocument();

    await user.click(crear());
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post.mock.calls[0][1].lineas).toEqual([
      {
        alcance: 'productos',
        item_ids: [201, 202, 203],
        modo_monto: 'por_unidad',
        valor: 12,
        tope_unidades: 300,
        tope_monto: 3000,
        tope_por_producto: false,
      },
    ]);
  });

  it('posts a sell in tactical with a brand line, a category line and a line per chosen invoice', async () => {
    const user = userEvent.setup();
    renderAt('/sell-in/tactical/nuevo?tipo=sell_in');
    await fillHeader(user, { nombre: 'Rebate TP-Link noviembre', marca: 'TP-Link' });

    await user.click(within(linea(1)).getByRole('button', { name: 'Marca' }));
    await user.selectOptions(within(linea(1)).getByLabelText('Marca de la línea'), 'TP-Link');
    expect(within(linea(1)).getByText('Aplica a todos los productos de la marca.')).toBeInTheDocument();
    await user.click(within(linea(1)).getByRole('button', { name: '%' }));
    await user.type(within(linea(1)).getByLabelText('Monto de la línea 1'), '3,6');

    await user.click(screen.getByRole('button', { name: '+ Agregar línea' }));
    await user.keyboard('{Escape}');
    await user.click(within(linea(2)).getByRole('button', { name: 'Categoría' }));
    await user.selectOptions(within(linea(2)).getByLabelText('Categoría de la línea'), 'Redes');
    await user.click(within(linea(2)).getByRole('button', { name: '%' }));
    await user.type(within(linea(2)).getByLabelText('Monto de la línea 2'), '1,5');

    await user.click(screen.getByRole('button', { name: '+ Agregar línea' }));
    await user.keyboard('{Escape}');
    await user.click(within(linea(3)).getByRole('button', { name: 'Factura' }));
    expect(within(linea(3)).getByRole('button', { name: 'monto total' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(within(linea(3)).getByRole('button', { name: '+ Factura' }));
    const picker = screen.getByRole('dialog', { name: 'Agregar facturas a la línea' });
    expect(within(picker).getByText('El monto se reparte entre los productos de la factura según lo facturado.')).toBeInTheDocument();
    await user.type(within(picker).getByLabelText('Buscar facturas'), '0003');
    await user.click(await within(picker).findByRole('checkbox', { name: /FC A 0003-00012345/ }));
    await user.click(within(picker).getByRole('checkbox', { name: /FC A 0003-00012346/ }));
    await user.click(within(picker).getByRole('button', { name: 'Agregar a la línea' }));
    expect(within(linea(3)).getAllByRole('button', { name: /^Quitar FC A/ })).toHaveLength(2);
    await user.type(within(linea(3)).getByLabelText('Monto de la línea 3'), '850000');

    await user.click(crear());
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const body = api.post.mock.calls[0][1];
    expect(body).toEqual(expect.objectContaining({ tipo: 'sell_in', moneda: 'ARS', marca: 'TP-Link' }));
    // ARS sends no exchange-rate fields (Contrato final).
    expect(body).not.toHaveProperty('tc_modo');
    expect(body).not.toHaveProperty('tipo_cambio');
    const factura = (id) => ({
      alcance: 'factura',
      pedido_compra_id: id,
      modo_monto: 'monto_total',
      valor: 850000,
      tope_unidades: null,
      tope_monto: null,
    });
    expect(body.lineas).toEqual([
      {
        alcance: 'marca',
        marca: 'TP-Link',
        modo_monto: 'porcentaje',
        valor: 3.6,
        tope_unidades: null,
        tope_monto: null,
      },
      {
        alcance: 'categoria',
        categoria: 'Redes',
        modo_monto: 'porcentaje',
        valor: 1.5,
        tope_unidades: null,
        tope_monto: null,
      },
      factura(9001),
      factura(9002),
    ]);
  });

  it('posts a sell in total amount split among the line\'s products by the chosen criterion (S4)', async () => {
    const user = userEvent.setup();
    renderAt('/sell-in/tactical/nuevo?tipo=sell_in');
    await fillHeader(user);
    await pickProducts(user, 1, 'notebook hp', ['Notebook HP 250RG10', 'Notebook HP 255r G10']);
    await user.click(within(linea(1)).getByRole('button', { name: 'monto total' }));
    await user.type(within(linea(1)).getByLabelText('Monto de la línea 1'), '1.200.000');

    await user.click(crear());
    expect(await screen.findByText('Hay 1 línea sin reparto del monto total. Completala o eliminala.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();

    await user.selectOptions(within(linea(1)).getByLabelText('Reparto del monto total, línea 1'), 'unidades');
    await user.click(crear());
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post.mock.calls[0][1]).toEqual(expect.objectContaining({ tipo: 'sell_in', moneda: 'ARS' }));
    expect(api.post.mock.calls[0][1].lineas).toEqual([
      {
        alcance: 'productos',
        item_ids: [103, 104],
        modo_monto: 'monto_total',
        valor: 1200000,
        tope_unidades: null,
        tope_monto: null,
        reparto_criterio: 'unidades',
      },
    ]);
  });

  it('copies and deletes a line', async () => {
    const user = userEvent.setup();
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out');
    await pickProducts(user, 1, 'aio hp g2', ['AIO HP G2 R5 16G 512 W11H']);
    await user.type(within(linea(1)).getByLabelText('Monto de la línea 1'), '220');
    await user.click(within(linea(1)).getByRole('button', { name: 'Duplicar línea 1' }));
    expect(within(linea(2)).getByLabelText('Monto de la línea 2')).toHaveValue('220');
    expect(within(linea(2)).getByRole('button', { name: /^Quitar AIO HP G2/ })).toBeInTheDocument();
    await user.click(within(linea(1)).getByRole('button', { name: 'Eliminar línea 1' }));
    expect(screen.queryByRole('group', { name: 'Línea 2' })).not.toBeInTheDocument();
  });
});

describe('what stops a save', () => {
  it('asks for a name before anything else', async () => {
    const user = userEvent.setup();
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out');
    await user.click(crear());
    expect(await screen.findByText('Poné un nombre para el tactical antes de crearlo.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('names the lines left without products', async () => {
    const user = userEvent.setup();
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out');
    await fillHeader(user);
    await user.click(crear());
    expect(await screen.findByText('Hay 1 línea sin productos. Completala o eliminala.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('shows the backend message naming the line the user sees, even when invoices split it', async () => {
    api.post.mockRejectedValue({
      response: { status: 422, data: { error: { message: 'Línea 2: la factura 9002 ya tiene un sell in con ese tactical.' } } },
    });
    const user = userEvent.setup();
    renderAt('/sell-in/tactical/nuevo?tipo=sell_in');
    await fillHeader(user, { nombre: 'Rebate', marca: 'TP-Link' });
    await user.click(within(linea(1)).getByRole('button', { name: 'Factura' }));
    await user.click(within(linea(1)).getByRole('button', { name: '+ Factura' }));
    const picker = screen.getByRole('dialog', { name: 'Agregar facturas a la línea' });
    await user.type(within(picker).getByLabelText('Buscar facturas'), '0003');
    await user.click(await within(picker).findByRole('checkbox', { name: /FC A 0003-00012345/ }));
    await user.click(within(picker).getByRole('checkbox', { name: /FC A 0003-00012346/ }));
    await user.click(within(picker).getByRole('button', { name: 'Agregar a la línea' }));
    await user.type(within(linea(1)).getByLabelText('Monto de la línea 1'), '1000');
    await user.click(screen.getByRole('button', { name: '+ Agregar línea' }));
    await user.keyboard('{Escape}');
    await pickProducts(user, 2, 'router', ['Router TP-Link Archer AX55']);
    await user.type(within(linea(2)).getByLabelText('Monto de la línea 2'), '5');

    await user.click(crear());
    // The backend's line 2 is the second invoice of the screen's line 1.
    expect(await screen.findByRole('alert')).toHaveTextContent('Línea 1: la factura 9002 ya tiene un sell in con ese tactical.');
    expect(screen.queryByText(/Listado de sell in/)).not.toBeInTheDocument();
  });
});

describe('leaving', () => {
  it('asks before discarding and goes back to the Tacticals tab', async () => {
    const user = userEvent.setup();
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out');
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    const dialog = screen.getByRole('dialog', { name: '¿Descartar el tactical?' });
    await user.click(within(dialog).getByRole('button', { name: 'Seguir editando' }));
    expect(screen.queryByRole('dialog', { name: '¿Descartar el tactical?' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '¿Descartar el tactical?' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    await user.click(screen.getByRole('button', { name: 'Descartar' }));
    expect(await screen.findByText('Listado de sell in?tab=tacticals')).toBeInTheDocument();
  });

  it('keeps the focus inside the discard dialog and gives it back to Cancelar', async () => {
    const user = userEvent.setup();
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out');
    const cancelar = screen.getByRole('button', { name: 'Cancelar' });
    await user.click(cancelar);
    const dialog = screen.getByRole('dialog', { name: '¿Descartar el tactical?' });
    expect(within(dialog).getByRole('button', { name: 'Seguir editando' })).toHaveFocus();
    await user.tab();
    expect(within(dialog).getByRole('button', { name: 'Descartar' })).toHaveFocus();
    await user.tab();
    expect(within(dialog).getByRole('button', { name: 'Seguir editando' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(cancelar).toHaveFocus();
  });
});

describe('Renovar', () => {
  it("opens prefilled from the tactical's detail with new dates to pick, and creates a NEW tactical", async () => {
    const user = userEvent.setup();
    const original = { ...TACTICAL_BPS, fecha_desde: '2026-11-01', fecha_hasta: '2026-11-30' };
    api.get.mockImplementation((url) =>
      url === '/tacticals/1' ? Promise.resolve({ data: original }) : Promise.resolve({ data: {} }),
    );
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out&renovar=1');

    expect(await screen.findByDisplayValue('Tacticals BPS Noviembre Q1FY27')).toBeInTheDocument();
    expect(screen.getByLabelText('Desde')).toHaveValue('');
    expect(screen.getByLabelText('Hasta')).toHaveValue('');
    await user.type(screen.getByLabelText('Desde'), '2026-12-01');
    await user.type(screen.getByLabelText('Hasta'), '2026-12-31');
    await user.click(crear());

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    const [url, body] = api.post.mock.calls[0];
    expect(url).toBe('/tacticals');
    expect(body).toMatchObject({ tipo: 'sell_out', nombre: 'Tacticals BPS Noviembre Q1FY27', marca: 'HP' });
    expect((({ fecha_desde, fecha_hasta }) => ({ fecha_desde, fecha_hasta }))(body)).toEqual({
      fecha_desde: '2026-12-01',
      fecha_hasta: '2026-12-31',
    });
    expect(body.lineas).toEqual([
      { alcance: 'productos', item_ids: [101, 102], modo_monto: 'por_unidad', valor: 220, tope_unidades: 90, tope_monto: null, tope_por_producto: true },
      { alcance: 'productos', item_ids: [201, 202], modo_monto: 'por_unidad', valor: 12, tope_unidades: 300, tope_monto: 3000, tope_por_producto: false },
    ]);
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('shows no form until the tactical to renew arrives, so nothing typed is overwritten', async () => {
    let responder;
    api.get.mockImplementation((url) =>
      url === '/tacticals/1' ? new Promise((resolve) => (responder = resolve)) : Promise.resolve({ data: {} }),
    );
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out&renovar=1');

    expect(await screen.findByRole('status')).toHaveTextContent('Cargando el tactical a renovar…');
    expect(screen.queryByLabelText('Desde')).not.toBeInTheDocument();
    expect(crear()).toBeDisabled();
    responder({ data: TACTICAL_BPS });

    expect(await screen.findByDisplayValue('Tacticals BPS Noviembre Q1FY27')).toBeInTheDocument();
    expect(screen.queryByText('Cargando el tactical a renovar…')).not.toBeInTheDocument();
  });

  it('reads the tactical to renew once, even after the official stores arrive', async () => {
    api.get.mockImplementation((url) =>
      url === '/tacticals/1' ? Promise.resolve({ data: TACTICAL_BPS }) : Promise.resolve({ data: {} }),
    );
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out&renovar=1');

    expect(await screen.findByDisplayValue('Tacticals BPS Noviembre Q1FY27')).toBeInTheDocument();
    expect(api.get.mock.calls.filter(([url]) => url === '/tacticals/1')).toHaveLength(1);
  });

  it('says so when the tactical to renew cannot be read', async () => {
    api.get.mockImplementation((url) => (url === '/tacticals/1' ? Promise.reject(new Error('500')) : Promise.resolve({ data: {} })));
    renderAt('/sell-in/tactical/nuevo?tipo=sell_out&renovar=1');

    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo cargar el tactical a renovar.');
  });
});

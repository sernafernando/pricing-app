/**
 * The product master's ficha (abm-productos T8, S9-S13): GBP fields with overrides and "Volver al valor de GBP",
 * units per box through Gestión Full's permission, the texts and their sources, the Tienda Nube link, and the specs
 * of notebooks and PCs with "No aplica". One "Guardar" sends only what changed.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FichaProducto from './FichaProducto';
import {
  productoMaestroAPI,
  productoSpecsAPI,
  productoTnVinculosAPI,
  productoMarcasAPI,
  productoCategoriasAPI,
} from '../../services/api';

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  productoMaestroAPI: { leer: vi.fn(), guardar: vi.fn() },
  productoSpecsAPI: { leer: vi.fn(), guardar: vi.fn(), precargar: vi.fn(), valores: vi.fn(), campos: vi.fn() },
  productoTnVinculosAPI: { leer: vi.fn(), candidatos: vi.fn(), vincular: vi.fn() },
  productoMarcasAPI: { listar: vi.fn() },
  productoCategoriasAPI: { listar: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const campo = (valor, gbp = valor, extra = {}) => ({ valor, gbp, overrideado: valor !== gbp, ...extra });

const maestro = (over = {}) => ({
  item_id: 455,
  codigo: '4897098683446',
  tipo_specs: null,
  campos: {
    nombre: campo('Adaptador Bluetooth 5.0 TP-Link UB500 Nano USB', 'BLUETOOTH TPLINK NANO USB UB500 BT 5.0'),
    ean: campo('4897098683446'),
    codigo_fabricante: campo('UB500'),
    marca_id: campo(12, 12, { nombre: 'TP-LINK', gbp_nombre: 'TP-LINK' }),
    categoria_id: campo(61, 61, { nombre: 'CONECTIVIDAD', gbp_nombre: 'CONECTIVIDAD' }),
    subcategoria_id: campo(3855, 3855, { nombre: 'ANTENAS WIFI', gbp_nombre: 'ANTENAS WIFI' }),
    garantia_dias: campo(180),
    peso_g: campo(35),
    ancho_cm: campo(14),
    largo_cm: campo(9),
    alto_cm: campo(3),
  },
  unidades_caja: null,
  textos: {
    titulo_ml: {
      fuente: 'ml',
      elegida: false,
      valor: 'Adaptador Bluetooth Tp-link Ub500',
      fuentes: { ml: 'Adaptador Bluetooth Tp-link Ub500', tn: null, gbp: 'Adaptador Bluetooth Ub400' },
    },
    titulo_web: { fuente: 'ml', elegida: false, valor: 'Adaptador Bluetooth Tp-link Ub500', fuentes: { tn: null, ml: 'Adaptador Bluetooth Tp-link Ub500', nombre: 'Adaptador Bluetooth 5.0 TP-Link UB500 Nano USB' } },
    descripcion_ml: { fuente: 'ml', elegida: false, valor: 'Bluetooth 5.0', fuentes: { ml: 'Bluetooth 5.0', tn: null, gbp: 'Viejo texto' } },
    descripcion_web: { fuente: 'ml', elegida: false, valor: 'Bluetooth 5.0', fuentes: { tn: null, ml: 'Bluetooth 5.0', gbp: 'Viejo texto' } },
  },
  mla_ganadora: 'MLA1442876593',
  lectura: {
    costo: 4.6606,
    moneda_costo: 'USD',
    iva: 10.5,
    stock: 964,
    precio_lista_ml: 11999,
    proveedor: 'PC-ARTS ARGENTINA S.A.',
    publicaciones_ml: 3,
    tn_producto_id: null,
    tn_publicado: null,
  },
  can_edit: true,
  can_edit_unidades: true,
  ...over,
});

const specs = (over = {}) => ({
  item_id: 4874,
  tipo: 'notebook',
  campos: [
    { campo: 'cpu_marca', grupo: 'Procesador', etiqueta: 'Marca', valor: 'AMD', origen: 'erp_name' },
    { campo: 'ram_gb', grupo: 'Memoria', etiqueta: 'Capacidad', valor: 8, origen: 'ml' },
    { campo: 'gpu_modelo', grupo: 'Placa de video', etiqueta: 'Modelo', valor: null, origen: null },
  ],
  completos: 2,
  total: 3,
  can_edit: true,
  ...over,
});

const vinculo = (over = {}) => ({ item_id: 455, origen: null, tn: null, can_edit: true, ...over });

beforeEach(() => {
  vi.clearAllMocks();
  productoMaestroAPI.leer.mockResolvedValue({ data: maestro() });
  productoMaestroAPI.guardar.mockImplementation(() => Promise.resolve({ data: maestro() }));
  productoTnVinculosAPI.leer.mockResolvedValue({ data: vinculo() });
  productoTnVinculosAPI.candidatos.mockResolvedValue({ data: [] });
  productoMarcasAPI.listar.mockResolvedValue({ data: [{ id: 12, nombre: 'TP-LINK', activa: true }, { id: 7, nombre: 'ASUS', activa: true }] });
  productoCategoriasAPI.listar.mockResolvedValue({
    data: [
      { id: 61, nombre: 'CONECTIVIDAD', activa: true, subcategorias: [{ id: 3855, nombre: 'ANTENAS WIFI', activa: true }] },
      { id: 46, nombre: 'NOTEBOOK', activa: true, subcategorias: [{ id: 3901, nombre: 'NOTEBOOKS', activa: true }] },
    ],
  });
  productoSpecsAPI.valores.mockResolvedValue({ data: [] });
  productoSpecsAPI.campos.mockResolvedValue({
    data: [
      { nombre: 'cpu_marca', tipo: 'categorico', unidad: null },
      { nombre: 'ram_gb', tipo: 'numerico', unidad: 'GB' },
      { nombre: 'gpu_modelo', tipo: 'categorico', unidad: null },
    ],
  });
});

const field = (label) => screen.getByLabelText(label, { selector: 'input,select,textarea' });

describe('Ficha: general fields over GBP', () => {
  it('shows an override with its GBP value and saves only what changed', async () => {
    const user = userEvent.setup();
    render(<FichaProducto itemId={455} />);

    expect(await screen.findByRole('heading', { name: 'Adaptador Bluetooth 5.0 TP-Link UB500 Nano USB' })).toBeInTheDocument();
    expect(screen.getByText('GBP: BLUETOOTH TPLINK NANO USB UB500 BT 5.0')).toBeInTheDocument();
    expect(screen.getByText('item 455 · CONECTIVIDAD / ANTENAS WIFI · TP-LINK · 3 MLA')).toBeInTheDocument();

    const guardar = screen.getByRole('button', { name: 'Guardar' });
    expect(guardar).toBeDisabled();

    await user.clear(field('Peso'));
    await user.type(field('Peso'), '40');
    expect(screen.getByRole('button', { name: 'Guardar 1 cambio' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Guardar 1 cambio' }));

    expect(productoMaestroAPI.guardar).toHaveBeenCalledWith(455, { peso_g: '40' });
    expect(productoSpecsAPI.guardar).not.toHaveBeenCalled();
  });

  it('"Volver al valor de GBP" drops the override at once', async () => {
    const user = userEvent.setup();
    render(<FichaProducto itemId={455} />);

    await user.click(await screen.findByRole('button', { name: 'Volver al valor de GBP' }));

    expect(productoMaestroAPI.guardar).toHaveBeenCalledWith(455, { nombre: null });
  });

  it('a cleared field goes back to GBP (null)', async () => {
    const user = userEvent.setup();
    render(<FichaProducto itemId={455} />);

    await user.clear(await screen.findByLabelText('Nombre'));
    await user.click(screen.getByRole('button', { name: 'Guardar 1 cambio' }));

    expect(productoMaestroAPI.guardar).toHaveBeenCalledWith(455, { nombre: null });
  });

  it('picks the brand from the brands master and sends its id', async () => {
    const user = userEvent.setup();
    render(<FichaProducto itemId={455} />);

    await screen.findByRole('option', { name: 'ASUS' });
    await user.selectOptions(field('Marca'), 'ASUS');
    await user.click(screen.getByRole('button', { name: 'Guardar 1 cambio' }));

    expect(productoMaestroAPI.guardar).toHaveBeenCalledWith(455, { marca_id: 7 });
  });

  it('a category without active subcategories cannot be saved', async () => {
    const user = userEvent.setup();
    productoCategoriasAPI.listar.mockResolvedValue({
      data: [
        { id: 61, nombre: 'CONECTIVIDAD', activa: true, subcategorias: [{ id: 3855, nombre: 'ANTENAS WIFI', activa: true }] },
        { id: 80, nombre: 'VARIOS', activa: true, subcategorias: [{ id: 4001, nombre: 'OTROS', activa: false }] },
      ],
    });
    render(<FichaProducto itemId={455} />);

    await screen.findByRole('option', { name: 'VARIOS' });
    await user.selectOptions(field('Categoría'), 'VARIOS');

    expect(screen.getByText('VARIOS no tiene subcategorías activas: elegí otra categoría')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Guardar/ })).toBeDisabled();
  });

  it('integer fields open the numeric keyboard, decimal ones the decimal one', async () => {
    render(<FichaProducto itemId={455} />);
    await screen.findByDisplayValue('180');
    expect(field('Garantía')).toHaveAttribute('inputmode', 'numeric');
    expect(field('Peso')).toHaveAttribute('inputmode', 'decimal');
  });

  it('units per box need Depósitos: read-only without it, sent as a number with it', async () => {
    productoMaestroAPI.leer.mockResolvedValueOnce({ data: maestro({ unidades_caja: 20, can_edit_unidades: false }) });
    const { unmount } = render(<FichaProducto itemId={455} />);
    expect(await screen.findByLabelText('Unidades por caja')).toBeDisabled();
    expect(screen.getByText('Mismo dato que Gestión Full · editar requiere Depósitos')).toBeInTheDocument();
    expect(screen.getByText('Gestión Full')).toBeInTheDocument();
    unmount();

    const user = userEvent.setup();
    render(<FichaProducto itemId={455} />);
    await user.type(await screen.findByLabelText('Unidades por caja'), '12');
    await user.click(screen.getByRole('button', { name: 'Guardar 1 cambio' }));

    expect(productoMaestroAPI.guardar).toHaveBeenCalledWith(455, { unidades_caja: 12 });
  });

  it('a general field the server does not send shows as without data', async () => {
    const { alto_cm: _omitido, ...campos } = maestro().campos;
    productoMaestroAPI.leer.mockResolvedValue({ data: maestro({ campos }) });
    render(<FichaProducto itemId={455} />);
    expect(await screen.findByDisplayValue('180')).toBeInTheDocument();
    expect(field('Alto')).toHaveValue('');
  });

  it('without edit permission every field is read-only', async () => {
    productoMaestroAPI.leer.mockResolvedValueOnce({ data: maestro({ can_edit: false, can_edit_unidades: false }) });
    render(<FichaProducto itemId={455} />);

    expect(await screen.findByLabelText('Nombre')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Volver al valor de GBP' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Título ML')).toBeDisabled();
  });

  it('shows the server reason when the save is refused', async () => {
    productoMaestroAPI.guardar.mockRejectedValueOnce(
      Object.assign(new Error('HTTP 422'), {
        response: { status: 422, data: { error: { code: 'error', message: 'La subcategoría no es de esa categoría' } } },
      }),
    );
    const user = userEvent.setup();
    render(<FichaProducto itemId={455} />);

    await user.type(await screen.findByLabelText('Garantía'), '0');
    await user.click(screen.getByRole('button', { name: 'Guardar 1 cambio' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('La subcategoría no es de esa categoría');
  });
});

describe('Ficha: titles and descriptions', () => {
  it('"Tomar de" picks a source; typing makes it an own text', async () => {
    const user = userEvent.setup();
    render(<FichaProducto itemId={455} />);

    const titulo = await screen.findByLabelText('Título ML');
    const bloque = titulo.closest('[data-texto]');
    expect(within(bloque).getByRole('button', { name: 'Publicación MLA1442876593' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(bloque).getByText('Sigue a la publicación mientras no se edite')).toBeInTheDocument();

    await user.click(within(bloque).getByRole('button', { name: 'GBP' }));
    expect(titulo).toHaveValue('Adaptador Bluetooth Ub400');
    expect(within(bloque).getByText('Texto de GBP: se actualiza con la sincronización de GBP')).toBeInTheDocument();

    const desc = screen.getByLabelText('Descripción web');
    await user.clear(desc);
    await user.type(desc, 'Texto nuevo');
    expect(within(desc.closest('[data-texto]')).getByRole('button', { name: 'Texto propio' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(screen.getByRole('button', { name: 'Guardar 2 cambios' }));
    expect(productoMaestroAPI.guardar).toHaveBeenCalledWith(455, {
      textos: { titulo_ml: { fuente: 'gbp' }, descripcion_web: { fuente: 'propio', texto: 'Texto nuevo' } },
    });
  });

  it('a source without text is not offered', async () => {
    render(<FichaProducto itemId={455} />);
    const bloque = (await screen.findByLabelText('Título ML')).closest('[data-texto]');
    expect(within(bloque).queryByRole('button', { name: 'Tienda Nube' })).not.toBeInTheDocument();
  });
});

describe('Ficha: Tienda Nube as a description source', () => {
  const chips = (bloque) =>
    within(bloque)
      .getAllByRole('button')
      .map((b) => b.textContent);

  it('both descriptions always offer Tienda Nube, in the mock order, even without its text', async () => {
    const user = userEvent.setup();
    render(<FichaProducto itemId={455} />);

    const ml = (await screen.findByLabelText('Descripción ML')).closest('[data-texto]');
    const web = screen.getByLabelText('Descripción web').closest('[data-texto]');
    expect(chips(ml)).toEqual(['Publicación MLA1442876593', 'Tienda Nube', 'GBP', 'Texto propio']);
    expect(chips(web)).toEqual(['Tienda Nube', 'Publicación MLA1442876593', 'GBP', 'Texto propio']);

    await user.click(within(web).getByRole('button', { name: 'Tienda Nube' }));
    expect(screen.getByLabelText('Descripción web')).toHaveValue('');
    expect(screen.getByLabelText('Descripción web')).toHaveAttribute(
      'placeholder',
      'Sin descripción en Tienda Nube: llega con la sincronización de TN',
    );
  });

  it('with its text, Tienda Nube gives the plain text for ML and the HTML for the web', async () => {
    const base = maestro();
    productoMaestroAPI.leer.mockResolvedValue({
      data: maestro({
        textos: {
          ...base.textos,
          descripcion_ml: { ...base.textos.descripcion_ml, fuentes: { ...base.textos.descripcion_ml.fuentes, tn: 'Bluetooth 5.0 nano' } },
          descripcion_web: { ...base.textos.descripcion_web, fuentes: { ...base.textos.descripcion_web.fuentes, tn: '<p>Bluetooth 5.0 nano</p>' } },
        },
      }),
    });
    const user = userEvent.setup();
    render(<FichaProducto itemId={455} />);

    const ml = (await screen.findByLabelText('Descripción ML')).closest('[data-texto]');
    const web = screen.getByLabelText('Descripción web').closest('[data-texto]');
    expect(chips(ml)).toEqual(['Publicación MLA1442876593', 'Tienda Nube', 'GBP', 'Texto propio']);
    expect(chips(web)).toEqual(['Tienda Nube', 'Publicación MLA1442876593', 'GBP', 'Texto propio']);

    await user.click(within(ml).getByRole('button', { name: 'Tienda Nube' }));
    await user.click(within(web).getByRole('button', { name: 'Tienda Nube' }));
    expect(screen.getByLabelText('Descripción ML')).toHaveValue('Bluetooth 5.0 nano');
    expect(screen.getByLabelText('Descripción web')).toHaveValue('<p>Bluetooth 5.0 nano</p>');
  });
});

describe('Ficha: read-only data', () => {
  it('shows cost, VAT, stock, list price, supplier, publications and Tienda Nube', async () => {
    render(<FichaProducto itemId={455} />);
    const lectura = await screen.findByRole('group', { name: /Precio, stock y canales/ });
    expect(within(lectura).getByText('USD 4,66')).toBeInTheDocument();
    expect(within(lectura).getByText('10,5 %')).toBeInTheDocument();
    expect(within(lectura).getByText('964')).toBeInTheDocument();
    expect(within(lectura).getByText('$ 11.999')).toBeInTheDocument();
    expect(within(lectura).getByText('3 vinculadas')).toBeInTheDocument();
    expect(within(lectura).getByText('No publicado')).toBeInTheDocument();
  });
});

describe('Ficha: Tienda Nube link', () => {
  const TN = { tn_product_id: 338251994, nombre: 'Adaptador Bluetooth TP-Link UB500', skus: ['4897098683446'], precio: 15999, published: true, item_id: 455 };

  it('shows the automatic link and unlinks it by hand', async () => {
    productoTnVinculosAPI.leer.mockResolvedValue({ data: vinculo({ origen: 'sku', tn: TN }) });
    productoTnVinculosAPI.vincular.mockResolvedValue({ data: vinculo({ origen: 'manual', tn: null }) });
    const user = userEvent.setup();
    render(<FichaProducto itemId={455} />);

    expect(await screen.findByText('Adaptador Bluetooth TP-Link UB500')).toBeInTheDocument();
    expect(screen.getByText('producto 338251994 · SKU 4897098683446 · $ 15.999 · publicado')).toBeInTheDocument();
    expect(screen.getByText('Automático por SKU')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Desvincular' }));
    expect(productoTnVinculosAPI.vincular).toHaveBeenCalledWith(455, null);
    expect(await screen.findByText('Sin producto de Tienda Nube vinculado')).toBeInTheDocument();
  });

  it('the read-only Tienda Nube status follows the product linked on screen', async () => {
    productoTnVinculosAPI.leer.mockResolvedValue({ data: vinculo({ origen: 'sku', tn: TN }) });
    productoTnVinculosAPI.vincular.mockResolvedValue({ data: vinculo({ origen: 'manual', tn: { ...TN, published: false } }) });
    productoTnVinculosAPI.candidatos.mockResolvedValue({ data: [{ ...TN, published: false, item_id: null, motivo: 'ean' }] });
    const user = userEvent.setup();
    render(<FichaProducto itemId={455} />);
    const lectura = await screen.findByRole('group', { name: /Precio, stock y canales/ });
    expect(await within(lectura).findByText('Publicado')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Cambiar' }));
    await user.click(await screen.findByRole('button', { name: 'Vincular' }));

    expect(await within(lectura).findByText('No publicado')).toBeInTheDocument();
  });

  it('suggests candidates, searches and links one', async () => {
    productoTnVinculosAPI.candidatos.mockImplementation((id, q) =>
      Promise.resolve({ data: q ? [{ ...TN, item_id: null, motivo: 'busqueda' }] : [{ ...TN, item_id: null, motivo: 'ean' }] }),
    );
    productoTnVinculosAPI.vincular.mockResolvedValue({ data: vinculo({ origen: 'manual', tn: TN }) });
    const user = userEvent.setup();
    render(<FichaProducto itemId={455} />);

    await user.click(await screen.findByRole('button', { name: 'Vincular' }));
    expect(await screen.findByText('Sugeridos por EAN o nombre')).toBeInTheDocument();
    expect(screen.getByText('Mismo EAN')).toBeInTheDocument();
    expect(screen.getByText('producto 338251994 · SKU 4897098683446 · sin vincular')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Buscar producto de Tienda Nube'), 'ub500');
    await waitFor(() => expect(productoTnVinculosAPI.candidatos).toHaveBeenLastCalledWith(455, 'ub500'));
    expect(await screen.findByText('Resultados')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Vincular' }));
    expect(productoTnVinculosAPI.vincular).toHaveBeenCalledWith(455, 338251994);
    expect(await screen.findByText('Manual')).toBeInTheDocument();
  });
});

describe('Ficha: specs of notebooks and PCs', () => {
  beforeEach(() => {
    productoMaestroAPI.leer.mockResolvedValue({ data: maestro({ item_id: 4874, tipo_specs: 'notebook' }) });
    productoSpecsAPI.leer.mockResolvedValue({ data: specs() });
    productoSpecsAPI.guardar.mockResolvedValue({ data: specs() });
  });

  it('the specs tab is off for a product that is not a notebook or a PC', async () => {
    productoMaestroAPI.leer.mockResolvedValue({ data: maestro() });
    render(<FichaProducto itemId={455} />);
    expect(await screen.findByRole('tab', { name: /Specs técnicas/ })).toBeDisabled();
    expect(productoSpecsAPI.leer).not.toHaveBeenCalled();
  });

  it('the tabs control their panel and move with the arrow keys', async () => {
    const user = userEvent.setup();
    render(<FichaProducto itemId={4874} />);

    const general = await screen.findByRole('tab', { name: 'General' });
    const specsTab = await screen.findByRole('tab', { name: /Specs técnicas/ });
    await waitFor(() => expect(specsTab).toBeEnabled());
    expect(screen.getByRole('tabpanel', { name: 'General' })).toHaveAttribute('id', general.getAttribute('aria-controls'));

    general.focus();
    await user.keyboard('{ArrowRight}');

    expect(specsTab).toHaveFocus();
    expect(specsTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel', { name: /Specs técnicas/ })).toBeInTheDocument();
  });

  it('shows each origin, edits by hand and marks "No aplica", saved in one PUT', async () => {
    const user = userEvent.setup();
    render(<FichaProducto itemId={4874} />);

    await user.click(await screen.findByRole('tab', { name: 'Specs técnicas 2 / 3' }));
    expect(screen.getByRole('group', { name: 'Procesador 1 / 1' })).toBeInTheDocument();

    const cpu = screen.getByLabelText('Procesador Marca');
    expect(within(cpu.closest('[data-spec]')).getByText('ERP')).toBeInTheDocument();
    await user.clear(cpu);
    await user.type(cpu, 'Intel');
    expect(within(cpu.closest('[data-spec]')).getByText('Manual · sin guardar')).toBeInTheDocument();

    const gpu = screen.getByLabelText('Placa de video Modelo');
    await user.click(within(gpu.closest('[data-spec]')).getByRole('checkbox', { name: 'No aplica' }));
    expect(gpu).toBeDisabled();
    expect(gpu).toHaveAttribute('placeholder', 'No aplica');

    await user.click(screen.getByRole('button', { name: 'Guardar 2 cambios' }));
    expect(productoSpecsAPI.guardar).toHaveBeenCalledWith(4874, { valores: { cpu_marca: 'Intel' }, no_aplica: { gpu_modelo: true } });
    expect(productoMaestroAPI.guardar).not.toHaveBeenCalled();
  });

  it('"Precargar de nuevo" re-pre-loads the product', async () => {
    productoSpecsAPI.precargar.mockResolvedValue({ data: specs({ completos: 3 }) });
    const user = userEvent.setup();
    render(<FichaProducto itemId={4874} />);

    await user.click(await screen.findByRole('tab', { name: /Specs técnicas/ }));
    await user.click(screen.getByRole('button', { name: 'Precargar de nuevo' }));

    expect(productoSpecsAPI.precargar).toHaveBeenCalledWith(4874);
    expect(await screen.findByRole('tab', { name: 'Specs técnicas 3 / 3' })).toBeInTheDocument();
  });
});

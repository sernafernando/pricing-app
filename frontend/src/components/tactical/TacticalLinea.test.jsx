/**
 * TacticalLinea — one line of the Nuevo tactical grid, driven through a holder that keeps its state like the page.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useState } from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TacticalLinea from './TacticalLinea';
import { nuevaLinea } from './tacticalLineas';
import api, { productosAPI } from '../../services/api';
import { CATALOGO, OPERACIONES } from './tacticalFixtures';

const onDuplicar = vi.fn();
const onEliminar = vi.fn();

function Holder({ tipo, moneda = 'USD', tcModo = 'al_cobro', inicial = {} }) {
  const [linea, setLinea] = useState(() => ({ ...nuevaLinea(), ...inicial }));
  const [abierto, setAbierto] = useState(false);
  return (
    <TacticalLinea
      linea={linea}
      n={1}
      tipo={tipo}
      moneda={moneda}
      tcModo={tcModo}
      marcas={['HP', 'TP-Link']}
      categorias={['Monitores', 'Redes']}
      abierto={abierto}
      onAbrir={() => setAbierto(true)}
      onCerrar={() => setAbierto(false)}
      onCambiar={setLinea}
      onDuplicar={onDuplicar}
      onEliminar={onEliminar}
    />
  );
}

const fila = () => screen.getByRole('group', { name: 'Línea 1' });
const monitores = CATALOGO.filter((p) => [201, 202, 203].includes(p.item_id));

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((url, config) =>
    Promise.resolve({ data: CATALOGO.filter((p) => p.descripcion.toLowerCase().includes(config.params.q.toLowerCase())) }),
  );
  productosAPI.categorias.mockResolvedValue({ data: { categorias: ['Routers', 'Switches'] } });
});

describe('TacticalLinea', () => {
  it('sell out offers products, brand and category, per unit, % or a total amount', () => {
    render(<Holder tipo="sell_out" />);
    const alcance = within(fila()).getByRole('group', { name: 'Alcance de la línea 1' });
    expect(within(alcance).getAllByRole('button').map((b) => b.textContent)).toEqual(['Productos', 'Marca', 'Categoría']);
    const modo = within(fila()).getByRole('group', { name: 'Unidad del monto, línea 1' });
    expect(within(modo).getAllByRole('button').map((b) => b.textContent)).toEqual(['por unidad', '%', 'monto total']);
    expect(within(modo).getByRole('button', { name: 'monto total' })).toBeEnabled();
    expect(within(fila()).queryByLabelText('Reparto del monto total, línea 1')).not.toBeInTheDocument();
  });

  it('a sell out total amount asks how to split it among the products and drops the caps', async () => {
    const user = userEvent.setup();
    render(<Holder tipo="sell_out" inicial={{ productos: monitores, topeUnidades: '300', topeMonto: '5000' }} />);
    await user.click(within(fila()).getByRole('button', { name: 'monto total' }));
    const reparto = within(fila()).getByLabelText('Reparto del monto total, línea 1');
    expect(within(reparto).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Elegí cómo repartir',
      'Partes iguales por modelo',
      'Según unidades vendidas',
      'Proporcional al costo',
    ]);
    expect(reparto).toHaveValue('');
    expect(within(fila()).queryByLabelText('Tope de unidades, línea 1')).not.toBeInTheDocument();
    expect(within(fila()).queryByLabelText('Tope de monto en USD, línea 1')).not.toBeInTheDocument();
    expect(within(fila()).queryByRole('button', { name: 'Por producto' })).not.toBeInTheDocument();
    await user.selectOptions(reparto, 'unidades');
    expect(reparto).toHaveValue('unidades');
    expect(within(fila()).getByText(/sigue las ventas y devoluciones/i)).toBeInTheDocument();
    await user.type(within(fila()).getByLabelText('Monto de la línea 1'), '1.200');
    expect(within(fila()).getByText('USD 1.200')).toBeInTheDocument();
    // Back to per unit: the caps come back empty, not the ones typed before.
    await user.click(within(fila()).getByRole('button', { name: 'por unidad' }));
    expect(within(fila()).getByLabelText('Tope de unidades, línea 1')).toHaveValue('');
    expect(within(fila()).queryByLabelText('Reparto del monto total, línea 1')).not.toBeInTheDocument();
  });

  it('sell in adds Factura, whose amount is a total with no split to choose, as before', async () => {
    const user = userEvent.setup();
    render(<Holder tipo="sell_in" moneda="ARS" />);
    await user.click(within(fila()).getByRole('button', { name: 'Factura' }));
    expect(within(fila()).getByRole('button', { name: 'monto total' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(fila()).getByRole('button', { name: '+ Factura' })).toBeInTheDocument();
    expect(within(fila()).queryByRole('button', { name: 'Por producto' })).not.toBeInTheDocument();
    expect(within(fila()).queryByLabelText('Reparto del monto total, línea 1')).not.toBeInTheDocument();
  });

  it('an operation without its supplier invoice can be picked and says it waits for it (sell in factura pendiente S4)', async () => {
    api.get.mockResolvedValue({
      data: {
        items: [
          { id: 9, numero: 'OC-9', proveedor_nombre: 'TP-Link', fecha: '2026-11-10', moneda: 'ARS', monto: '100',
            numero_factura: null, fecha_factura: null },
          { id: 8, numero: 'OC-8', proveedor_nombre: 'TP-Link', fecha: '2026-11-01', moneda: 'ARS', monto: '100',
            numero_factura: 'A-1', fecha_factura: '2026-11-05' },
        ],
      },
    });
    const user = userEvent.setup();
    render(<Holder tipo="sell_in" moneda="ARS" />);
    await user.click(within(fila()).getByRole('button', { name: 'Factura' }));
    await user.click(within(fila()).getByRole('button', { name: '+ Factura' }));
    const picker = screen.getByRole('dialog', { name: 'Agregar facturas a la línea' });
    const pendiente = await within(picker).findByRole('checkbox', { name: /OC-9/ });
    expect(pendiente).toBeEnabled();
    expect(within(picker).getByText(/Operación OC-9 · Esperando factura/)).toBeInTheDocument();
    expect(within(picker).queryByText(/Operación OC-8 · Esperando factura/)).not.toBeInTheDocument();
  });

  it.each(['productos', 'marca', 'categoria'])('a sell in total amount over %s asks how to split it and drops the caps (S4)', async (alcance) => {
    const user = userEvent.setup();
    render(<Holder tipo="sell_in" moneda="ARS" inicial={{ alcance, productos: monitores, topeUnidades: '300' }} />);
    await user.click(within(fila()).getByRole('button', { name: 'monto total' }));
    const reparto = within(fila()).getByLabelText('Reparto del monto total, línea 1');
    expect(within(reparto).getAllByRole('option').map((o) => o.value)).toEqual(['', 'iguales', 'unidades', 'costo']);
    await user.selectOptions(reparto, 'costo');
    expect(reparto).toHaveValue('costo');
    expect(within(fila()).queryByLabelText('Tope de unidades, línea 1')).not.toBeInTheDocument();
    expect(within(fila()).queryByLabelText('Tope de monto en ARS, línea 1')).not.toBeInTheDocument();
  });

  it('a sell in total amount in USD needs a fixed exchange rate, and says so (S4)', () => {
    const { unmount } = render(<Holder tipo="sell_in" moneda="USD" tcModo="al_cobro" />);
    const total = within(fila()).getByRole('button', { name: 'monto total' });
    expect(total).toBeDisabled();
    expect(total).toHaveAttribute('title', 'Un monto total en USD necesita tipo de cambio fijo.');
    unmount();
    render(<Holder tipo="sell_in" moneda="USD" tcModo="fijo" />);
    expect(within(fila()).getByRole('button', { name: 'monto total' })).toBeEnabled();
    expect(within(fila()).getByRole('button', { name: 'monto total' })).not.toHaveAttribute('title');
  });

  it('a brand line picks its brand and says what it covers', async () => {
    const user = userEvent.setup();
    render(<Holder tipo="sell_out" />);
    await user.click(within(fila()).getByRole('button', { name: 'Marca' }));
    await user.selectOptions(within(fila()).getByLabelText('Marca de la línea'), 'TP-Link');
    expect(within(fila()).getByLabelText('Marca de la línea')).toHaveValue('TP-Link');
    expect(within(fila()).getByText('Aplica a todos los productos de la marca.')).toBeInTheDocument();
  });

  it('a brand line may narrow to one of its brand\'s categories (SISO S3)', async () => {
    const user = userEvent.setup();
    render(<Holder tipo="sell_out" />);
    await user.click(within(fila()).getByRole('button', { name: 'Marca' }));
    await user.selectOptions(within(fila()).getByLabelText('Marca de la línea'), 'TP-Link');
    const categoria = within(fila()).getByLabelText('Categoría de la marca, línea 1');
    expect(productosAPI.categorias).toHaveBeenCalledWith({ marca: 'TP-Link' });
    expect(await within(categoria).findByRole('option', { name: 'Routers' })).toBeInTheDocument();
    expect(within(categoria).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Todas las categorías',
      'Routers',
      'Switches',
    ]);

    await user.selectOptions(categoria, 'Routers');

    expect(categoria).toHaveValue('Routers');
    expect(within(fila()).getByText('Aplica a los productos de la marca en esa categoría.')).toBeInTheDocument();
    await user.selectOptions(within(fila()).getByLabelText('Marca de la línea'), 'HP');
    expect(within(fila()).getByLabelText('Categoría de la marca, línea 1')).toHaveValue('');
  });

  it('adds products as chips, removes one, and its button toggles the picker', async () => {
    const user = userEvent.setup();
    render(<Holder tipo="sell_out" />);
    const boton = within(fila()).getByRole('button', { name: '+ Producto' });
    await user.click(boton);
    await user.click(boton);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await user.click(boton);
    const picker = screen.getByRole('dialog', { name: 'Agregar productos a la línea' });
    await user.type(within(picker).getByLabelText('Buscar productos'), 'monitor');
    await user.click(await within(picker).findByRole('checkbox', { name: /V24i/ }));
    await user.click(within(picker).getByRole('checkbox', { name: /V27i/ }));
    await user.click(within(picker).getByRole('button', { name: 'Agregar a la línea' }));
    await user.click(within(fila()).getByRole('button', { name: 'Quitar Monitor HP V24i G5' }));
    expect(within(fila()).getAllByRole('button', { name: /^Quitar/ }).map((b) => b.getAttribute('aria-label'))).toEqual([
      'Quitar Monitor HP V27i G5',
    ]);
  });

  it('shows what it can charge at most, per product or shared', async () => {
    const user = userEvent.setup();
    render(<Holder tipo="sell_out" inicial={{ productos: monitores }} />);
    await user.type(within(fila()).getByLabelText('Monto de la línea 1'), '12');
    await user.type(within(fila()).getByLabelText('Tope de unidades, línea 1'), '300');
    expect(within(fila()).getByText('USD 10.800')).toBeInTheDocument();
    await user.click(within(fila()).getByRole('button', { name: 'Por producto' }));
    await user.type(within(fila()).getByLabelText('Tope de monto en USD, línea 1'), '3.000');
    expect(within(fila()).getByRole('button', { name: 'Compartido' })).toBeInTheDocument();
    expect(within(fila()).getByText('USD 3.000')).toBeInTheDocument();
  });

  it('one product cannot share its cap', () => {
    render(<Holder tipo="sell_out" inicial={{ productos: monitores.slice(0, 1) }} />);
    expect(within(fila()).getByRole('button', { name: 'Por producto' })).toBeDisabled();
  });

  it('an operation with several invoices applies to all of them, or to the ones picked (varias facturas S3)', async () => {
    const user = userEvent.setup();
    const inicial = { alcance: 'factura', modo: 'monto_total', facturas: [OPERACIONES[0]] };
    render(<Holder tipo="sell_in" moneda="ARS" inicial={inicial} />);
    const grupo = within(fila()).getByRole('group', { name: 'Facturas de FC A 0003-00012345, línea 1' });
    const todas = within(grupo).getByRole('checkbox', { name: 'Todas las facturas' });
    const segunda = within(grupo).getByRole('checkbox', { name: 'FC A 0003-00012360' });
    expect(todas).toBeChecked();
    expect(segunda).not.toBeChecked();

    await user.click(segunda);
    expect(todas).not.toBeChecked();
    expect(segunda).toBeChecked();
    await user.click(segunda);
    expect(todas).toBeChecked();
  });

  it('an operation with one invoice or none applies to all of them, with nothing to pick', () => {
    const inicial = { alcance: 'factura', modo: 'monto_total', facturas: [OPERACIONES[1], OPERACIONES[3]] };
    render(<Holder tipo="sell_in" moneda="ARS" inicial={inicial} />);
    expect(within(fila()).queryByRole('checkbox')).not.toBeInTheDocument();
    expect(within(fila()).getByText('Todas las facturas · FC A 0003-00012346')).toBeInTheDocument();
    expect(within(fila()).getByText('Todas las facturas')).toBeInTheDocument();
  });

  it('copies and deletes', async () => {
    const user = userEvent.setup();
    render(<Holder tipo="sell_out" />);
    await user.click(within(fila()).getByRole('button', { name: 'Duplicar línea 1' }));
    await user.click(within(fila()).getByRole('button', { name: 'Eliminar línea 1' }));
    expect(onDuplicar).toHaveBeenCalledTimes(1);
    expect(onEliminar).toHaveBeenCalledTimes(1);
  });
});

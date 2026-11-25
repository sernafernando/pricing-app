/**
 * Sell in incident 2026-11-24, S1: a % cost bonus's generated amount is in the currency of the costo SI steps it got,
 * never converted to the bonus's stored currency (a % has no currency). Bono 98, TPLINK LOYALTY: stored ARS, its 173
 * steps are USD, so the panel reads "USD 11.648,08", not "$ 18.183.306,16" (L35: USD costs shown in USD).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { productosAPI } from '../../services/api';
import { sellInBonosAPI } from '../../services/sellInAPI';
import { ALCANCE_VACIO, BONO } from './sellInFixtures';
import SellInBonoPanel from './SellInBonoPanel';

vi.mock('../../services/sellInAPI', () => ({
  sellInBonosAPI: { detalle: vi.fn(), alcance: vi.fn(), crear: vi.fn(), editar: vi.fn(), anular: vi.fn() },
  sellInAPI: { operaciones: vi.fn(), operacionProductos: vi.fn() },
}));

vi.mock('../../services/api', () => ({
  productosAPI: { categorias: vi.fn(), listar: vi.fn() },
}));

// Bono 98 as GET /api/sell-in/bonos/98 answers it once the steps' currency is kept: stored ARS, generated USD.
const BONO_98 = {
  ...BONO,
  id: 98,
  alcance: 'marca',
  marca: 'TP-LINK',
  tipo: 'porcentaje',
  monto_unit: null,
  porcentaje: '3.6000',
  moneda: 'ARS',
  fecha_desde: '2026-10-01',
  fecha_hasta: '2026-12-31',
  descripcion: 'TPLINK LOYALTY',
  tactical_id: 62,
  compras_activas: 0,
  unidades: 11954,
  monto_generado: '11648.08',
  moneda_generado: 'USD',
  montos_generados: [{ moneda: 'USD', monto: '11648.08' }],
  base: 'costo_venta',
  incluye_iva: false,
  offset_origen_id: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE_VACIO });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: [] } });
  productosAPI.listar.mockResolvedValue({ data: { productos: [], total: 0, page: 1, page_size: 10 } });
});

const renderPanel = () =>
  render(<SellInBonoPanel bonoId={98} marcas={['TP-LINK']} puedeGestionar onSaved={vi.fn()} onClose={vi.fn()} onVerCompra={vi.fn()} />);

describe('SellInBonoPanel — a % cost bonus in its steps currency', () => {
  it('shows TP loyalty as USD 11.648,08 taken off costo SI, not as another currency', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({ data: BONO_98 });
    renderPanel();

    expect(await screen.findByText('11.954 u en facturas · USD 11.648,08 descontados del costo SI')).toBeInTheDocument();
    expect(screen.queryByText(/en otra moneda/)).not.toBeInTheDocument();
  });

  it('shows one amount per currency when its steps were USD and ARS', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({
      data: {
        ...BONO_98,
        unidades: 130,
        monto_generado: '9668.48',
        moneda_generado: 'ARS',
        montos_generados: [
          { moneda: 'ARS', monto: '9668.48' },
          { moneda: 'USD', monto: '38.43' },
        ],
      },
    });
    renderPanel();

    expect(await screen.findByText('130 u en facturas · $ 9.668,48 y USD 38,43 descontados del costo SI')).toBeInTheDocument();
    expect(screen.queryByText(/en otra moneda/)).not.toBeInTheDocument();
  });
});

describe('SellInBonoPanel — a purchase in its invoice currency', () => {
  it('shows a USD 2.5 % bonus whose purchase is ARS on its ARS invoice as ARS, not as another currency', async () => {
    // Compras 25/26 after S3 (USD bonos 84/85, base factura): the purchase is in its invoice's currency, ARS.
    sellInBonosAPI.detalle.mockResolvedValue({
      data: {
        ...BONO,
        id: 84,
        tipo: 'porcentaje',
        monto_unit: null,
        porcentaje: '2.5000',
        moneda: 'USD',
        descripcion: 'DESC AIR TP',
        compras_activas: 1,
        unidades: 1000,
        monto_generado: '393467.14',
        moneda_generado: 'ARS',
        montos_generados: [{ moneda: 'ARS', monto: '393467.14' }],
      },
    });
    render(<SellInBonoPanel bonoId={84} marcas={['TP-LINK']} puedeGestionar onSaved={vi.fn()} onClose={vi.fn()} onVerCompra={vi.fn()} />);

    expect(await screen.findByText('1 compras · 1.000 u · $ 393.467,14 aplicados')).toBeInTheDocument();
    expect(screen.queryByText(/en otra moneda/)).not.toBeInTheDocument();
  });
});

/**
 * Tests for SaleDetailPanel.jsx (ventas-ml-rediseno PR13).
 *
 * Migrated from `DesgloseDrawer.test.jsx` — see the assertion-mapping
 * table in the PR13 report for what changed and why. In short: every test
 * about CONTENT (lines, IVA, Total Gauss, item detail, incomplete/error
 * states, stale-response guard) moved over unchanged in intent, only
 * dropping the removed `open` prop and the `role="dialog"` query in favor
 * of `getByText('Desglose de costos')`/the panel's own DOM. Every test
 * about the MODAL SHELL (focus trap, backdrop click, aria-modal, focus
 * restore) did NOT migrate: that behavior was deleted on purpose — see
 * `VentasMLLayout.test.jsx` for its replacement (Escape without a trap,
 * no overlay, rows stay selectable).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act, within } from '@testing-library/react';
import SaleDetailPanel from './SaleDetailPanel';
import api from '../../services/api';

function mockBreakdown(orderId, breakdown) {
  api.get.mockImplementation((url) => {
    if (url === `/ml-ventas-ops/orders/${orderId}`) {
      return Promise.resolve({ data: { breakdown } });
    }
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  api.get.mockReset();
});

describe('Fetch and render on mount', () => {
  it('fetches the breakdown and renders it', async () => {
    mockBreakdown(1001, {
      lines: [
        { concepto: 'Cargo por vender', monto: 91250, origen: 'api' },
        { concepto: 'Costo por ofrecer cuotas', monto: 97820, origen: 'api' },
        { concepto: 'Envíos', monto: 15190, origen: 'api' },
      ],
      neto: 525740,
      incompleto: false,
      incomplete_reasons: [],
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    expect(await screen.findByText('Desglose de costos')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/orders/1001');

    // Rendered exactly as the backend sent them, in the given order.
    const items = await screen.findAllByRole('listitem');
    expect(items.map((li) => li.textContent)).toEqual([
      'Cargo por vender91.250,00',
      'Costo por ofrecer cuotas97.820,00',
      'Envíos15.190,00',
    ]);
    expect(screen.getByText('525.740,00')).toBeInTheDocument();
  });
});

describe('Switching orders without closing', () => {
  it('re-fetches when orderId changes, staying mounted (R2 — never closes on its own)', async () => {
    mockBreakdown(1001, {
      lines: [{ concepto: 'Cargo por vender', monto: 10, origen: 'api' }],
      neto: 90,
      incompleto: false,
      incomplete_reasons: [],
    });
    const { rerender } = render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/orders/1001'));

    mockBreakdown(1002, {
      lines: [{ concepto: 'Costo fijo', monto: 20, origen: 'api' }],
      neto: 80,
      incompleto: false,
      incomplete_reasons: [],
    });
    rerender(<SaleDetailPanel orderId={1002} onClose={vi.fn()} />);

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/orders/1002'));
    expect(await screen.findByText('Costo fijo')).toBeInTheDocument();
    // Never unmounted between orders — the panel stayed on screen the
    // whole time.
    expect(screen.getByText('Desglose de costos')).toBeInTheDocument();
  });
});

describe('Incomplete breakdown', () => {
  it('shows the plain-language reason for payments_not_synced, never the raw code', async () => {
    mockBreakdown(1001, {
      lines: [],
      neto: null,
      incompleto: true,
      incomplete_reasons: ['payments_not_synced'],
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    expect(await screen.findByText(/todav[ií]a no los trajo/i)).toBeInTheDocument();
    expect(screen.queryByText('payments_not_synced')).not.toBeInTheDocument();
  });

  it('shows the plain-language reason for billing_not_swept and still shows the partial total, not a dash', async () => {
    mockBreakdown(1001, {
      lines: [{ concepto: 'Cargo por vender', monto: 100, origen: 'api' }],
      neto: 900,
      incompleto: true,
      incomplete_reasons: ['billing_not_swept'],
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    expect(await screen.findByText(/falta el barrido de facturaci[oó]n/i)).toBeInTheDocument();
    // The real partial number stays visible — never hidden behind a dash.
    expect(screen.getByText('900,00')).toBeInTheDocument();
  });
});

describe('Closing', () => {
  it('calls onClose when the close button is clicked', async () => {
    mockBreakdown(1001, { lines: [], neto: null, incompleto: false, incomplete_reasons: [] });
    const onClose = vi.fn();
    render(<SaleDetailPanel orderId={1001} onClose={onClose} />);

    const closeButton = await screen.findByRole('button', { name: /cerrar/i });
    closeButton.click();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('Stale response guard', () => {
  it('never lets an older row selection overwrite a newer one, mirroring VentasML.jsx', async () => {
    const resolvers = {};
    api.get.mockImplementation((url) => {
      const match = url.match(/\/ml-ventas-ops\/orders\/(\d+)/);
      if (match) {
        return new Promise((resolve) => {
          resolvers[match[1]] = resolve;
        });
      }
      return Promise.resolve({ data: {} });
    });

    const { rerender } = render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);
    await waitFor(() => expect(resolvers['1001']).toBeDefined());

    // Operator picks row B before A's response arrives.
    rerender(<SaleDetailPanel orderId={1002} onClose={vi.fn()} />);
    await waitFor(() => expect(resolvers['1002']).toBeDefined());

    // B's response arrives FIRST, then the stale A response arrives LAST.
    resolvers['1002']({
      data: {
        breakdown: {
          lines: [{ concepto: 'Costo fijo', monto: 20, origen: 'api' }],
          neto: 80,
          incompleto: false,
          incomplete_reasons: [],
        },
      },
    });
    await screen.findByText('Costo fijo');

    resolvers['1001']({
      data: {
        breakdown: {
          lines: [{ concepto: 'Cargo por vender', monto: 10, origen: 'api' }],
          neto: 90,
          incompleto: false,
          incomplete_reasons: [],
        },
      },
    });

    // The stale A payload must never appear — B is still selected.
    await waitFor(() => expect(screen.getByText('Costo fijo')).toBeInTheDocument());
    expect(screen.queryByText('Cargo por vender')).not.toBeInTheDocument();
  });

  it('keeps showing the loader when the stale response lands while the newer one is still in flight', async () => {
    // The test above resolves the stale response LAST, when loading is
    // already false, so it cannot fail if the `finally` guard is removed.
    // The guard earns its place in this order instead: the old response
    // arrives while the new request is still pending. Without it, the
    // panel stops saying "Cargando" and renders empty for a sale whose
    // numbers have not arrived — the operator reads absence as an answer.
    const resolvers = {};
    api.get.mockImplementation((url) => {
      const match = url.match(/\/ml-ventas-ops\/orders\/(\d+)/);
      if (match) {
        return new Promise((resolve) => {
          resolvers[match[1]] = resolve;
        });
      }
      return Promise.resolve({ data: {} });
    });

    const { rerender } = render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);
    await waitFor(() => expect(resolvers['1001']).toBeDefined());

    rerender(<SaleDetailPanel orderId={1002} onClose={vi.fn()} />);
    await waitFor(() => expect(resolvers['1002']).toBeDefined());

    // Only the STALE one answers. B is still in flight.
    resolvers['1001']({
      data: {
        breakdown: {
          lines: [{ concepto: 'Cargo por vender', monto: 10, origen: 'api' }],
          neto: 90,
          incompleto: false,
          incomplete_reasons: [],
        },
      },
    });

    // Flush the stale promise's continuations BEFORE asserting. Without
    // this the assertion finds the loader that was already on screen and
    // passes whether or not the guard exists.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText('Cargando desglose…')).toBeInTheDocument();
    expect(screen.queryByText('Cargo por vender')).not.toBeInTheDocument();
  });
});

describe('A response with no breakdown', () => {
  it('says so instead of rendering an empty panel', async () => {
    // Blank is the worst of the three states: it looks like a sale that
    // left nothing, which is a number we never received. No loader, no
    // error and no lines used to render exactly that.
    api.get.mockResolvedValue({ data: {} });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    expect(
      await screen.findByText('Esta venta todavía no tiene desglose disponible.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Cargando desglose…')).not.toBeInTheDocument();
    expect(screen.queryByText('Error al cargar el desglose.')).not.toBeInTheDocument();
  });
});

describe('The incomplete reason must match what actually happened', () => {
  it('tells the operator to check the payment, not to wait for a sweep that already ran', async () => {
    api.get.mockResolvedValue({
      data: {
        breakdown: {
          lines: [],
          neto: null,
          incompleto: true,
          incomplete_reasons: ['payments_not_countable'],
        },
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    expect(await screen.findByText(/ninguno se puede computar/i)).toBeInTheDocument();
    expect(screen.queryByText(/todavía no los trajo/i)).not.toBeInTheDocument();
  });

  it('still says "waiting for the sweep" when there are no payments at all', async () => {
    api.get.mockResolvedValue({
      data: {
        breakdown: {
          lines: [],
          neto: null,
          incompleto: true,
          incomplete_reasons: ['payments_not_synced'],
        },
      },
    });
    render(<SaleDetailPanel orderId={1002} onClose={vi.fn()} />);

    expect(await screen.findByText(/todavía no los trajo/i)).toBeInTheDocument();
  });
});

describe('IVA decomposition and Total Gauss chain (ml-ventas-modo-logistico PR6)', () => {
  function mockDetail(orderId, { breakdown, iva_decomposicion, cadena_total_gauss } = {}) {
    api.get.mockImplementation((url) => {
      if (url === `/ml-ventas-ops/orders/${orderId}`) {
        return Promise.resolve({ data: { breakdown, iva_decomposicion, cadena_total_gauss } });
      }
      return Promise.resolve({ data: {} });
    });
  }

  const BASE_BREAKDOWN = { lines: [], neto: 100, incompleto: false, incomplete_reasons: [] };

  describe('defensive: fields absent', () => {
    it('renders the existing breakdown fine when iva_decomposicion/cadena_total_gauss are absent', async () => {
      mockDetail(1001, { breakdown: BASE_BREAKDOWN });
      render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

      expect(await screen.findByText('Desglose de costos')).toBeInTheDocument();
      expect(screen.getByText('Neto')).toBeInTheDocument();
      expect(screen.queryByText('IVA por alícuota')).not.toBeInTheDocument();
      expect(screen.queryByText('Total Gauss')).not.toBeInTheDocument();
    });

    it('renders fine when iva_decomposicion/cadena_total_gauss are explicitly null', async () => {
      mockDetail(1001, { breakdown: BASE_BREAKDOWN, iva_decomposicion: null, cadena_total_gauss: null });
      render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

      expect(await screen.findByText('Desglose de costos')).toBeInTheDocument();
      expect(screen.queryByText('IVA por alícuota')).not.toBeInTheDocument();
    });
  });

  describe('historical sale with no frozen cost', () => {
    it('says "sin costo congelado" instead of an error, never a $0', async () => {
      mockDetail(1001, {
        breakdown: BASE_BREAKDOWN,
        iva_decomposicion: {
          componentes: [],
          neto_sin_iva: null,
          reconcilia: false,
          diferencia: null,
          razones: ['item_sin_costo_congelado'],
        },
        cadena_total_gauss: { total_gauss: null, lineas: [] },
      });
      render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

      expect(await screen.findByText(/sin costo congelado/i)).toBeInTheDocument();
      expect(screen.queryByText('$0')).not.toBeInTheDocument();
      expect(screen.queryByText('0,00')).not.toBeInTheDocument();
    });
  });

  describe('chain blocked at one link', () => {
    it('shows "—" for the unresolved link and names it under Total Gauss, never a zero', async () => {
      mockDetail(1001, {
        breakdown: BASE_BREAKDOWN,
        iva_decomposicion: {
          componentes: [{ concepto: 'Venta ítem', alicuota: 21, bruto: 100, base: 82.64, iva: 17.36 }],
          neto_sin_iva: 82.64,
          reconcilia: true,
          diferencia: 0,
          razones: [],
        },
        cadena_total_gauss: {
          total_gauss: null,
          lineas: [
            { code: 'costo_mercaderia', monto: null },
            { code: 'envio_flex', monto: 5 },
            { code: 'varios', monto: 2 },
          ],
        },
      });
      render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

      await screen.findByRole('heading', { name: 'Total Gauss' });
      expect(screen.getByText('Costo de mercadería')).toBeInTheDocument();
      expect(screen.getByText(/sin costo de mercadería conocido/i)).toBeInTheDocument();
      const totalLabels = screen.getAllByText('Total Gauss');
      const totalRow = totalLabels[totalLabels.length - 1].closest('div');
      expect(within(totalRow).getByText('—')).toBeInTheDocument();
    });
  });

  describe('fully resolved chain', () => {
    it('renders the full chain and a numeric Total Gauss', async () => {
      mockDetail(1001, {
        breakdown: BASE_BREAKDOWN,
        iva_decomposicion: {
          componentes: [{ concepto: 'Venta ítem', alicuota: 21, bruto: 100, base: 82.64, iva: 17.36 }],
          neto_sin_iva: 82.64,
          reconcilia: true,
          diferencia: 0,
          razones: [],
        },
        cadena_total_gauss: {
          total_gauss: 70.64,
          lineas: [
            { code: 'costo_mercaderia', monto: 10 },
            { code: 'envio_flex', monto: 0 },
            { code: 'varios', monto: 2 },
          ],
        },
      });
      render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

      expect(await screen.findByText('Neto sin IVA')).toBeInTheDocument();
      expect(screen.getByText('Envío Flex')).toBeInTheDocument();
      expect(screen.getByText('% de varios')).toBeInTheDocument();
      expect(screen.getByText('70,64')).toBeInTheDocument();
    });
  });

  describe('IVA rows per alícuota', () => {
    it('renders each componente with its own base/IVA/alícuota', async () => {
      mockDetail(1001, {
        breakdown: BASE_BREAKDOWN,
        iva_decomposicion: {
          componentes: [
            { concepto: 'Venta ítem 21%', alicuota: 21, bruto: 121, base: 100, iva: 21 },
            { concepto: 'Retención', alicuota: null, bruto: -5, base: -5, iva: 0 },
          ],
          neto_sin_iva: 95,
          reconcilia: true,
          diferencia: 0,
          razones: [],
        },
        cadena_total_gauss: { total_gauss: null, lineas: [] },
      });
      render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

      expect(await screen.findByText('IVA por alícuota')).toBeInTheDocument();
      expect(screen.getByText(/Venta ítem 21%/)).toBeInTheDocument();
      expect(screen.getByText(/\(21,00%\)/)).toBeInTheDocument();
      expect(screen.getByText(/Sin alícuota/)).toBeInTheDocument();
    });

    it('renders the named reason instead of a componentes table when it does not reconcile', async () => {
      mockDetail(1001, {
        breakdown: BASE_BREAKDOWN,
        iva_decomposicion: {
          componentes: [],
          neto_sin_iva: null,
          reconcilia: false,
          diferencia: null,
          razones: ['sin_pagos_sincronizados'],
        },
        cadena_total_gauss: { total_gauss: null, lineas: [] },
      });
      render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

      expect(await screen.findByText(/todavía no se sincronizaron/i)).toBeInTheDocument();
    });
  });
});

describe('Flex own-cost line vs the Total Gauss chain', () => {
  it('does not render a propio line above Neto, but keeps api lines', async () => {
    mockBreakdown(1001, {
      lines: [
        { concepto: 'Cargo por vender', monto: 100, origen: 'api' },
        { concepto: 'Envío Flex (costo propio)', monto: 50, origen: 'propio' },
      ],
      neto: 900,
      incompleto: false,
      incomplete_reasons: [],
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    await screen.findByText('Desglose de costos');

    expect(screen.getByText('Cargo por vender')).toBeInTheDocument();
    expect(screen.queryByText('Envío Flex (costo propio)')).not.toBeInTheDocument();
  });
});

describe('SIRTAC recuperable, componentes informativos y sub-línea de Neto (ml-ventas-neto-iibb-varios)', () => {
  function mockDetail(orderId, { breakdown, iva_decomposicion } = {}) {
    api.get.mockImplementation((url) => {
      if (url === `/ml-ventas-ops/orders/${orderId}`) {
        return Promise.resolve({ data: { breakdown, iva_decomposicion } });
      }
      return Promise.resolve({ data: {} });
    });
  }

  it('renders the SIRTAC line as a muted row after the subtraction list, excluded from it', async () => {
    mockDetail(1001, {
      breakdown: {
        lines: [
          { concepto: 'Cargo por vender', monto: 74676.08, origen: 'api' },
          { concepto: 'Retención IIBB (CABA) · SIRTAC', monto: 1792.23, origen: 'recuperable' },
        ],
        neto: 503958.14,
        neto_depositado: 502165.91,
        retenciones_recuperables: 1792.23,
        incompleto: false,
        incomplete_reasons: [],
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    await screen.findByText('Desglose de costos');

    const subtractionList = screen.getByText('Cargo por vender').closest('ul');
    expect(subtractionList).not.toBeNull();
    expect(within(subtractionList).queryByText('Retención IIBB (CABA) · SIRTAC')).not.toBeInTheDocument();

    const recuperableRow = screen.getByText('Retención IIBB (CABA) · SIRTAC').closest('li');
    expect(recuperableRow).toBeInTheDocument();
    expect(subtractionList.contains(recuperableRow)).toBe(false);
  });

  it('renders an informativo IVA componente muted, with no base/IVA figures', async () => {
    mockDetail(1001, {
      breakdown: { lines: [], neto: 100, incompleto: false, incomplete_reasons: [] },
      iva_decomposicion: {
        componentes: [
          { concepto: 'Venta', alicuota: 21, bruto: 100, base: 82.64, iva: 17.36, informativo: false },
          {
            concepto: 'Retención IIBB (CABA) · SIRTAC',
            alicuota: null,
            bruto: -20,
            base: -20,
            iva: 0,
            informativo: true,
          },
        ],
        neto_sin_iva: 82.64,
        reconcilia: true,
        diferencia: 0,
        razones: [],
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    await screen.findByText('Desglose de costos');

    expect(screen.getByText(/informativo/i)).toBeInTheDocument();
    expect(screen.queryByText(/base -20,00 · IVA 0,00/i)).not.toBeInTheDocument();
  });

  it('shows the Neto sub-line "MP $X · SIRTAC $Y" when retenciones_recuperables > 0', async () => {
    mockDetail(1001, {
      breakdown: {
        lines: [],
        neto: 503958.14,
        neto_depositado: 502165.91,
        retenciones_recuperables: 1792.23,
        incompleto: false,
        incomplete_reasons: [],
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    await screen.findByText('Desglose de costos');

    expect(screen.getByText('MP $ 502.165,91 · SIRTAC $ 1.792,23')).toBeInTheDocument();
  });

  it.each([
    ['0', 0],
    ['null', null],
  ])('does not show the sub-line when retenciones_recuperables is %s', async (_label, retenciones) => {
    mockDetail(1001, {
      breakdown: {
        lines: [],
        neto: 500,
        neto_depositado: 500,
        retenciones_recuperables: retenciones,
        incompleto: false,
        incomplete_reasons: [],
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    await screen.findByText('Desglose de costos');

    expect(screen.queryByText(/^MP \$/)).not.toBeInTheDocument();
  });
});

describe('Monto de la operación', () => {
  it('renders paid_amount summed across the operation, above the line list', async () => {
    mockBreakdown(1001, {
      lines: [{ concepto: 'Cargo por vender', monto: 100, origen: 'api' }],
      neto: 900,
      incompleto: false,
      incomplete_reasons: [],
      monto_operacion: 1000,
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    expect(await screen.findByText('Monto de la operación')).toBeInTheDocument();
    expect(screen.getByText('1.000,00')).toBeInTheDocument();
  });

  it('renders the unknown treatment, never a zero, when monto_operacion is null', async () => {
    mockBreakdown(1001, {
      lines: [],
      neto: null,
      incompleto: false,
      incomplete_reasons: [],
      monto_operacion: null,
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    const label = await screen.findByText('Monto de la operación');
    expect(label.nextSibling).toHaveTextContent('—');
    expect(label.nextSibling).not.toHaveTextContent('0,00');
  });
});

describe('Markup (total_gauss / costo de mercadería, as a percentage)', () => {
  function mockDetail(orderId, { breakdown, iva_decomposicion, cadena_total_gauss } = {}) {
    api.get.mockImplementation((url) => {
      if (url === `/ml-ventas-ops/orders/${orderId}`) {
        return Promise.resolve({ data: { breakdown, iva_decomposicion, cadena_total_gauss } });
      }
      return Promise.resolve({ data: {} });
    });
  }

  const BASE_BREAKDOWN = { lines: [], neto: 100, incompleto: false, incomplete_reasons: [] };

  it('renders the markup percentage below Total Gauss', async () => {
    mockDetail(1001, {
      breakdown: BASE_BREAKDOWN,
      iva_decomposicion: {
        componentes: [],
        neto_sin_iva: 67686.47,
        reconcilia: true,
        diferencia: 0,
        razones: [],
      },
      cadena_total_gauss: {
        total_gauss: 8812.07,
        lineas: [{ code: 'costo_mercaderia', monto: 58874.4 }],
        markup: 14.97,
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    expect(await screen.findByText('Markup')).toBeInTheDocument();
    expect(screen.getByText('14,97%')).toBeInTheDocument();
  });

  it('renders the unknown treatment, never 0%, when markup is null', async () => {
    mockDetail(1001, {
      breakdown: BASE_BREAKDOWN,
      iva_decomposicion: {
        componentes: [],
        neto_sin_iva: 100,
        reconcilia: true,
        diferencia: 0,
        razones: [],
      },
      cadena_total_gauss: {
        total_gauss: null,
        lineas: [{ code: 'costo_mercaderia', monto: null }],
        markup: null,
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    await screen.findByText('Markup');
    const markupRow = screen.getByText('Markup').closest('div');
    expect(within(markupRow).getByText('—')).toBeInTheDocument();
    expect(screen.queryByText('0%')).not.toBeInTheDocument();
  });
});

describe('Product detail under "Monto de la operación" (ml-ventas-desglose-costos)', () => {
  function mockDetail(orderId, { breakdown, iva_decomposicion, cadena_total_gauss } = {}) {
    api.get.mockImplementation((url) => {
      if (url === `/ml-ventas-ops/orders/${orderId}`) {
        return Promise.resolve({ data: { breakdown, iva_decomposicion, cadena_total_gauss } });
      }
      return Promise.resolve({ data: {} });
    });
  }

  it('renders one line per item, under the total, matching quantity and amount', async () => {
    mockDetail(1001, {
      breakdown: {
        lines: [],
        neto: 99333,
        incompleto: false,
        incomplete_reasons: [],
        monto_operacion: 99333,
        item_lines: [
          {
            item_id: 'MLA1',
            title: 'Board Asus Prime A520m-k / Am4 / Ddr4',
            quantity: 1,
            monto: 99333,
          },
        ],
        item_lines_reconcilia: true,
        item_lines_razon: null,
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    const titulo = await screen.findByText(/board asus prime/i);
    const lista = screen.getByLabelText('Detalle de productos');
    expect(lista).toContainElement(titulo);
    expect(titulo.closest('li')).toHaveTextContent('99.333,00');
    expect(screen.queryByText(/no se puede calcular el monto/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/no tiene ítems cargados/i)).not.toBeInTheDocument();
  });

  it('shows quantity when greater than 1', async () => {
    mockDetail(1001, {
      breakdown: {
        lines: [],
        neto: 200,
        incompleto: false,
        incomplete_reasons: [],
        monto_operacion: 200,
        item_lines: [{ item_id: 'MLA1', title: 'Mouse', quantity: 2, monto: 200 }],
        item_lines_reconcilia: true,
        item_lines_razon: null,
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    expect(await screen.findByText(/mouse \(x2\)/i)).toBeInTheDocument();
  });

  it('surfaces the named reason instead of pretending the list is trustworthy when it cannot reconcile', async () => {
    mockDetail(1001, {
      breakdown: {
        lines: [],
        neto: 200,
        incompleto: false,
        incomplete_reasons: [],
        monto_operacion: 200,
        item_lines: [
          { item_id: 'MLA1', title: 'Mouse', quantity: 1, monto: 100 },
          { item_id: 'MLA2', title: 'Teclado', quantity: 1, monto: null },
        ],
        item_lines_reconcilia: false,
        item_lines_razon: 'item_lines_item_sin_precio',
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    expect(
      await screen.findByText(/no tienen precio unitario cargado.*no se puede calcular el monto/i),
    ).toBeInTheDocument();
    const sinPrecio = screen.getByText(/teclado/i);
    expect(sinPrecio.closest('li')).toHaveTextContent('—');
    expect(sinPrecio.closest('li')).not.toHaveTextContent('0,00');
  });
});

describe('Costo de mercadería per-item arithmetic (ml-ventas-desglose-costos)', () => {
  function mockDetail(orderId, { breakdown, iva_decomposicion, cadena_total_gauss } = {}) {
    api.get.mockImplementation((url) => {
      if (url === `/ml-ventas-ops/orders/${orderId}`) {
        return Promise.resolve({ data: { breakdown, iva_decomposicion, cadena_total_gauss } });
      }
      return Promise.resolve({ data: {} });
    });
  }

  const BASE_BREAKDOWN = { lines: [], neto: 100, incompleto: false, incomplete_reasons: [] };

  it('renders a USD-costed item WITH the exchange rate and its date', async () => {
    mockDetail(1001, {
      breakdown: BASE_BREAKDOWN,
      iva_decomposicion: { componentes: [], neto_sin_iva: 100, reconcilia: true, diferencia: 0, razones: [] },
      cadena_total_gauss: {
        total_gauss: 900,
        lineas: [{ code: 'costo_mercaderia', monto: 100 }],
        markup: 900,
        costo_mercaderia_items: [
          {
            item_id: 'MLA1',
            title: 'Board Asus',
            quantity: 1,
            conocido: true,
            moneda: 'USD',
            costo_origen: 45,
            tipo_cambio: 1183.5,
            tipo_cambio_fecha: '2026-07-01',
            costo_unitario_ars: 53257.5,
            fuente: 'erp_sku',
            costo_fecha: null,
          },
        ],
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    expect(await screen.findByText(/USD 45,00/)).toBeInTheDocument();
    expect(screen.getByText(/1\.183,50/)).toBeInTheDocument();
    expect(screen.getByText(/01\/07\/2026/)).toBeInTheDocument();
    expect(screen.getByText(/53\.257,50/)).toBeInTheDocument();
  });

  it('spells out the quantity so the cost of the LINE can be replicated, not just the unit', async () => {
    mockDetail(1001, {
      breakdown: BASE_BREAKDOWN,
      iva_decomposicion: { componentes: [], neto_sin_iva: 100, reconcilia: true, diferencia: 0, razones: [] },
      cadena_total_gauss: {
        total_gauss: 900,
        lineas: [{ code: 'costo_mercaderia', monto: 100 }],
        markup: 900,
        costo_mercaderia_items: [
          {
            item_id: 'MLA1',
            title: 'Board Asus',
            quantity: 3,
            conocido: true,
            moneda: 'ARS',
            costo_origen: 5000,
            tipo_cambio: null,
            tipo_cambio_fecha: null,
            costo_unitario_ars: 5000,
            fuente: 'erp_sku',
            costo_fecha: null,
          },
        ],
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    const titulo = await screen.findByText(/board asus/i);
    const fila = titulo.closest('li');
    expect(fila).toHaveTextContent('× 3');
    expect(fila).toHaveTextContent('15.000,00');
  });

  it('does not clutter a single-unit line with a quantity multiplier', async () => {
    mockDetail(1001, {
      breakdown: BASE_BREAKDOWN,
      iva_decomposicion: { componentes: [], neto_sin_iva: 100, reconcilia: true, diferencia: 0, razones: [] },
      cadena_total_gauss: {
        total_gauss: 900,
        lineas: [{ code: 'costo_mercaderia', monto: 100 }],
        markup: 900,
        costo_mercaderia_items: [
          {
            item_id: 'MLA1',
            title: 'Board Asus',
            quantity: 1,
            conocido: true,
            moneda: 'ARS',
            costo_origen: 5000,
            tipo_cambio: null,
            tipo_cambio_fecha: null,
            costo_unitario_ars: 5000,
            fuente: 'erp_sku',
            costo_fecha: null,
          },
        ],
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    const titulo = await screen.findByText(/board asus/i);
    expect(titulo.closest('li')).not.toHaveTextContent('c/u');
  });

  it('renders an ARS-costed item with NO exchange-rate arithmetic line', async () => {
    mockDetail(1001, {
      breakdown: BASE_BREAKDOWN,
      iva_decomposicion: { componentes: [], neto_sin_iva: 100, reconcilia: true, diferencia: 0, razones: [] },
      cadena_total_gauss: {
        total_gauss: 900,
        lineas: [{ code: 'costo_mercaderia', monto: 100 }],
        markup: 900,
        costo_mercaderia_items: [
          {
            item_id: 'MLA2',
            title: 'Mouse Logitech',
            quantity: 1,
            conocido: true,
            moneda: 'ARS',
            costo_origen: 5000,
            tipo_cambio: null,
            tipo_cambio_fecha: null,
            costo_unitario_ars: 5000,
            fuente: 'erp_publicacion',
            costo_fecha: null,
          },
        ],
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    expect(await screen.findByText(/mouse logitech/i)).toBeInTheDocument();
    expect(screen.queryByText(/×/)).not.toBeInTheDocument();
    expect(screen.getByText('$ 5.000,00')).toBeInTheDocument();
  });

  it('renders an item with no frozen cost row as unknown, never a $0', async () => {
    mockDetail(1001, {
      breakdown: BASE_BREAKDOWN,
      iva_decomposicion: { componentes: [], neto_sin_iva: 100, reconcilia: true, diferencia: 0, razones: [] },
      cadena_total_gauss: {
        total_gauss: null,
        lineas: [{ code: 'costo_mercaderia', monto: null }],
        markup: null,
        costo_mercaderia_items: [
          {
            item_id: 'MLA3',
            title: 'Sin costo',
            quantity: 1,
            conocido: false,
          },
        ],
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    expect(await screen.findByText(/costo desconocido/i)).toBeInTheDocument();
    expect(screen.queryByText('$ 0,00')).not.toBeInTheDocument();
  });

  it('stacks the cost row instead of splitting it into two columns', async () => {
    mockDetail(1001, {
      breakdown: BASE_BREAKDOWN,
      iva_decomposicion: { componentes: [], neto_sin_iva: 100, reconcilia: true, diferencia: 0, razones: [] },
      cadena_total_gauss: {
        total_gauss: 900,
        lineas: [{ code: 'costo_mercaderia', monto: 100 }],
        markup: 900,
        costo_mercaderia_items: [
          {
            item_id: 'MLA1',
            title:
              'Cámara Wi-fi Tp-link Tapo C201 Full Hd 360° Visión Nocturna Detección Por Ia Y Llanto De Bebé Color Negro',
            quantity: 1,
            conocido: true,
            moneda: 'USD',
            costo_origen: 14.3,
            tipo_cambio: 1535,
            tipo_cambio_fecha: '2026-09-17',
            costo_unitario_ars: 21950.5,
            fuente: 'erp_publicacion',
            costo_fecha: null,
          },
        ],
      },
    });
    render(<SaleDetailPanel orderId={1001} onClose={vi.fn()} />);

    const titulo = await screen.findByText(/cámara wi-fi tp-link tapo c201/i);
    const fila = titulo.closest('li');
    expect(fila.className).toMatch(/costoItemLine/);
    expect(fila.className).not.toMatch(/(^|\s)itemLine(\s|$)/);
  });
});

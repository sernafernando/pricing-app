import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import PppLine from './PppLine';

describe('PppLine — informational PPP companion line', () => {
  it('renders "sin PPP" when ppp is null', () => {
    render(<PppLine ppp={null} />);
    expect(screen.getByText('sin PPP')).toBeTruthy();
  });

  it('renders "sin PPP" when ppp is undefined', () => {
    render(<PppLine ppp={undefined} />);
    expect(screen.getByText('sin PPP')).toBeTruthy();
  });

  it('renders costo + date (dd/mm/aa) when no markupKey is given', () => {
    render(<PppLine ppp={{ costo: 1234.5, fecha: '2026-07-15', markups: {} }} />);
    expect(screen.getByText(/\$1234\.50/)).toBeTruthy();
    expect(screen.getByText(/15\/07\/26/)).toBeTruthy();
  });

  it('renders the cost cell companion in ARS when no display conversion is present', () => {
    render(<PppLine ppp={{ costo: 1234.5, fecha: '2026-07-15', markups: {} }} />);
    expect(screen.getByText(/ARS \$1234\.50/)).toBeTruthy();
  });

  it('renders the cost cell companion in USD, mirroring the list-cost cell currency label', () => {
    render(
      <PppLine
        ppp={{
          costo: 8500,
          costo_display: 8.5,
          costo_display_moneda: 'USD',
          fecha: '2026-07-15',
          markups: {},
        }}
      />
    );
    expect(screen.getByText(/USD \$8\.50/)).toBeTruthy();
  });

  it('renders an already-percent markup as-is', () => {
    render(
      <PppLine
        ppp={{ costo: 100, fecha: '2026-01-05', markups: { pvp_clasica: 32.5 } }}
        markupKey="pvp_clasica"
      />
    );
    expect(screen.getByText(/32\.50%/)).toBeTruthy();
    expect(screen.getByText(/05\/01\/26/)).toBeTruthy();
  });

  it('scales the raw-ratio mejor_oferta key by x100 (RAW DECIMAL RATIO, not percent)', () => {
    render(
      <PppLine
        ppp={{ costo: 100, fecha: '2026-01-05', markups: { mejor_oferta: 0.612 } }}
        markupKey="mejor_oferta"
      />
    );
    expect(screen.getByText(/61\.20%/)).toBeTruthy();
  });

  it('renders "sin PPP" (not a crash) when markupKey is missing from markups', () => {
    render(
      <PppLine
        ppp={{ costo: 100, fecha: '2026-01-05', markups: { pvp_clasica: 10 } }}
        markupKey="unknown_key"
      />
    );
    expect(screen.getByText('sin PPP')).toBeTruthy();
  });

  it('never reads costo as a substitute value for a markup line', () => {
    // ppp present with costo populated but the requested markup absent —
    // must still show "sin PPP", never a costo-derived fallback.
    render(
      <PppLine
        ppp={{ costo: 999.99, fecha: '2026-01-05', markups: {} }}
        markupKey="cuota_clasica_3"
      />
    );
    expect(screen.getByText('sin PPP')).toBeTruthy();
    expect(screen.queryByText(/999\.99/)).toBeNull();
  });

  it('renders the clasica key (T2.6, reopened) as an already-percent markup', () => {
    render(
      <PppLine
        ppp={{ costo: 100, fecha: '2026-01-05', markups: { clasica: 45.5 } }}
        markupKey="clasica"
      />
    );
    expect(screen.getByText(/45\.50%/)).toBeTruthy();
    expect(screen.getByText(/05\/01\/26/)).toBeTruthy();
  });

  it('renders "sin PPP" for clasica when the key is absent (e.g. missing precio_lista_ml)', () => {
    render(
      <PppLine
        ppp={{ costo: 100, fecha: '2026-01-05', markups: {} }}
        markupKey="clasica"
      />
    );
    expect(screen.getByText('sin PPP')).toBeTruthy();
  });

  describe('instalment key family (cuota_clasica_{n} / pvp_cuota_{n}) — highest key-typo risk', () => {
    const markups = {
      cuota_clasica_3: 10,
      cuota_clasica_6: 20,
      cuota_clasica_9: 30,
      cuota_clasica_12: 40,
      pvp_cuota_3: 11,
      pvp_cuota_6: 21,
      pvp_cuota_9: 31,
      pvp_cuota_12: 41,
    };

    it.each([
      ['cuota_clasica_3', '10.00%'],
      ['cuota_clasica_6', '20.00%'],
      ['cuota_clasica_9', '30.00%'],
      ['cuota_clasica_12', '40.00%'],
      ['pvp_cuota_3', '11.00%'],
      ['pvp_cuota_6', '21.00%'],
      ['pvp_cuota_9', '31.00%'],
      ['pvp_cuota_12', '41.00%'],
    ])('renders the exact value recorded under %s, never a sibling instalment value', (key, expected) => {
      render(<PppLine ppp={{ costo: 100, fecha: '2026-01-05', markups }} markupKey={key} />);
      expect(screen.getByText(new RegExp(expected.replace('.', '\\.')))).toBeTruthy();
    });

    it('renders "sin PPP" for a key that is absent, without falling back to a similarly named one', () => {
      render(
        <PppLine
          ppp={{ costo: 100, fecha: '2026-01-05', markups: { pvp_cuota_3: 11 } }}
          markupKey="pvp_cuota_30"
        />
      );
      expect(screen.getByText('sin PPP')).toBeTruthy();
    });
  });
});

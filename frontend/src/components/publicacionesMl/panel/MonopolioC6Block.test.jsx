import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import MonopolioC6Block from './MonopolioC6Block';

vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../promociones/PromoApplyControl', () => ({
  default: function PromoApplyControlStub({ label }) {
    return <button type="button">{label}</button>;
  },
}));

describe('MonopolioC6Block', () => {
  const oportunidad = {
    our_price: 10000,
    segundo_precio: 16000,
    gap: 6000,
    precio_objetivo: 15900,
    solo_via_promo: false,
  };

  it('shows markup pct and Premium apply when available', () => {
    render(
      <MonopolioC6Block
        oportunidad={oportunidad}
        markupPct={12.5}
        premiumPromo={{
          promotion_id: 'PREM-1',
          promotion_type: 'SELLER_CAMPAIGN',
          status: 'candidate',
          name: 'Premium noviembre',
          min_discounted_price: 10000,
          max_discounted_price: 20000,
          price: 14000,
        }}
        itemId="MLA1"
      />,
    );
    expect(screen.getByText(/con 12\.5% de markup/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Aplicar Premium al objetivo/i })).toBeInTheDocument();
  });

  it('shows apply-fail aviso when provided', () => {
    render(
      <MonopolioC6Block
        oportunidad={oportunidad}
        applyFailMessage="Autoapply falló: stock insuficiente"
      />,
    );
    expect(screen.getByText(/Autoapply falló: stock insuficiente/)).toBeInTheDocument();
  });

  it('solo_via_promo explains no editable Premium', () => {
    render(
      <MonopolioC6Block
        oportunidad={{ ...oportunidad, solo_via_promo: true }}
        markupPct={8}
      />,
    );
    expect(screen.getByText(/solo vía promo/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Aplicar Premium/i })).not.toBeInTheDocument();
  });
});

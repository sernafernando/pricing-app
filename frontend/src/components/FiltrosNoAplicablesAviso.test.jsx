import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import FiltrosNoAplicablesAviso from './FiltrosNoAplicablesAviso';

describe('FiltrosNoAplicablesAviso — says which active filters the bulk op ignores', () => {
  it('renders nothing when no unsupported filter is active', () => {
    const { container } = render(
      <FiltrosNoAplicablesAviso filtrosActivos={{ marcas: ['ACME'], filtroMLA: 'con_mla' }} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when filtrosActivos is missing', () => {
    const { container } = render(<FiltrosNoAplicablesAviso filtrosActivos={undefined} />);
    expect(container.firstChild).toBeNull();
  });

  it('warns and names the wholesale filter when it is on', () => {
    render(<FiltrosNoAplicablesAviso filtrosActivos={{ filtroPxq: 'con_pxq' }} />);
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByText(/Con precios mayoristas/)).toBeTruthy();
  });

  it('says the operation runs over a WIDER set — never implies it matches the listing', () => {
    render(<FiltrosNoAplicablesAviso filtrosActivos={{ filtroPxq: 'con_pxq' }} />);
    expect(screen.getByRole('alert').textContent).toMatch(/más amplio/i);
  });

  it('names the promo filter too (same gap, also dropped by these modals)', () => {
    render(<FiltrosNoAplicablesAviso filtrosActivos={{ promo_tipos: 'SMART,DEAL' }} />);
    expect(screen.getByText(/Promos/)).toBeTruthy();
  });

  it('lists every unsupported filter that is active', () => {
    render(<FiltrosNoAplicablesAviso filtrosActivos={{ filtroPxq: 'con_pxq', promo_tipos: 'SMART' }} />);
    const texto = screen.getByRole('alert').textContent;
    expect(texto).toMatch(/Con precios mayoristas/);
    expect(texto).toMatch(/Promos/);
  });
});

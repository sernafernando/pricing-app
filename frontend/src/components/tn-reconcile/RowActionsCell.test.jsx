import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import RowActionsCell from './RowActionsCell';

function despublicarTargetProductId(row) {
  const published = row.tn_matches.find((tn) => tn.published === true);
  if (published) return published.product_id;
  return row.tn_matches[0]?.product_id ?? null;
}

function baseProps(overrides = {}) {
  return {
    row: { ean: 'EAN-1', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [] },
    canBanlist: true,
    canPublish: true,
    despublicarTargetProductId,
    onPublicar: vi.fn(),
    onBanear: vi.fn(),
    confirmingProductId: null,
    despublicando: false,
    onStartDespublicarConfirm: vi.fn(),
    onCancelDespublicarConfirm: vi.fn(),
    onConfirmDespublicar: vi.fn(),
    ...overrides,
  };
}

describe('RowActionsCell — primary action', () => {
  it('renders Publicar as a real, clickable button for FALTA_PUBLICAR when canPublish', async () => {
    const props = baseProps();
    const user = userEvent.setup();
    render(<RowActionsCell {...props} />);

    const btn = screen.getByRole('button', { name: 'Publicar' });
    await user.click(btn);
    expect(props.onPublicar).toHaveBeenCalledWith(props.row);
  });

  it('sin permiso de publicar no renderiza ninguna acción primaria', () => {
    render(<RowActionsCell {...baseProps({ canPublish: false })} />);
    expect(screen.queryByRole('button', { name: 'Publicar' })).not.toBeInTheDocument();
    // `Revisar` era un botón con onClick={undefined}: se veía accionable y
    // no hacía nada. Sin comportamiento no hay botón.
    expect(screen.queryByRole('button', { name: 'Revisar' })).not.toBeInTheDocument();
  });

  it('en FALTA_VINCULAR no renderiza Vincular: no existe endpoint de vinculación', () => {
    render(
      <RowActionsCell
        {...baseProps({ row: { ean: 'EAN-2', verdict: 'FALTA_VINCULAR', despublicar: false, tn_matches: [] } })}
      />
    );
    expect(screen.queryByRole('button', { name: 'Vincular' })).not.toBeInTheDocument();
  });

  it('cada botón primario que se renderiza tiene un handler real', () => {
    const onPublicar = vi.fn();
    render(<RowActionsCell {...baseProps({ canPublish: true, onPublicar })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Publicar' }));
    expect(onPublicar).toHaveBeenCalledTimes(1);
  });

  it('renders no primary button for a verdict with no primary action', () => {
    render(
      <RowActionsCell
        {...baseProps({
          row: { ean: 'EAN-3', verdict: 'OK', despublicar: false, tn_matches: [] },
          canBanlist: false,
        })}
      />
    );
    expect(screen.queryByRole('button', { name: /Publicar|Revisar|Vincular/ })).not.toBeInTheDocument();
  });
});

describe('RowActionsCell — Banear (visible action, not menu-only)', () => {
  it('renders Banear as a visible button next to the primary action for FALTA_PUBLICAR when canBanlist is true', () => {
    render(<RowActionsCell {...baseProps()} />);
    expect(screen.getByRole('button', { name: 'Banear' })).toBeInTheDocument();
  });

  it('renders Banear for FALTA_VINCULAR too', () => {
    render(
      <RowActionsCell
        {...baseProps({ row: { ean: 'EAN-2', verdict: 'FALTA_VINCULAR', despublicar: false, tn_matches: [] } })}
      />
    );
    expect(screen.getByRole('button', { name: 'Banear' })).toBeInTheDocument();
  });

  it('is absent without canBanlist', () => {
    render(<RowActionsCell {...baseProps({ canBanlist: false })} />);
    expect(screen.queryByRole('button', { name: 'Banear' })).not.toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Banear' })).not.toBeInTheDocument();
  });

  it('is absent on verdicts other than FALTA_PUBLICAR/FALTA_VINCULAR', () => {
    render(
      <RowActionsCell {...baseProps({ row: { ean: 'EAN-3', verdict: 'MAL_PUBLICADO', despublicar: false, tn_matches: [] } })} />
    );
    expect(screen.queryByRole('button', { name: 'Banear' })).not.toBeInTheDocument();
  });

  it('clicking it calls onBanear with the EAN directly, no menu involved', async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<RowActionsCell {...props} />);

    await user.click(screen.getByRole('button', { name: 'Banear' }));
    expect(props.onBanear).toHaveBeenCalledWith('EAN-1');
  });

  it('never appears inside the overflow menu', async () => {
    const user = userEvent.setup();
    const row = {
      ean: 'EAN-5',
      verdict: 'MAL_VINCULADO',
      despublicar: true,
      tn_matches: [{ product_id: 555, tn_admin_url: 'https://tn.example/555', published: true }],
    };
    render(<RowActionsCell {...baseProps({ row })} />);

    await user.click(screen.getByRole('button', { name: /Más acciones/i }));
    expect(screen.queryByRole('menuitem', { name: 'Banear' })).not.toBeInTheDocument();
  });
});

describe('RowActionsCell — overflow menu', () => {
  it('renders no overflow trigger when there are no secondary actions', () => {
    render(
      <RowActionsCell
        {...baseProps({
          row: { ean: 'EAN-4', verdict: 'OK', despublicar: false, tn_matches: [] },
          canBanlist: false,
        })}
      />
    );
    expect(screen.queryByRole('button', { name: /Más acciones/i })).not.toBeInTheDocument();
  });

  it('opens on click and has correct ARIA wiring', async () => {
    const user = userEvent.setup();
    const row = {
      ean: 'EAN-1',
      verdict: 'FALTA_PUBLICAR',
      despublicar: true,
      tn_matches: [{ product_id: 1, tn_admin_url: 'https://tn.example/1', published: true }],
    };
    render(<RowActionsCell {...baseProps({ row })} />);

    const trigger = screen.getByRole('button', { name: /Más acciones para EAN-1/i });
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    await user.click(trigger);

    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const menu = screen.getByRole('menu', { name: /Acciones para EAN-1/i });
    // Editar en TN is no longer in here — it is a visible action now.
    expect(within(menu).getByRole('menuitem', { name: 'Despublicar' })).toBeInTheDocument();
    expect(within(menu).queryByRole('menuitem', { name: /Editar en TN/i })).not.toBeInTheDocument();
  });

  it('shows Editar en TN as a visible link, without opening any menu', async () => {
    // The whole point of moving it out: an operator staring at a
    // mis-published row wants to open it in TN, and that took discovering
    // a three-dot menu first.
    const row = {
      ean: 'EAN-5',
      verdict: 'MAL_VINCULADO',
      despublicar: true,
      tn_matches: [{ product_id: 555, tn_admin_url: 'https://tn.example/555', published: true }],
    };
    render(<RowActionsCell {...baseProps({ row, canBanlist: false })} />);

    // No click on the overflow trigger anywhere in this test.
    const editLink = screen.getByRole('link', { name: /Editar en TN el producto 555/i });
    expect(editLink).toHaveAttribute('href', 'https://tn.example/555');
    expect(editLink).toHaveAttribute('target', '_blank');
    expect(editLink).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('omits the visible Editar en TN link when no match carries a URL', () => {
    const row = {
      ean: 'EAN-5b',
      verdict: 'MAL_VINCULADO',
      despublicar: false,
      tn_matches: [{ product_id: 556, tn_admin_url: null }],
    };
    render(<RowActionsCell {...baseProps({ row, canBanlist: false })} />);

    // A dead button is worse than no button.
    expect(screen.queryByRole('link', { name: /Editar en TN/i })).not.toBeInTheDocument();
  });

  it('clicking Despublicar in the menu hands off to onStartDespublicarConfirm with the resolved product id, not the endpoint directly', async () => {
    const user = userEvent.setup();
    const props = baseProps({
      row: {
        ean: 'EAN-6',
        verdict: 'MAL_VINCULADO',
        despublicar: true,
        tn_matches: [{ product_id: 777, published: true }],
      },
      canBanlist: false,
    });
    render(<RowActionsCell {...props} />);

    await user.click(screen.getByRole('button', { name: /Más acciones/i }));
    await user.click(screen.getByRole('menuitem', { name: 'Despublicar' }));

    expect(props.onStartDespublicarConfirm).toHaveBeenCalledWith(777);
    expect(props.onConfirmDespublicar).not.toHaveBeenCalled();
  });

  it('Escape closes the menu and returns focus to the trigger', async () => {
    const user = userEvent.setup();
    const row = {
      ean: 'EAN-10',
      verdict: 'MAL_VINCULADO',
      despublicar: true,
      tn_matches: [{ product_id: 999, published: true }],
    };
    render(<RowActionsCell {...baseProps({ row, canBanlist: false })} />);

    const trigger = screen.getByRole('button', { name: /Más acciones/i });
    await user.click(trigger);
    expect(screen.getByRole('menu')).toBeInTheDocument();

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('ArrowDown wraps around when the menu holds a single item', async () => {
    // With Editar en TN promoted out, Despublicar is the only secondary
    // action left, so this pins the wrap-around rather than a move to a
    // second item. The keyboard contract must not break just because the
    // menu got shorter.
    const user = userEvent.setup();
    const row = {
      ean: 'EAN-7',
      verdict: 'MAL_VINCULADO',
      despublicar: true,
      tn_matches: [{ product_id: 42, tn_admin_url: 'https://tn.example/42', published: true }],
    };
    render(<RowActionsCell {...baseProps({ row })} />);

    await user.click(screen.getByRole('button', { name: /Más acciones/i }));
    const items = screen.getAllByRole('menuitem');
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveFocus();

    await user.keyboard('{ArrowDown}');
    expect(items[0]).toHaveFocus();
  });
});

describe('RowActionsCell — Despublicar confirm handoff (same shared-state invariant as before)', () => {
  it('renders Confirmar/Cancelar instead of the primary/overflow controls when this row is the confirming one', async () => {
    const user = userEvent.setup();
    const row = {
      ean: 'EAN-8',
      verdict: 'MAL_VINCULADO',
      despublicar: true,
      tn_matches: [{ product_id: 900, published: true }],
    };
    const props = baseProps({ row, confirmingProductId: 900, canBanlist: false });
    render(<RowActionsCell {...props} />);

    expect(screen.queryByRole('button', { name: /Más acciones/i })).not.toBeInTheDocument();
    const confirmBtn = screen.getByRole('button', { name: 'Confirmar' });
    await user.click(confirmBtn);
    expect(props.onConfirmDespublicar).toHaveBeenCalledWith(900);

    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(props.onCancelDespublicarConfirm).toHaveBeenCalled();
  });

  it('does not show this row\'s confirm UI when a DIFFERENT row is the one mid-confirm', () => {
    const row = {
      ean: 'EAN-9',
      verdict: 'MAL_VINCULADO',
      despublicar: true,
      tn_matches: [{ product_id: 901, published: true }],
    };
    render(<RowActionsCell {...baseProps({ row, confirmingProductId: 999 })} />);
    expect(screen.queryByRole('button', { name: 'Confirmar' })).not.toBeInTheDocument();
  });
});

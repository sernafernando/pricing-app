import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
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

  it('renders Revisar instead of Publicar for FALTA_PUBLICAR without canPublish', () => {
    render(<RowActionsCell {...baseProps({ canPublish: false })} />);
    expect(screen.getByRole('button', { name: 'Revisar' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Publicar' })).not.toBeInTheDocument();
  });

  it('renders Vincular for FALTA_VINCULAR', () => {
    render(
      <RowActionsCell
        {...baseProps({ row: { ean: 'EAN-2', verdict: 'FALTA_VINCULAR', despublicar: false, tn_matches: [] } })}
      />
    );
    expect(screen.getByRole('button', { name: 'Vincular' })).toBeInTheDocument();
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
    expect(within(menu).getByRole('menuitem', { name: /Editar en TN/i })).toBeInTheDocument();
  });

  it('lists Despublicar and Editar en TN when applicable, with the link carrying the correct href/target', async () => {
    const user = userEvent.setup();
    const row = {
      ean: 'EAN-5',
      verdict: 'MAL_VINCULADO',
      despublicar: true,
      tn_matches: [{ product_id: 555, tn_admin_url: 'https://tn.example/555', published: true }],
    };
    render(<RowActionsCell {...baseProps({ row, canBanlist: false })} />);

    await user.click(screen.getByRole('button', { name: /Más acciones/i }));

    expect(screen.getByRole('menuitem', { name: 'Despublicar' })).toBeInTheDocument();
    const editLink = screen.getByRole('menuitem', { name: /Editar en TN el producto 555/i });
    expect(editLink).toHaveAttribute('href', 'https://tn.example/555');
    expect(editLink).toHaveAttribute('target', '_blank');
    expect(editLink).toHaveAttribute('rel', 'noopener noreferrer');
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

  it('ArrowDown moves focus to the next menu item', async () => {
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
    expect(items[0]).toHaveFocus();

    await user.keyboard('{ArrowDown}');
    expect(items[1]).toHaveFocus();
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

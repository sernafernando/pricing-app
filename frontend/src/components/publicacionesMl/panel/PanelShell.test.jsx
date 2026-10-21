/**
 * PanelShell: the frame shared by the side panels (header, close, loading,
 * error with retry). PublicationPanel's own tests prove it renders the same.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelShell from './PanelShell';

const renderShell = (props = {}) => render(<PanelShell title="Producto X" onClose={vi.fn()} {...props} />);

describe('header', () => {
  it('shows the title as a heading and the meta under it', () => {
    renderShell({ meta: <span>SKU 123</span> });
    expect(screen.getByRole('heading', { level: 2, name: 'Producto X' })).toBeInTheDocument();
    expect(screen.getByText('SKU 123')).toBeInTheDocument();
  });

  it('calls onClose from the close button', async () => {
    const onClose = vi.fn();
    renderShell({ onClose });
    await userEvent.click(screen.getByRole('button', { name: 'Cerrar panel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('loading', () => {
  it('shows a busy skeleton with its label only while loading', () => {
    const { rerender } = renderShell({ loading: true, loadingLabel: 'Cargando producto' });
    const skeleton = screen.getByRole('status', { name: 'Cargando producto' });
    expect(skeleton).toHaveAttribute('aria-busy', 'true');

    rerender(<PanelShell title="Producto X" onClose={vi.fn()} loadingLabel="Cargando producto" />);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('error', () => {
  it('shows the message and retries from "Reintentar"', async () => {
    const onRetry = vi.fn();
    renderShell({ error: 'No se pudo cargar el producto.', onRetry });
    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo cargar el producto.');
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('shows no alert without an error and no retry without onRetry', () => {
    const { rerender } = renderShell();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    rerender(<PanelShell title="Producto X" onClose={vi.fn()} error="Falló." />);
    expect(screen.getByRole('alert')).toHaveTextContent('Falló.');
    expect(screen.queryByRole('button', { name: 'Reintentar' })).not.toBeInTheDocument();
  });
});

it('renders its children after the header', () => {
  renderShell({ children: <p>Contenido</p> });
  expect(screen.getByText('Contenido')).toBeInTheDocument();
});

/**
 * SheetsNotice: what "Exportar a Sheets" leaves on screen that is not an error. A created sheet is a success banner
 * with a button-like link to it; a cancelled Google popup is a quiet note. Both can be closed.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SheetsNotice from './SheetsNotice';

const URL = 'https://docs.google.com/spreadsheets/d/sid';

describe('SheetsNotice', () => {
  it('a created sheet: a titled status with a link that opens it in a new tab', () => {
    render(<SheetsNotice notice={{ url: URL }} onClose={() => {}} />);
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Hoja creada en Google Sheets');
    expect(status).toHaveTextContent('Mi unidad');
    const link = screen.getByRole('link', { name: 'Abrir en Google Sheets' });
    expect(link).toHaveAttribute('href', URL);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('a note: its text, no link', () => {
    render(<SheetsNotice notice={{ text: 'Exportación cancelada' }} onClose={() => {}} />);
    expect(screen.getByRole('status')).toHaveTextContent('Exportación cancelada');
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('"Cerrar aviso" calls onClose', async () => {
    const onClose = vi.fn();
    render(<SheetsNotice notice={{ url: URL }} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: 'Cerrar aviso' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders nothing without a notice', () => {
    const { container } = render(<SheetsNotice notice={null} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });
});

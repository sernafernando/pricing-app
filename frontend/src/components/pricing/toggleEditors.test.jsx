/**
 * The rebate and web transfer editors keep Tab inside themselves, as Productos does (`useProductosKeyboard.js`): from
 * the last control Tab goes back to the first, and Shift+Tab from the first goes to the last.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RebateEditor, WebTransfEditor } from './toggleEditors';

const props = { saving: false, onSave: vi.fn(), onCancel: vi.fn() };

describe('Tab inside the rebate editor', () => {
  it('wraps from Guardar to the first control and back with Shift+Tab', async () => {
    const user = userEvent.setup();
    render(
      <>
        <RebateEditor {...props} initial={{ participa: true, porcentaje: '5' }} />
        <button type="button">fuera</button>
      </>,
    );
    const participa = screen.getByRole('checkbox', { name: 'Participa' });
    const guardar = screen.getByRole('button', { name: 'Guardar' });

    guardar.focus();
    await user.tab();
    expect(participa).toHaveFocus(); // never the button after the editor

    await user.tab({ shift: true });
    expect(guardar).toHaveFocus();
  });

  it('does not hold Tab while saving (every control is disabled)', async () => {
    const user = userEvent.setup();
    render(
      <>
        <RebateEditor {...props} saving initial={{ participa: true, porcentaje: '5' }} />
        <button type="button">fuera</button>
      </>,
    );
    await user.tab();
    expect(screen.getByRole('button', { name: 'fuera' })).toHaveFocus();
  });

  it('moves through the controls in order in between', async () => {
    const user = userEvent.setup();
    render(<RebateEditor {...props} initial={{ participa: true, porcentaje: '5' }} />);
    screen.getByRole('checkbox', { name: 'Participa' }).focus();
    await user.tab();
    expect(screen.getByRole('textbox', { name: '% de rebate' })).toHaveFocus();
  });
});

describe('Tab inside the web transfer editor', () => {
  it('wraps from Guardar to the first control and back with Shift+Tab', async () => {
    const user = userEvent.setup();
    render(
      <>
        <button type="button">fuera</button>
        <WebTransfEditor {...props} initial={{ participa: true, porcentaje: '3', preservar: false }} />
      </>,
    );
    const participa = screen.getByRole('checkbox', { name: 'Participa' });
    const guardar = screen.getByRole('button', { name: 'Guardar' });

    guardar.focus();
    await user.tab();
    expect(participa).toHaveFocus(); // never the page's next control

    await user.tab({ shift: true });
    expect(guardar).toHaveFocus(); // never the button before the editor
  });
});

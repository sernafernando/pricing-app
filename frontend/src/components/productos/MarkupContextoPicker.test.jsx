import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MarkupContextoPicker from './MarkupContextoPicker';
import { paramDesdeSeleccion, seleccionDesdeParam } from './markupContextos';

const GRUPOS = [
  { value: '57997', ids: ['57997'], label: 'GaussOnline' },
  { value: '2645,471846', ids: ['2645', '471846'], label: 'TP-Link' },
];

/** The picker as Productos wires it: its state lives only in the `markup_contextos` query param. */
function ConParametro({ onParam }) {
  const [param, setParam] = useState(null);
  const { todas, keys } = seleccionDesdeParam(param, GRUPOS);
  return (
    <MarkupContextoPicker
      grupos={GRUPOS}
      todas={todas}
      keys={keys}
      onChange={(sel) => {
        const next = paramDesdeSeleccion(sel.todas, sel.keys, GRUPOS);
        setParam(next);
        onParam(next);
      }}
    />
  );
}

const todas = () => screen.getByRole('checkbox', { name: 'Todas (como hoy)' });

describe('MarkupContextoPicker', () => {
  it('unticking Todas shows the stores to pick, and picking one sends its context', async () => {
    const user = userEvent.setup();
    const params = [];
    render(<ConParametro onParam={(p) => params.push(p)} />);

    await user.click(todas());

    expect(todas()).not.toBeChecked();
    expect(screen.getByText('Elegí al menos una tienda o canal; mientras tanto se ve como Todas.')).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'TP-Link' }));

    expect(screen.getByRole('checkbox', { name: 'TP-Link' })).toBeChecked();
    expect(params.at(-1)).toBe('ml:2645,ml:471846');
  });

  it('unticking the last store keeps the stores open instead of snapping back to Todas', async () => {
    const user = userEvent.setup();
    const params = [];
    render(<ConParametro onParam={(p) => params.push(p)} />);
    await user.click(todas());
    await user.click(screen.getByRole('checkbox', { name: 'GaussOnline' }));

    await user.click(screen.getByRole('checkbox', { name: 'GaussOnline' }));

    expect(todas()).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'GaussOnline' })).not.toBeChecked();
    expect(params.at(-1)).toBeNull(); // nothing picked: the global read, as Todas
  });

  it('ticking Todas again goes back to the global read and hides the stores', async () => {
    const user = userEvent.setup();
    const params = [];
    render(<ConParametro onParam={(p) => params.push(p)} />);
    await user.click(todas());
    await user.click(screen.getByRole('checkbox', { name: 'GaussOnline' }));

    await user.click(todas());

    expect(todas()).toBeChecked();
    expect(screen.queryByRole('checkbox', { name: 'GaussOnline' })).not.toBeInTheDocument();
    expect(params.at(-1)).toBeNull();
  });
});

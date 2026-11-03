import { screen } from '@testing-library/react';
import { LISTS } from './priceWrites';

/**
 * Test helper: where one price of ProductPrices is, to look inside it. A list price (Clásica, 3 cuotas, PVP clásica,
 * …) is its own cell in its plan's row of the one "Precios por plan" table (S2), not the whole row; anything else
 * (Rebate, Mejor oferta, Web transferencia) is its row of the rebate, offer and transfer table.
 */
const PRICE_LABELS = new Set(LISTS.flatMap((list) => list.rows.map((row) => row.label)));

export async function priceOf(label) {
  if (!PRICE_LABELS.has(label)) return screen.findByRole('row', { name: new RegExp(`^${label}\\b`) });
  const table = await screen.findByRole('table', { name: 'Precios por plan' });
  const entry = table.querySelector(`[data-entry-label="${label}"]`);
  if (!entry) throw new Error(`No price "${label}" in the table`);
  return entry;
}

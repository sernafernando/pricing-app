/** What an aporte covers, as the Aportes page names it: its campaign, or the whole Display account of its advertiser. */
export const advertiserLabel = (row) => row.advertiser_name || `Anunciante ${row.advertiser_id}`;

export function scopeOf(row) {
  if (row.campaign_id == null) return { name: `Toda la cuenta Display · ${advertiserLabel(row)}`, detail: 'Cuenta completa' };
  return { name: row.campaign_name || `Campaña ${row.campaign_id}`, detail: String(row.campaign_id) };
}

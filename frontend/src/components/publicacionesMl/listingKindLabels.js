// The words of a publication's listing type (`listing_kind`), shared by its badge and the tooltips that say it in
// text. Kept outside the component file so Fast Refresh keeps working on it.
export const KINDS = {
  clasica: { label: 'Clásica', short: 'C', tone: 'neutral' },
  clasica_cofinanciada: { label: 'Clásica', short: 'C', tone: 'neutral', title: 'Clásica: cuotas cofinanciadas por ML' },
  cuotas_3: { label: '3 cuotas', short: '3', tone: 'info' },
  cuotas_6: { label: '6 cuotas', short: '6', tone: 'success' },
  cuotas_9: { label: '9 cuotas', short: '9', tone: 'warning' },
  cuotas_12: { label: '12 cuotas', short: '12', tone: 'purple' },
};

// ML's other listing types (`listing_type_id`), by the names ML gives them.
const OTHER_TYPES = {
  free: 'Gratuita',
  bronze: 'Bronce',
  silver: 'Plata',
  gold: 'Oro',
  gold_premium: 'Oro Premium',
  gold_pro: 'Premium',
};

// Their short labels, for a parent row's compact Tipo badges ("P 4" for 4 Premium).
const OTHER_SHORT = {
  free: 'G',
  bronze: 'B',
  silver: 'Pl',
  gold: 'O',
  gold_premium: 'OP',
  gold_pro: 'P',
};

/** The short label of `kind` for a compact badge ("C", "3", "P"); an unknown kind keeps its name. */
export function listingKindShort(kind) {
  return KINDS[kind]?.short ?? OTHER_SHORT[kind] ?? listingKindLabel(kind);
}

/** The word the badge shows for `kind`, for a tooltip that has to say it in text. */
export function listingKindLabel(kind) {
  return KINDS[kind]?.label ?? OTHER_TYPES[kind] ?? kind;
}

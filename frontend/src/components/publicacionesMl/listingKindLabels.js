// The words of a publication's listing type (`listing_kind`), shared by its badge and the tooltips that say it in
// text. Kept outside the component file so Fast Refresh keeps working on it.
export const KINDS = {
  clasica: { label: 'Clásica', tone: 'neutral' },
  clasica_cofinanciada: { label: 'Clásica', tone: 'neutral', title: 'Clásica: cuotas cofinanciadas por ML' },
  cuotas_3: { label: '3 cuotas', tone: 'info' },
  cuotas_6: { label: '6 cuotas', tone: 'success' },
  cuotas_9: { label: '9 cuotas', tone: 'warning' },
  cuotas_12: { label: '12 cuotas', tone: 'purple' },
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

/** The word the badge shows for `kind`, for a tooltip that has to say it in text. */
export function listingKindLabel(kind) {
  return KINDS[kind]?.label ?? OTHER_TYPES[kind] ?? kind;
}

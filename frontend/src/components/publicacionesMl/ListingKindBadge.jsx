import StatusPill from '../kit/StatusPill';

/**
 * The listing type of a publication at a glance (owner, 2026-11-02): Clásica, or its installments plan. `kind` is
 * the backend's `listing_kind` (`app/services/ml_publications/listing_kind.py`): Clásica first, then 3, 6, 9 and
 * 12 cuotas, the order both lists sort by. Each one has its own tone. A co-funded Clásica reads as Clásica, and its
 * hint says that ML co-funds the installments; another ML listing type keeps its name. No kind (a backend without
 * the field, a group row) renders nothing.
 */
const KINDS = {
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

function listingKindLabel(kind) {
  return KINDS[kind]?.label ?? OTHER_TYPES[kind] ?? kind;
}

export default function ListingKindBadge({ kind }) {
  if (!kind) return null;
  const known = KINDS[kind];
  const label = listingKindLabel(kind);
  return (
    <StatusPill tone={known?.tone ?? 'neutral'} title={known?.title ?? label}>
      {label}
    </StatusPill>
  );
}

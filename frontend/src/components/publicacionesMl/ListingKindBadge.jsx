import StatusPill from '../kit/StatusPill';
import { KINDS, listingKindLabel } from './listingKindLabels';

/**
 * The listing type of a publication at a glance (owner, 2026-11-02): Clásica, or its installments plan. `kind` is
 * the backend's `listing_kind` (`app/services/ml_publications/listing_kind.py`): Clásica first, then 3, 6, 9 and
 * 12 cuotas, the order both lists sort by. Each one has its own tone. A co-funded Clásica reads as Clásica, and its
 * hint says that ML co-funds the installments; another ML listing type keeps its name. The CSV's Tipo column uses
 * the same words (backend `listing_kind.KIND_LABELS`; a test keeps them equal to `listingKindLabels.js`). No kind (a backend without
 * the field, a group row) renders nothing.
 */
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

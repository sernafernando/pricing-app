import { User, Bot, Sparkles } from 'lucide-react';
import styles from './ProvenanceBadge.module.css';

/**
 * Provenance is the trust mechanism the tickets-ai-triage feature rests on:
 * a maintainer must be able to tell at a glance whether a value was set by a
 * person or proposed by the AI and confirmed. Each vocabulary value gets a
 * visibly distinct badge (icon + color token + label) — never just a
 * presence/absence signal.
 */
const ORIGEN_CONFIG = {
  humano: { label: 'Manual', Icon: User, className: 'humano' },
  ia_confirmada: { label: 'IA confirmada', Icon: Bot, className: 'iaConfirmada' },
  // Written by `run_triage`'s auto-apply branch (TICKETS_TRIAGE_AUTO_APPLY,
  // default True, feat/tickets-triage-aplicar-directo): a threshold-passing
  // value the AI applied with nobody having reviewed it yet.
  ia_auto: { label: 'IA automática', Icon: Sparkles, className: 'iaAuto' },
};

export default function ProvenanceBadge({ origen }) {
  const config = ORIGEN_CONFIG[origen];
  if (!config) return null;

  const { label, Icon, className } = config;
  return (
    <span className={`${styles.badge} ${styles[className]}`} title={label}>
      <Icon size={11} />
      {label}
    </span>
  );
}

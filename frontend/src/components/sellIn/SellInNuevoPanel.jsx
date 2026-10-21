import { useState } from 'react';
import { SegmentedControl } from '../kit';
import SellInBonoPanel from './SellInBonoPanel';
import SellInCreatePanel from './SellInCreatePanel';
import styles from './SellInPanel.module.css';

const MODOS = [
  { value: 'compra', label: 'Por compra' },
  { value: 'bono', label: 'Bono de marca' },
];

/**
 * The "Nuevo sell in" side panel (Stitch `02`/`03`): a "Por compra | Bono de
 * marca" switch over the purchase form or the brand bonus form, in the same
 * panel (no modals). Switching drops what the other form had.
 */
export default function SellInNuevoPanel({ marcas, onCreated, onBonoCreado, onClose }) {
  const [modo, setModo] = useState('compra');
  const modoSwitch = (
    <div className={styles.modoSwitch}>
      <SegmentedControl label="Tipo de sell in" options={MODOS} value={modo} onChange={setModo} />
    </div>
  );
  return modo === 'compra' ? (
    <SellInCreatePanel onCreated={onCreated} onClose={onClose} modoSwitch={modoSwitch} />
  ) : (
    <SellInBonoPanel marcas={marcas} puedeGestionar onSaved={onBonoCreado} onClose={onClose} onVerCompra={() => {}} modoSwitch={modoSwitch} />
  );
}

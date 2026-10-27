/** Catalog seller disposition options for PARA GANAR TOP / ranking. */

export const SELLER_DISPOSITIONS = [
  { value: 'active', label: 'Activo (participa)' },
  { value: 'ignore_participant', label: 'Ignorar como participante' },
  { value: 'hide', label: 'Ocultar' },
  { value: 'exclude_from_top', label: 'No considerar en TOP' },
];

export function dispositionLabel(value) {
  const found = SELLER_DISPOSITIONS.find((item) => item.value === value);
  return found ? found.label : value;
}

import { iconoDeTipo } from '../utils/notificacionFamilias';

export default function NotificacionIcono({ tipo, size = 20 }) {
  const Icono = iconoDeTipo(tipo);
  return <Icono size={size} strokeWidth={2} aria-hidden="true" />;
}

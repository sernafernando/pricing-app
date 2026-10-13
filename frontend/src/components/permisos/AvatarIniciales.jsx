/** Square avatar with the first two initials of a user's name (decorative). */
export default function AvatarIniciales({ nombre, className }) {
  const partes = String(nombre ?? '').trim().split(/\s+/).filter(Boolean);
  const iniciales = partes.slice(0, 2).map((p) => p[0].toUpperCase()).join('') || '?';
  return (
    <span className={className} aria-hidden="true">
      {iniciales}
    </span>
  );
}

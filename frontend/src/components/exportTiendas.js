/**
 * Serializa las tiendas oficiales tildadas a CSV para el backend.
 * `destildadas` es el Set de IDs que el usuario sacó (vacío = todas tildadas,
 * el default, sin importar cuántas tiendas haya).
 * Devuelve null cuando todas o ninguna están tildadas (= sin filtro efectivo).
 */
export const serializarTiendasOficiales = (opciones, destildadas) => {
  const tildadas = opciones.filter((opcion) => !destildadas.has(opcion.id)).map((opcion) => opcion.id);
  if (tildadas.length === 0 || tildadas.length === opciones.length) {
    return null;
  }
  return tildadas.join(','); // cada id de opción ya es una lista CSV de IDs
};


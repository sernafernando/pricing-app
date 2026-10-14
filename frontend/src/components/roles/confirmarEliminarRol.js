/** Asks the user to confirm deleting `rol`. Returns true when confirmed. */
export default function confirmarEliminarRol(rol) {
  return confirm(`¿Eliminar el rol "${rol.nombre}"? Esta accion no se puede deshacer.`);
}

import { useEffect, useState } from 'react';
import { sellOutProgramasAPI } from '../../services/sellOutAPI';

/** Programs per request: the list endpoint's maximum (`page_size` le=200); there are tens of them. */
const PROGRAMAS_PAGE_SIZE = 200;

/**
 * Every sell-out program, active and archived, by name (`GET /sell-out/programas`); empty on failure. A new `version`
 * (an assignment, a program created from a suggestion, "Actualizar") asks them again.
 */
export function useProgramas(enabled, version) {
  const [programas, setProgramas] = useState([]);
  useEffect(() => {
    if (!enabled) return undefined;
    let activo = true;
    sellOutProgramasAPI
      .listar({ page: 1, page_size: PROGRAMAS_PAGE_SIZE })
      .then(({ data }) => activo && setProgramas(data?.items ?? []))
      .catch(() => activo && setProgramas([]));
    return () => {
      activo = false;
    };
  }, [enabled, version]);
  return programas;
}

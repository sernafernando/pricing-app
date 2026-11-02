import { useEffect, useState } from 'react';
import { sellOutProgramasAPI } from '../../services/sellOutAPI';

/** Programs per request: the list endpoint's maximum (`page_size` le=200). */
const PROGRAMAS_PAGE_SIZE = 200;

/**
 * Every sell-out program, active and archived, by name (`GET /sell-out/programas`, page by page up to `total`, so
 * the Programa filter and the assign dialog never miss one); empty on failure. A new `version`
 * (an assignment, a program created from a suggestion, "Actualizar") asks them again.
 */
export function useProgramas(enabled, version) {
  const [programas, setProgramas] = useState([]);
  useEffect(() => {
    if (!enabled) return undefined;
    let activo = true;
    (async () => {
      const todos = [];
      for (let page = 1; ; page += 1) {
        const { data } = await sellOutProgramasAPI.listar({ page, page_size: PROGRAMAS_PAGE_SIZE });
        todos.push(...(data?.items ?? []));
        if (!data?.items?.length || todos.length >= data.total) break;
      }
      return todos;
    })()
      .then((todos) => activo && setProgramas(todos))
      .catch(() => activo && setProgramas([]));
    return () => {
      activo = false;
    };
  }, [enabled, version]);
  return programas;
}

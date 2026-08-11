/**
 * Hook para generación de documentos PDF con pdfme.
 * Carga templates por contexto y genera PDFs en el browser.
 */
import { useState, useCallback } from 'react';
import { documentTemplatesAPI } from '../services/api';
import { mapEntityToInputs } from '../utils/contextDataMappers';

/**
 * @param {string} contexto - Contexto del módulo (pedidos, rrhh, envios, etc.)
 */
export function useDocumentGenerator(contexto) {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  /**
   * Carga la lista de templates activos para este contexto.
   */
  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await documentTemplatesAPI.listar({
        contexto,
        activo: true,
      });
      setTemplates(data);
    } catch {
      setError('Error al cargar templates');
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, [contexto]);

  /**
   * Genera un PDF a partir de un template y datos de entidad.
   * Abre el PDF en una nueva pestaña del browser.
   *
   * `entityData` acepta UNA entidad o un ARRAY de entidades. pdfme genera un
   * juego de páginas por cada elemento de `inputs`, así que N entidades
   * producen UN PDF de N juegos de páginas. Pasar una sola entidad se comporta
   * exactamente igual que antes (un único registro).
   *
   * @param {number} templateId - ID del template a usar
   * @param {object|object[]} entityData - Datos crudos de la/s entidad/es
   * @param {object} [options] - Opciones de generación
   * @param {function} [options.transformTemplate] - Recibe el template_json de
   *   la API y devuelve el template a usar. DEBE ser puro (no mutar la
   *   entrada). Sirve para variantes de layout, p.ej. sacar una columna.
   */
  const generatePdf = async (templateId, entityData, options = {}) => {
    const { transformTemplate } = options;
    setGenerating(true);
    setError(null);
    try {
      const entities = Array.isArray(entityData) ? entityData : [entityData];
      if (entities.length === 0) {
        setError('No hay datos para generar el documento');
        return;
      }

      // 1. Obtener template completo (con template_json)
      const { data: templateData } = await documentTemplatesAPI.obtener(templateId);
      const sourceTemplate = transformTemplate
        ? transformTemplate(templateData.template_json)
        : templateData.template_json;

      // 2. Clonar antes de normalizar: el paso 3 escribe sobre los campos de
      //    tabla y el template de la API no es nuestro para mutarlo.
      const pdfmeTemplate = structuredClone(sourceTemplate);

      // 3. Extraer defaults del template (imágenes, labels estáticos, etc.)
      //    pdfme sobreescribe TODO con inputs — si un campo no está en inputs,
      //    se pierde el content del template. Mergeamos defaults + datos dinámicos.
      const templateDefaults = {};
      const schemas = pdfmeTemplate.schemas || [];
      for (const page of schemas) {
        for (const field of page) {
          if (field.content !== undefined && field.content !== '') {
            templateDefaults[field.name] = field.content;
          }
          // pdfme v5 requiere ciertos campos en tablas — asegurar que existan
          if (field.type === 'table') {
            if (!field.columnStyles) field.columnStyles = {};

            // Asegurar que headStyles y bodyStyles tengan padding y borderWidth como objetos
            const defaultPadding = { top: 5, right: 5, bottom: 5, left: 5 };
            const defaultBorderWidth = { top: 0.1, right: 0.1, bottom: 0.1, left: 0.1 };

            for (const key of ['headStyles', 'bodyStyles']) {
              const s = field[key];
              if (!s) continue;
              if (s.padding && typeof s.padding !== 'object') {
                const v = s.padding;
                s.padding = { top: v, right: v, bottom: v, left: v };
              }
              if (!s.padding) s.padding = defaultPadding;
              if (s.borderWidth !== undefined && typeof s.borderWidth !== 'object') {
                const v = s.borderWidth;
                s.borderWidth = { top: v, right: v, bottom: v, left: v };
              }
              if (s.borderWidth === undefined) s.borderWidth = defaultBorderWidth;
            }
          }
        }
      }

      // 4. Un registro de inputs por entidad, con los defaults mergeados en
      //    CADA uno (pdfme los pisa por registro, no por template).
      const inputs = entities.map((entity) => ({
        ...templateDefaults,
        ...mapEntityToInputs(contexto, entity),
      }));

      // 5. Dynamic import de pdfme generator + fonts (lazy load)
      const { generate } = await import('@pdfme/generator');
      const { plugins } = await import('../utils/pdfmePlugins');
      const { getFont } = await import('../utils/pdfmeFonts');

      // 6. Generar PDF (pdfme v5)
      const pdf = await generate({
        template: pdfmeTemplate,
        inputs,
        plugins,
        options: { font: await getFont() },
      });

      // 7. Abrir en nueva pestaña
      const blob = new Blob([pdf.buffer], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');

      // Cleanup después de un delay (para que el browser abra la pestaña)
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (err) {
      const message = err?.response?.data?.detail || err?.message || 'Error al generar PDF';
      setError(message);
    } finally {
      setGenerating(false);
    }
  };

  return {
    templates,
    loading,
    generating,
    error,
    fetchTemplates,
    generatePdf,
  };
}

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
   * @param {number} templateId - ID del template a usar
   * @param {object} entityData - Datos crudos de la entidad (del state de la página)
   */
  const generatePdf = async (templateId, entityData) => {
    setGenerating(true);
    setError(null);
    try {
      // 1. Obtener template completo (con template_json)
      const { data: templateData } = await documentTemplatesAPI.obtener(templateId);
      const pdfmeTemplate = templateData.template_json;

      // 2. Mapear datos de entidad a inputs pdfme
      const mappedInputs = mapEntityToInputs(contexto, entityData);

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
          // pdfme v5 requiere columnStyles en tablas — asegurar que exista
          if (field.type === 'table' && !field.columnStyles) {
            field.columnStyles = {};
          }
        }
      }
      const inputs = { ...templateDefaults, ...mappedInputs };

      // 4. Dynamic import de pdfme generator + fonts (lazy load)
      const { generate } = await import('@pdfme/generator');
      const { plugins } = await import('../utils/pdfmePlugins');
      const { getFont } = await import('../utils/pdfmeFonts');

      // 5. Generar PDF (pdfme v5)
      const pdf = await generate({
        template: pdfmeTemplate,
        inputs: [inputs],
        plugins,
        options: { font: await getFont() },
      });

      // 6. Abrir en nueva pestaña
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

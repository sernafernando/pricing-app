/**
 * Zebra Browser Print integration.
 *
 * Zebra Browser Print es un servicio local que corre en la PC del usuario
 * y permite enviar ZPL directamente a impresoras Zebra desde el navegador.
 *
 * Flujo:
 * 1. Intenta descubrir impresoras vía GET http://localhost:9100/available
 * 2. Si encuentra una, envía el ZPL vía POST http://localhost:9100/write
 * 3. Si no puede conectar o no hay impresoras, descarga el .zpl como archivo
 */

const ZEBRA_BASE_URL = 'http://localhost:9100';
const ZEBRA_TIMEOUT = 3000;

/**
 * Descubre impresoras Zebra disponibles vía Browser Print.
 *
 * @returns {Promise<object|null>} Primera impresora encontrada o null
 */
const discoverPrinter = async () => {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), ZEBRA_TIMEOUT);

    const response = await fetch(`${ZEBRA_BASE_URL}/available`, {
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (!response.ok) return null;

    const data = await response.json();

    // Browser Print devuelve { printer: [...] } o { deviceList: [...] }
    const printers = data.printer || data.deviceList || [];
    if (printers.length === 0) return null;

    // Devolver la primera impresora (generalmente la default)
    return printers[0];
  } catch {
    // Zebra Browser Print no está corriendo o timeout
    return null;
  }
};

/**
 * Envía ZPL a una impresora Zebra vía Browser Print.
 *
 * @param {string} zpl - Contenido ZPL a imprimir
 * @param {object} printer - Objeto impresora de discoverPrinter()
 * @returns {Promise<boolean>} true si se envió correctamente
 */
const sendToZebra = async (zpl, printer) => {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    const deviceName = typeof printer === 'string' ? printer : (printer.name || printer.uid || '');

    const response = await fetch(`${ZEBRA_BASE_URL}/write`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: `${deviceName ? `{"device":"${deviceName}"}` + '\n' : ''}${zpl}`,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    return response.ok;
  } catch {
    return false;
  }
};

/**
 * Descarga el contenido ZPL como archivo .zpl.
 *
 * @param {string} zpl - Contenido ZPL
 * @param {string} shippingId - ID del envío (para el nombre del archivo)
 */
const downloadAsFile = (zpl, shippingId) => {
  const blob = new Blob([zpl], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `etiqueta_${shippingId}.zpl`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

/**
 * Imprime ZPL: intenta Zebra Browser Print, si falla descarga .zpl.
 *
 * @param {string} zpl - Contenido ZPL a imprimir
 * @param {string} shippingId - ID del envío
 * @returns {Promise<{method: 'zebra'|'download', success: boolean}>}
 */
export const printZpl = async (zpl, shippingId) => {
  // Intentar impresión directa con Zebra Browser Print
  const printer = await discoverPrinter();

  if (printer) {
    const sent = await sendToZebra(zpl, printer);
    if (sent) {
      return { method: 'zebra', success: true };
    }
  }

  // Fallback: descargar como archivo .zpl
  downloadAsFile(zpl, shippingId);
  return { method: 'download', success: true };
};

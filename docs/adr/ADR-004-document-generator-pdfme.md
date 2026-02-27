# ADR-004 - Generador de Documentos con pdfme

Status: Accepted
Date: 2026-02-25

## Context

Se necesita un sistema para generar documentos imprimibles (remitos, recibos de envío, etc.) a partir de los datos existentes del sistema. El requerimiento clave es que usuarios con permiso puedan **diseñar visualmente** los templates (layout, datos dinámicos, imágenes, texto libre) y guardarlos como presets reutilizables.

Esto equivale a un "report builder" embebido en la aplicación.

## Options Evaluated

### Option A: Templates HTML codificados + `@media print`

- **Pro:** Cero dependencias nuevas, Ctrl+P nativo del browser.
- **Contra:** Cero personalización por parte del usuario. Cada template nuevo requiere código. No cumple el requerimiento.
- **Descartado:** No permite diseño visual por el usuario.

### Option B: @react-pdf/renderer

- **Licencia:** MIT, 100% gratis.
- **Pro:** Genera PDFs con componentes React, buen control de layout.
- **Contra:** Los templates son código JSX, no JSON. No tiene designer visual. El usuario no puede diseñar nada sin un desarrollador.
- **Descartado:** No cumple el requerimiento de diseño visual por el usuario.

### Option C: jsPDF + html2pdf.js

- **Licencia:** MIT.
- **Pro:** Maduro, mucha documentación.
- **Contra:** Convierte HTML a PDF pixel-based (rasteriza). No tiene designer, no tiene schemas, no tiene binding de datos. Calidad de PDF inferior.
- **Descartado:** No cumple ningún requerimiento.

### Option D: pdfme (elegido)

- **Licencia:** MIT, 100% gratis, para siempre.
- **GitHub:** 4.2k stars, 428 forks, 51 contributors, mantenido activamente (último release Nov 2025).
- **Stack:** TypeScript + React.
- **Designer visual:** SI — componente `Designer` WYSIWYG con drag & drop incluido.
- **Viewer/Preview:** SI — componente `Viewer` para previsualización con datos reales.
- **Generador PDF:** SI — `generate()` funciona en browser y Node.js.
- **Templates:** JSON puro, guardable en base de datos (JSONB en PostgreSQL).
- **Plugins:** `text`, `image`, `barcodes` (QR, Code128, etc.), `table`.
- **Fuentes custom:** SI.
- **Placeholders dinámicos:** SI — `{variable}` con reemplazo automático.
- **Multi-página:** SI.
- **Internacionalización:** SI — soporta `lang: 'es'`.

## Decision

Usar **pdfme** (paquetes `@pdfme/common`, `@pdfme/ui`, `@pdfme/generator`, `@pdfme/schemas`) para implementar el sistema de generación de documentos.

Los templates se almacenan como JSON en PostgreSQL (columna JSONB) y se gestionan con CRUD estándar. La generación de PDF ocurre 100% en el frontend (browser), sin carga adicional al backend.

## Consequences

### Positivas

- El usuario diseña templates sin intervención de desarrollo.
- Templates son JSON: versionables, exportables, importables, copiables.
- Generación de PDF en browser: cero carga al servidor.
- Librería MIT sin costo, con comunidad activa.
- Se integra naturalmente con el stack actual (React + Vite).

### Negativas

- Nueva dependencia en frontend (~4 paquetes npm).
- El Designer de pdfme usa Ant Design internamente (puede agregar peso al bundle).
- Templates complejos requieren que el usuario entienda el concepto de variables/placeholders.

### Riesgos

- pdfme es un proyecto relativamente joven (v5.x). Si el proyecto muere, los templates JSON siguen siendo usables con código custom.
- El Designer no soporta expresiones complejas (ej: `IF stock > 0 THEN ...`). Para lógica condicional, se pre-procesan los datos en el backend antes de enviarlos al frontend.

## Follow-up

- Implementar según `docs/FEATURE-DOCUMENT-GENERATOR.md`.
- Crear permiso `documentos.disenar` para acceso al Designer.
- Crear permiso `documentos.imprimir` para uso de presets.

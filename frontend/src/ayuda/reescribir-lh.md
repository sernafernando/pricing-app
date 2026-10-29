# Reescribir ^LH

Área: Operaciones
Ruta: Operaciones → Reescribir ^LH
Permiso: Pedile a un administrador el permiso para reescribir etiquetas ^LH.

## Para qué sirve

Corrige el offset vertical (^LH y) de etiquetas ZPL de Mercado Libre. Subís un archivo de etiquetas y se descarga el archivo corregido.

## Cómo se usa

Arriba dice **Reescribir ^LH** y aclara que corrige el offset vertical de etiquetas ZPL de Mercado Libre.

Elegí un archivo (**Seleccionar archivo .txt o .zip**), acepta .txt o .zip. Definí el **Offset Y (^LH y)** (por defecto 450). Usá **Procesar y descargar**. Mientras trabaja dice **Procesando...**.

Al terminar muestra cuántas etiquetas se detectaron y cuántas se corrigieron, y descarga el archivo. Si los valores ^LH eran heterogéneos, avisa que se normalizaron. Si hay una advertencia adicional, la muestra.

Si falta el archivo o el offset no es válido, muestra un error.

## Filtros y columnas

Sin filtros.

## Botones y acciones

- **Procesar y descargar**: procesa y descarga el archivo corregido.

## Preguntas frecuentes

**¿Qué archivos acepta?**
Archivos .txt (ZPL) o .zip con un archivo Envio-*.txt.

**¿Qué valor por defecto tiene el offset?**
450.

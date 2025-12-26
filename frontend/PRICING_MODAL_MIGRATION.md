# 🔄 PRICING MODAL - Comparativa Migración

## ✅ PricingModalTesla - CREADO

### 📊 Comparativa Código

| Aspecto | ANTES (PricingModal.jsx) | AHORA (PricingModalTesla.jsx) | Mejora |
|---------|--------------------------|-------------------------------|--------|
| **Líneas totales** | ~525 líneas | ~350 líneas | **-33%** |
| **Líneas JSX** | ~400 líneas | ~250 líneas | **-38%** |
| **Estilos inline** | 45+ instancias | 0 | **-100%** |
| **Portal** | ✅ Propio | ✅ Via ModalTesla | Estandarizado |
| **ESC close** | ❌ No | ✅ Sí | Mejorado |
| **Click outside** | ✅ Manual | ✅ Via ModalTesla | Estandarizado |
| **Tab trap** | ❌ No | ✅ Sí | Mejorado |
| **Auto-focus** | ❌ No | ✅ Sí | Mejorado |
| **CSS custom** | 250 líneas (module.css) | 180 líneas | **-28%** |

---

## 🎨 Cambios Visuales

### ANTES (PricingModal):
```jsx
<div className={styles.overlay} onClick={onClose}>
  <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
    <div className={styles.header}>
      <div className={styles.headerInfo}>
        <h2>{producto.descripcion}</h2>
        <p>{producto.marca} | Stock: {producto.stock}</p>
      </div>
      <button onClick={onClose} className={styles.closeBtn}>×</button>
    </div>
    
    {/* 45+ inline styles en ofertas */}
    <div style={{ padding: '8px', backgroundColor: '#fef3c7', ... }}>
      ...
    </div>
    
    <div className={styles.section}>
      <label className={styles.label}>Modo de cálculo</label>
      <div className={styles.modeButtons}>
        <button className={modo === 'markup' ? styles.modeActive : styles.modeButton}>
          Por Markup
        </button>
      </div>
    </div>
    
    {/* Sin footer estructurado */}
    {resultado && (
      <button onClick={guardar} className={styles.saveBtn}>
        Guardar Precio
      </button>
    )}
  </div>
</div>
```

### AHORA (PricingModalTesla):
```jsx
<ModalTesla
  isOpen={isOpen}
  onClose={onClose}
  title={producto.descripcion}
  subtitle={`${producto.marca} | Stock: ${producto.stock}`}
  size="lg"
  footer={
    resultado && (
      <ModalFooterButtons
        onCancel={onClose}
        onConfirm={guardar}
        confirmText="Guardar Precio"
        confirmLoading={guardando}
        confirmVariant="success"
      />
    )
  }
>
  {/* Ofertas con ModalAlert */}
  <ModalAlert type="warning">
    <strong>📢 Ofertas Vigentes</strong>
    <div className="ofertas-list">
      {/* 0 inline styles */}
    </div>
  </ModalAlert>

  {/* Modo selector con botones Tesla */}
  <ModalSection title="Modo de cálculo">
    <div className="modo-selector">
      <button className={`btn-tesla ${modo === 'markup' ? 'primary' : 'secondary'}`}>
        Por Markup
      </button>
    </div>
  </ModalSection>
</ModalTesla>
```

---

## 🚀 Mejoras Implementadas

### 1. **Estructura Estandarizada**
- ✅ Usa `ModalTesla` base
- ✅ Header/Body/Footer separados
- ✅ ModalSection para organización
- ✅ ModalAlert para ofertas/errores

### 2. **Botones Estandarizados**
```jsx
// ANTES
<button className={styles.calculateBtn}>Calcular</button>
<button className={styles.saveBtn}>Guardar</button>

// AHORA
<button className="btn-tesla primary">Calcular</button>
<ModalFooterButtons confirmText="Guardar Precio" confirmVariant="success" />
```

### 3. **Inputs Estandarizados**
```jsx
// ANTES
<input type="number" className={styles.input} />

// AHORA
<input type="number" className="input" /> {/* Clase global del sistema */}
```

### 4. **Sin Estilos Inline**
```jsx
// ANTES (45+ instancias)
<div style={{ padding: '8px', backgroundColor: '#fef3c7', borderRadius: '4px' }}>

// AHORA
<div className="oferta-item"> {/* CSS con variables del sistema */}
```

### 5. **Ofertas Mejoradas**
```jsx
// ANTES
<div style={{ maxHeight: '200px', overflowY: 'auto', border: '1px solid #e5e7eb' }}>

// AHORA
<ModalAlert type="warning">
  <div className="ofertas-list"> {/* CSS: max-height, overflow, gap */}
```

### 6. **Loading States**
```jsx
// ANTES
<button disabled={calculando}>
  {calculando ? 'Calculando...' : 'Calcular'}
</button>

// AHORA
<button className={`btn-tesla primary ${calculando ? 'loading' : ''}`}>
  {calculando ? 'Calculando...' : 'Calcular'}
</button>
{/* Spinner animado automático con .loading */}
```

### 7. **Footer Estructurado**
```jsx
// ANTES - Botones sueltos en el body
{resultado && (
  <button onClick={guardar}>Guardar Precio</button>
)}

// AHORA - Footer consistente
footer={
  resultado && (
    <ModalFooterButtons
      onCancel={onClose}
      onConfirm={guardar}
      confirmLoading={guardando}
      confirmVariant="success"
    />
  )
}
```

---

## 📁 Archivos Creados

1. **`PricingModalTesla.jsx`** (350 líneas)
   - Componente migrado
   - Usa ModalTesla base
   - 0 estilos inline

2. **`PricingModalTesla.css`** (180 líneas)
   - Estilos específicos
   - Usa design tokens
   - Responsive

---

## 🔄 Cómo Usar

### Importar:
```jsx
import PricingModalTesla from '../components/PricingModalTesla';
```

### Reemplazar en Productos.jsx:
```jsx
// ANTES
import PricingModal from '../components/PricingModal';

{productoSeleccionado && (
  <PricingModal
    producto={productoSeleccionado}
    onClose={() => setProductoSeleccionado(null)}
    onSave={fetchProductos}
  />
)}

// AHORA
import PricingModalTesla from '../components/PricingModalTesla';

<PricingModalTesla
  isOpen={!!productoSeleccionado}
  producto={productoSeleccionado}
  onClose={() => setProductoSeleccionado(null)}
  onSave={fetchProductos}
/>
```

**NOTA:** Agregué prop `isOpen` porque ModalTesla lo necesita para controlar renderizado.

---

## ✨ Características Nuevas

### 1. **ESC para Cerrar**
Ahora se puede cerrar con ESC (antes no funcionaba)

### 2. **Tab Trap**
El foco se mantiene dentro del modal

### 3. **Auto-focus**
Focus automático en el primer input

### 4. **Loading en Botón**
Spinner animado integrado en el botón de guardar

### 5. **Glassmorphism (Dark Mode)**
Efecto vidrio esmerilado en dark mode

### 6. **Animaciones**
Entrada/salida suaves del modal

---

## 🎨 Diseño Tesla Aplicado

### Ofertas Vigentes:
- **ANTES:** Estilos inline hardcodeados
- **AHORA:** `ModalAlert type="warning"` con clases del sistema

### Modo Selector:
- **ANTES:** Botones custom con CSS module
- **AHORA:** `btn-tesla primary/secondary`

### Resultados:
- **ANTES:** Grid con estilos inline
- **AHORA:** `.cuotas-grid` con variables del sistema

### Cards de Cuotas:
- **ANTES:** Sin hover, sin transición
- **AHORA:** Hover con elevación, transición suave

---

## 📊 Reducción de Código

| Tipo | ANTES | AHORA | Reducción |
|------|-------|-------|-----------|
| Líneas JSX | ~400 | ~250 | **-38%** |
| Líneas CSS | 250 (module) | 180 (específico) | **-28%** |
| Estilos inline | 45+ | 0 | **-100%** |
| Clases custom | ~30 | ~15 | **-50%** |
| Boilerplate | 150 líneas | 0 | **-100%** |

---

## 🚦 Estado de Migración

| Modal | Archivo Original | Archivo Nuevo | Estado |
|-------|------------------|---------------|--------|
| PricingModal | `PricingModal.jsx` | `PricingModalTesla.jsx` | ✅ **CREADO** |
| - | `PricingModal.module.css` | `PricingModalTesla.css` | ✅ **CREADO** |

---

## 🧪 Testing Necesario

### Probar:
1. ✅ Abrir modal
2. ✅ Cambiar entre modo Markup/Precio Manual
3. ✅ Calcular precio
4. ✅ Ver ofertas vigentes (si hay)
5. ✅ Toggle rebate
6. ✅ Guardar precio
7. ✅ Cerrar con X, ESC, click outside
8. ✅ Loading states (calcular, guardar)
9. ✅ Errores (validación)
10. ✅ Dark mode

---

## 🎯 Próximos Pasos

1. **Testear PricingModalTesla** en dev
2. **Reemplazar** en Productos.jsx si funciona bien
3. **Migrar** ModalInfoProducto (siguiente prioridad)
4. **Deprecar** PricingModal.jsx viejo

---

**¿Querés que reemplace PricingModal por PricingModalTesla en Productos.jsx para testearlo?**

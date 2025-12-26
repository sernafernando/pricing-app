# 🪟 MODALS TESLA - Guía de Uso

## ✅ Sistema de Modales Implementado

### 🎨 Componente Base

```jsx
import ModalTesla from '../components/ModalTesla';

<ModalTesla
  isOpen={isOpen}
  onClose={handleClose}
  title="Título del Modal"
  subtitle="Subtítulo opcional"
  size="md"
  footer={<FooterButtons />}
>
  {/* Contenido aquí */}
</ModalTesla>
```

---

## 📏 Tamaños Disponibles

```jsx
<ModalTesla size="xs">     {/* 400px - Confirmaciones */}
<ModalTesla size="sm">     {/* 500px - Formularios simples */}
<ModalTesla size="md">     {/* 672px - Default */}
<ModalTesla size="lg">     {/* 896px - Datos complejos */}
<ModalTesla size="xl">     {/* 1152px - Tablas grandes */}
<ModalTesla size="full">   {/* 95vw - Fullscreen */}
```

---

## 🎯 Props Principales

| Prop | Tipo | Default | Descripción |
|------|------|---------|-------------|
| `isOpen` | boolean | - | **Requerido** - Estado del modal |
| `onClose` | function | - | **Requerido** - Callback al cerrar |
| `title` | string | - | **Requerido** - Título del modal |
| `subtitle` | string | - | Subtítulo opcional |
| `children` | node | - | Contenido del modal |
| `footer` | node | - | Footer con botones |
| `size` | string | 'md' | xs, sm, md, lg, xl, full |
| `showCloseButton` | boolean | true | Mostrar botón X |
| `closeOnOverlay` | boolean | true | Cerrar al click fuera |
| `closeOnEsc` | boolean | true | Cerrar con ESC |
| `className` | string | '' | Clase adicional |
| `bodyClassName` | string | '' | Clase para body |
| `tabs` | array | - | Array de tabs (ver abajo) |
| `activeTab` | string | - | Tab activo |
| `onTabChange` | function | - | Callback cambio de tab |

---

## 🔧 Características Incluidas

### ✅ Portal a document.body
```jsx
// Se renderiza fuera del DOM padre
createPortal(modalContent, document.body)
```

### ✅ ESC para cerrar
```jsx
<ModalTesla closeOnEsc={true} />  // Default
<ModalTesla closeOnEsc={false} /> // Deshabilitar
```

### ✅ Click outside para cerrar
```jsx
<ModalTesla closeOnOverlay={true} />  // Default
<ModalTesla closeOnOverlay={false} /> // Deshabilitar
```

### ✅ Tab trap (mantiene foco)
Automático - No permite salir del modal con Tab

### ✅ Auto-focus
Focus automático en el primer elemento focuseable

### ✅ Prevención de scroll
El body no scrollea mientras el modal está abierto

---

## 📑 Modales con Tabs

```jsx
const tabs = [
  { id: 'info', label: 'Información' },
  { id: 'ml', label: 'MercadoLibre', badge: '3' },
  { id: 'ventas', label: 'Ventas' },
  { id: 'config', label: 'Configuración', disabled: true }
];

<ModalTesla
  isOpen={isOpen}
  onClose={onClose}
  title="Detalle Producto"
  tabs={tabs}
  activeTab={activeTab}
  onTabChange={setActiveTab}
>
  {activeTab === 'info' && <TabInfo />}
  {activeTab === 'ml' && <TabML />}
  {activeTab === 'ventas' && <TabVentas />}
</ModalTesla>
```

---

## 🔨 Componentes Helper

### ModalSection
```jsx
import { ModalSection } from '../components/ModalTesla';

<ModalSection title="Datos del Producto">
  <p>Código: 123456</p>
  <p>Stock: 10</p>
</ModalSection>
```

### ModalDivider
```jsx
import { ModalDivider } from '../components/ModalTesla';

<ModalSection title="Sección 1">...</ModalSection>
<ModalDivider />
<ModalSection title="Sección 2">...</ModalSection>
```

### ModalAlert
```jsx
import { ModalAlert } from '../components/ModalTesla';

<ModalAlert type="info">Información importante</ModalAlert>
<ModalAlert type="warning">Advertencia</ModalAlert>
<ModalAlert type="error">Error crítico</ModalAlert>
<ModalAlert type="success">Operación exitosa</ModalAlert>
```

### ModalLoading
```jsx
import { ModalLoading } from '../components/ModalTesla';

{loading && <ModalLoading message="Calculando precios..." />}
```

### ModalFooterButtons
```jsx
import { ModalFooterButtons } from '../components/ModalTesla';

<ModalTesla
  footer={
    <ModalFooterButtons
      onCancel={onClose}
      onConfirm={handleSave}
      confirmText="Guardar"
      cancelText="Cancelar"
      confirmLoading={saving}
      confirmDisabled={!isValid}
      confirmVariant="primary" // primary, success, danger
    />
  }
>
  ...
</ModalTesla>
```

---

## 📝 Ejemplos Completos

### Ejemplo 1: Modal Simple
```jsx
import ModalTesla, { ModalFooterButtons } from '../components/ModalTesla';

function ConfirmacionModal({ isOpen, onClose, onConfirm }) {
  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title="¿Confirmar acción?"
      size="sm"
      footer={
        <ModalFooterButtons
          onCancel={onClose}
          onConfirm={onConfirm}
          confirmText="Confirmar"
          confirmVariant="danger"
        />
      }
    >
      <p>Esta acción no se puede deshacer.</p>
    </ModalTesla>
  );
}
```

### Ejemplo 2: Modal con Formulario
```jsx
import ModalTesla, { ModalSection, ModalFooterButtons } from '../components/ModalTesla';

function FormularioModal({ isOpen, onClose, onSave }) {
  const [data, setData] = useState({});
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    await onSave(data);
    setSaving(false);
    onClose();
  };

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title="Editar Producto"
      subtitle="Código: 123456"
      size="md"
      footer={
        <ModalFooterButtons
          onCancel={onClose}
          onConfirm={handleSave}
          confirmText="Guardar Cambios"
          confirmLoading={saving}
        />
      }
    >
      <ModalSection title="Datos Principales">
        <input type="text" className="input" placeholder="Nombre" />
        <input type="number" className="input" placeholder="Precio" />
      </ModalSection>

      <ModalSection title="Stock">
        <input type="number" className="input" placeholder="Cantidad" />
      </ModalSection>
    </ModalTesla>
  );
}
```

### Ejemplo 3: Modal con Tabs
```jsx
import ModalTesla from '../components/ModalTesla';

function InfoProductoModal({ isOpen, onClose, producto }) {
  const [activeTab, setActiveTab] = useState('info');

  const tabs = [
    { id: 'info', label: 'Información' },
    { id: 'ml', label: 'MercadoLibre', badge: producto.publicaciones },
    { id: 'ventas', label: 'Ventas' }
  ];

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title={producto.descripcion}
      subtitle={`${producto.marca} | Stock: ${producto.stock}`}
      size="lg"
      tabs={tabs}
      activeTab={activeTab}
      onTabChange={setActiveTab}
    >
      {activeTab === 'info' && <TabInfo data={producto} />}
      {activeTab === 'ml' && <TabML data={producto} />}
      {activeTab === 'ventas' && <TabVentas data={producto} />}
    </ModalTesla>
  );
}
```

### Ejemplo 4: Modal con Loading
```jsx
import ModalTesla, { ModalLoading, ModalSection } from '../components/ModalTesla';

function CalcularPrecioModal({ isOpen, onClose, producto }) {
  const [calculando, setCalculando] = useState(false);
  const [resultado, setResultado] = useState(null);

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title="Calcular Precio"
      size="md"
    >
      {calculando ? (
        <ModalLoading message="Calculando precios..." />
      ) : resultado ? (
        <ModalSection title="Resultado">
          <p>Precio calculado: ${resultado.precio}</p>
          <p>Markup: {resultado.markup}%</p>
        </ModalSection>
      ) : (
        <p>Presiona calcular para comenzar</p>
      )}
      
      <div className="btn-group-tesla right">
        <button className="btn-tesla secondary" onClick={onClose}>
          Cerrar
        </button>
        <button 
          className="btn-tesla primary" 
          onClick={() => calcular()}
          disabled={calculando}
        >
          Calcular
        </button>
      </div>
    </ModalTesla>
  );
}
```

---

## 🎨 Personalización de Estilos

### Clase custom en modal
```jsx
<ModalTesla className="mi-modal-custom">
  ...
</ModalTesla>
```

```css
.mi-modal-custom {
  /* Estilos custom */
}
```

### Clase custom en body
```jsx
<ModalTesla bodyClassName="compact">
  ...
</ModalTesla>
```

---

## 🔄 Migración desde Modales Antiguos

### ANTES (PricingModal viejo):
```jsx
// PricingModal.jsx
<div className={styles.overlay} onClick={onClose}>
  <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
    <div className={styles.header}>
      <h2>{producto.descripcion}</h2>
      <button onClick={onClose} className={styles.closeBtn}>×</button>
    </div>
    
    <div className={styles.body}>
      {/* contenido */}
    </div>
    
    <div className={styles.footer}>
      <button onClick={onClose}>Cancelar</button>
      <button onClick={handleSave}>Guardar</button>
    </div>
  </div>
</div>
```

### DESPUÉS (Con ModalTesla):
```jsx
import ModalTesla, { ModalFooterButtons } from '../components/ModalTesla';

<ModalTesla
  isOpen={isOpen}
  onClose={onClose}
  title={producto.descripcion}
  footer={
    <ModalFooterButtons
      onCancel={onClose}
      onConfirm={handleSave}
    />
  }
>
  {/* contenido */}
</ModalTesla>
```

**Beneficios:**
- ✅ Portal automático
- ✅ ESC + click outside
- ✅ Tab trap
- ✅ Auto-focus
- ✅ -70% código boilerplate

---

## 📊 Estado de Migración

| Modal | Estado | Prioridad |
|-------|--------|-----------|
| ModalTesla (base) | ✅ Creado | - |
| PricingModal | ⏳ Siguiente | Alta |
| ModalInfoProducto | ⏳ Pendiente | Alta |
| ExportModal | ⏳ Pendiente | Alta |
| ModalCalculadora | ⏳ Pendiente | Media |
| Otros | ⏳ Pendiente | Baja |

---

**¿Querés que migre PricingModal ahora para ver el resultado?**

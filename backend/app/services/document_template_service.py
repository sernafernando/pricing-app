"""
Servicio de Document Templates
Lógica de negocio para el sistema de generación de documentos.
"""

from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from app.models.document_template import DocumentTemplate, CONTEXTOS_VALIDOS
from app.schemas.document_template import VariableInfo


class DocumentTemplateService:
    """Servicio para gestión de templates de documentos"""

    def __init__(self, db: Session):
        self.db = db

    def listar_templates(
        self,
        contexto: Optional[str] = None,
        activo: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DocumentTemplate]:
        """
        Lista templates con filtros opcionales.
        Por defecto solo activos. Designers pueden ver inactivos.
        """
        query = self.db.query(DocumentTemplate).options(
            joinedload(DocumentTemplate.creado_por),
        )

        if contexto is not None:
            query = query.filter(DocumentTemplate.contexto == contexto)

        if activo is not None:
            query = query.filter(DocumentTemplate.activo == activo)

        return query.order_by(DocumentTemplate.nombre.asc()).limit(limit).offset(offset).all()

    def obtener_template(self, template_id: int) -> Optional[DocumentTemplate]:
        """Obtiene un template por ID con relaciones cargadas."""
        return (
            self.db.query(DocumentTemplate)
            .options(
                joinedload(DocumentTemplate.creado_por),
                joinedload(DocumentTemplate.actualizado_por),
            )
            .filter(DocumentTemplate.id == template_id)
            .first()
        )

    def crear_template(
        self,
        nombre: str,
        descripcion: Optional[str],
        contexto: str,
        template_json: dict,
        creado_por_id: int,
    ) -> DocumentTemplate:
        """Crea un nuevo template."""
        template = DocumentTemplate(
            nombre=nombre,
            descripcion=descripcion,
            contexto=contexto,
            template_json=template_json,
            creado_por_id=creado_por_id,
        )
        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)

        # Cargar relaciones para la respuesta
        return self.obtener_template(template.id)  # type: ignore[return-value]

    def actualizar_template(
        self,
        template: DocumentTemplate,
        actualizado_por_id: int,
        **kwargs: object,
    ) -> DocumentTemplate:
        """Actualiza campos de un template existente."""
        for key, value in kwargs.items():
            if value is not None and hasattr(template, key):
                setattr(template, key, value)

        template.actualizado_por_id = actualizado_por_id  # type: ignore[assignment]
        self.db.commit()
        self.db.refresh(template)

        return self.obtener_template(template.id)  # type: ignore[return-value]

    def soft_delete_template(
        self,
        template: DocumentTemplate,
        actualizado_por_id: int,
    ) -> None:
        """Soft-delete: marca template como inactivo."""
        template.activo = False  # type: ignore[assignment]
        template.actualizado_por_id = actualizado_por_id  # type: ignore[assignment]
        self.db.commit()


# =============================================================================
# REGISTRO DE VARIABLES POR CONTEXTO
# =============================================================================
# Cada contexto define las variables disponibles para los templates.
# Esto se expone via el endpoint GET /variables/{contexto} para que el
# Designer muestre las variables disponibles al usuario.
# =============================================================================

VARIABLES_POR_CONTEXTO: dict[str, List[VariableInfo]] = {
    "pedidos": [
        VariableInfo(nombre="pedido_id", tipo="text", descripcion="ID del pedido (SOH)", ejemplo="12345"),
        VariableInfo(nombre="fecha_pedido", tipo="date", descripcion="Fecha del pedido", ejemplo="2026-03-15"),
        VariableInfo(
            nombre="fecha_entrega", tipo="date", descripcion="Fecha de entrega estimada", ejemplo="2026-03-20"
        ),
        VariableInfo(
            nombre="observacion", tipo="text", descripcion="Observaciones del pedido", ejemplo="Entregar por portería"
        ),
        VariableInfo(nombre="total", tipo="number", descripcion="Total del pedido", ejemplo="125000.00"),
        VariableInfo(nombre="cliente_nombre", tipo="text", descripcion="Nombre del cliente", ejemplo="Juan Pérez"),
        VariableInfo(nombre="cliente_cuit", tipo="text", descripcion="CUIT del cliente", ejemplo="20-12345678-9"),
        VariableInfo(
            nombre="cliente_direccion", tipo="text", descripcion="Dirección del cliente", ejemplo="Av. Corrientes 1234"
        ),
        VariableInfo(nombre="cliente_ciudad", tipo="text", descripcion="Ciudad del cliente", ejemplo="CABA"),
        VariableInfo(nombre="cliente_cp", tipo="text", descripcion="Código postal del cliente", ejemplo="C1043"),
        VariableInfo(
            nombre="cliente_telefono", tipo="text", descripcion="Teléfono del cliente", ejemplo="11-4567-8901"
        ),
        VariableInfo(nombre="cliente_email", tipo="text", descripcion="Email del cliente", ejemplo="juan@email.com"),
        VariableInfo(nombre="ml_id", tipo="text", descripcion="ID de orden MercadoLibre", ejemplo="2000004567890123"),
        VariableInfo(nombre="ml_guia", tipo="text", descripcion="Número de guía ML", ejemplo="MEL-12345678"),
        VariableInfo(
            nombre="direccion_envio", tipo="text", descripcion="Dirección de envío", ejemplo="Av. Rivadavia 5678, CABA"
        ),
        VariableInfo(nombre="destinatario", tipo="text", descripcion="Nombre del destinatario", ejemplo="María García"),
        VariableInfo(nombre="bultos", tipo="number", descripcion="Cantidad de bultos", ejemplo="3"),
    ],
    "rrhh": [
        VariableInfo(nombre="legajo", tipo="text", descripcion="Número de legajo", ejemplo="EMP-001"),
        VariableInfo(nombre="nombre", tipo="text", descripcion="Nombre del empleado", ejemplo="Carlos"),
        VariableInfo(nombre="apellido", tipo="text", descripcion="Apellido del empleado", ejemplo="González"),
        VariableInfo(
            nombre="nombre_completo",
            tipo="text",
            descripcion="Nombre completo (apellido, nombre)",
            ejemplo="González, Carlos",
        ),
        VariableInfo(nombre="dni", tipo="text", descripcion="DNI del empleado", ejemplo="35.123.456"),
        VariableInfo(nombre="cuil", tipo="text", descripcion="CUIL del empleado", ejemplo="20-35123456-7"),
        VariableInfo(nombre="fecha_nacimiento", tipo="date", descripcion="Fecha de nacimiento", ejemplo="1990-05-15"),
        VariableInfo(
            nombre="domicilio",
            tipo="text",
            descripcion="Domicilio completo",
            ejemplo="Av. San Martín 1234, Lomas de Zamora",
        ),
        VariableInfo(nombre="telefono", tipo="text", descripcion="Teléfono del empleado", ejemplo="11-2345-6789"),
        VariableInfo(nombre="email_personal", tipo="text", descripcion="Email personal", ejemplo="carlos@email.com"),
        VariableInfo(
            nombre="contacto_emergencia", tipo="text", descripcion="Contacto de emergencia", ejemplo="Ana González"
        ),
        VariableInfo(
            nombre="contacto_emergencia_tel", tipo="text", descripcion="Teléfono de emergencia", ejemplo="11-9876-5432"
        ),
        VariableInfo(nombre="fecha_ingreso", tipo="date", descripcion="Fecha de ingreso", ejemplo="2023-01-15"),
        VariableInfo(nombre="fecha_egreso", tipo="date", descripcion="Fecha de egreso (si aplica)", ejemplo=""),
        VariableInfo(nombre="puesto", tipo="text", descripcion="Puesto del empleado", ejemplo="Operario de depósito"),
        VariableInfo(nombre="area", tipo="text", descripcion="Área / sector", ejemplo="Logística"),
        VariableInfo(nombre="estado", tipo="text", descripcion="Estado del empleado", ejemplo="activo"),
        VariableInfo(nombre="observaciones", tipo="text", descripcion="Observaciones del legajo", ejemplo=""),
    ],
    "envios": [
        # Header del remito flex
        VariableInfo(
            nombre="fecha_envio", tipo="date", descripcion="Fecha de envío (pistoleado)", ejemplo="2026-03-15"
        ),
        VariableInfo(nombre="logistica", tipo="text", descripcion="Nombre de la logística", ejemplo="Andreani"),
        VariableInfo(nombre="transporte", tipo="text", descripcion="Nombre del transporte", ejemplo="OCA"),
        VariableInfo(
            nombre="transporte_direccion", tipo="text", descripcion="Dirección del transporte", ejemplo="Ruta 3 km 25"
        ),
        VariableInfo(
            nombre="transporte_telefono", tipo="text", descripcion="Teléfono del transporte", ejemplo="011-4321-0000"
        ),
        # Totales
        VariableInfo(
            nombre="total_envios",
            tipo="number",
            descripcion="Cantidad total de envíos pistoleados",
            ejemplo="45",
        ),
        VariableInfo(nombre="total_bultos", tipo="number", descripcion="Cantidad total de bultos", ejemplo="62"),
        # Resumen por cordón
        VariableInfo(
            nombre="resumen_cordones",
            tipo="text",
            descripcion="Resumen por cordón: CABA: X, Cordón 1: X, ...",
            ejemplo="CABA: 12 | Cordón 1: 18 | Cordón 2: 10 | Cordón 3: 5",
        ),
        # Tabla de envíos pistoleados (pdfme table plugin — string JSON con filas)
        VariableInfo(
            nombre="tabla_envios",
            tipo="table",
            descripcion="Tabla: shipping_id, destinatario, dirección, CP, ciudad, cordón, caja, bultos",
            ejemplo='[["SHP-001","Juan Pérez","Av. Rivadavia 5678","C1043","CABA","CABA","A1","2"]]',
        ),
    ],
    "productos": [
        VariableInfo(nombre="codigo", tipo="text", descripcion="Código del producto", ejemplo="PROD-001"),
        VariableInfo(
            nombre="descripcion", tipo="text", descripcion="Descripción del producto", ejemplo="Monitor LED 24 pulgadas"
        ),
        VariableInfo(nombre="marca", tipo="text", descripcion="Marca del producto", ejemplo="Samsung"),
        VariableInfo(nombre="categoria", tipo="text", descripcion="Categoría del producto", ejemplo="Monitores"),
        VariableInfo(nombre="costo", tipo="number", descripcion="Costo del producto", ejemplo="85000.00"),
        VariableInfo(nombre="moneda_costo", tipo="text", descripcion="Moneda del costo (ARS/USD)", ejemplo="ARS"),
        VariableInfo(nombre="stock", tipo="number", descripcion="Stock disponible", ejemplo="42"),
        VariableInfo(
            nombre="precio_lista_ml", tipo="number", descripcion="Precio lista MercadoLibre", ejemplo="125000.00"
        ),
        VariableInfo(nombre="precio_pvp", tipo="number", descripcion="Precio PVP", ejemplo="120000.00"),
        VariableInfo(
            nombre="precio_web_transferencia",
            tipo="number",
            descripcion="Precio web transferencia",
            ejemplo="110000.00",
        ),
    ],
    "ventas": [
        VariableInfo(nombre="id_venta", tipo="text", descripcion="ID de la venta", ejemplo="98765432"),
        VariableInfo(nombre="id_operacion", tipo="text", descripcion="ID de operación ML", ejemplo="2000004567890"),
        VariableInfo(nombre="fecha", tipo="date", descripcion="Fecha de la venta", ejemplo="2026-03-15"),
        VariableInfo(nombre="marca", tipo="text", descripcion="Marca del producto vendido", ejemplo="Samsung"),
        VariableInfo(nombre="categoria", tipo="text", descripcion="Categoría del producto", ejemplo="Monitores"),
        VariableInfo(nombre="codigo_item", tipo="text", descripcion="Código del item vendido", ejemplo="PROD-001"),
        VariableInfo(
            nombre="descripcion", tipo="text", descripcion="Descripción del producto", ejemplo="Monitor LED 24"
        ),
        VariableInfo(nombre="cantidad", tipo="number", descripcion="Cantidad vendida", ejemplo="2"),
        VariableInfo(nombre="monto_unitario", tipo="number", descripcion="Monto unitario", ejemplo="125000.00"),
        VariableInfo(nombre="monto_total", tipo="number", descripcion="Monto total", ejemplo="250000.00"),
    ],
    "rma": [
        VariableInfo(nombre="numero_caso", tipo="text", descripcion="Número de caso RMA", ejemplo="RMA-2026-0001"),
        VariableInfo(nombre="cliente_nombre", tipo="text", descripcion="Nombre del cliente", ejemplo="Juan Pérez"),
        VariableInfo(nombre="cliente_dni", tipo="text", descripcion="DNI del cliente", ejemplo="35.123.456"),
        VariableInfo(nombre="ml_id", tipo="text", descripcion="ID de orden ML relacionada", ejemplo="2000004567890123"),
        VariableInfo(nombre="origen", tipo="text", descripcion="Origen del reclamo", ejemplo="mercadolibre"),
        VariableInfo(nombre="estado", tipo="text", descripcion="Estado del caso", ejemplo="en_revision"),
        VariableInfo(
            nombre="observaciones",
            tipo="text",
            descripcion="Observaciones del caso",
            ejemplo="Producto con pantalla rota",
        ),
        VariableInfo(nombre="fecha_caso", tipo="date", descripcion="Fecha del caso", ejemplo="2026-03-10"),
    ],
}


def obtener_variables_contexto(contexto: str) -> Optional[List[VariableInfo]]:
    """Retorna las variables disponibles para un contexto dado."""
    return VARIABLES_POR_CONTEXTO.get(contexto)


def obtener_contextos_disponibles() -> List[str]:
    """Retorna la lista de contextos válidos."""
    return CONTEXTOS_VALIDOS

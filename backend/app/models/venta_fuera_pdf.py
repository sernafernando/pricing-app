"""Ventas por fuera loaded from GBP's PDF reports.

The detailed report ("Reporte de Ventas Detalladas") creates the operations: one row per document in
`ventas_fuera_operaciones` and one per line in `ventas_fuera_operacion_lineas`. Metrics, offsets and sell in / sell
out of ventas por fuera read only these tables, never the GBP sync (`ventas_fuera_ml_metricas`). Each upload is kept
in `ventas_fuera_pdf_cargas`; the last upload of a company, salesperson and date range replaces what was loaded for
them.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from app.core.database import Base

MONTO = Numeric(18, 2)


class VentaFueraPdfCarga(Base):
    """One upload: the header of the detailed PDF (company, salesperson filter, range) and its cross-check warnings."""

    __tablename__ = "ventas_fuera_pdf_cargas"

    id = Column(Integer, primary_key=True)
    empresa = Column(String(200), nullable=False)
    # The PDF's "Vendedor" parameter; NULL when the report covers every salesperson ("Todos").
    vendedor = Column(String(200), nullable=True)
    desde = Column(Date, nullable=False)
    hasta = Column(Date, nullable=False)
    # NULL when only the summary was uploaded.
    archivo_detallado = Column(String(255), nullable=True)
    archivo_resumen = Column(String(255), nullable=True)
    documentos = Column(Integer, nullable=False)
    reemplazados = Column(Integer, nullable=False)
    avisos = Column(JSON, nullable=False, default=list)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_ventas_fuera_pdf_cargas_empresa_desde", "empresa", "desde"),)


class VentaFueraPdfAlcance(Base):
    """A load scope: company + salesperson filter (NULL = "Todos") + exact date range. It records the last upload of
    each report and what of it no report of the other kind covers yet, so the view can mark "falta el resumen" or
    "falta el detallado" (owner, L8) only for those salespeople and dates (owner, L11: "que cubra por partes"). A
    summary uploaded alone is kept here as control and creates no operations."""

    __tablename__ = "ventas_fuera_pdf_alcances"

    id = Column(Integer, primary_key=True)
    empresa = Column(String(200), nullable=False)
    vendedor = Column(String(200), nullable=True)
    desde = Column(Date, nullable=False)
    hasta = Column(Date, nullable=False)
    detallada_carga_id = Column(Integer, ForeignKey("ventas_fuera_pdf_cargas.id"), nullable=True)
    resumen_carga_id = Column(Integer, ForeignKey("ventas_fuera_pdf_cargas.id"), nullable=True)
    resumen_con_impuestos = Column(Boolean, nullable=True)
    # [{"reporte": "detallada" | "resumen", "vendedor": str | None, "desde": "YYYY-MM-DD", "hasta": "YYYY-MM-DD"}]
    faltantes = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    avisos = Column(JSON, nullable=False, default=list)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    documentos_resumen = relationship(
        "VentaFueraPdfResumenDocumento", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        # One scope per company, salesperson and range; "Todos" (NULL) is a salesperson value of its own.
        Index(
            "uq_ventas_fuera_pdf_alcances_scope",
            "empresa",
            func.coalesce(vendedor, ""),
            "desde",
            "hasta",
            unique=True,
        ),
    )

    @property
    def falta_detallada(self) -> bool:
        return any(f["reporte"] == "detallada" for f in self.faltantes or [])

    @property
    def falta_resumen(self) -> bool:
        return any(f["reporte"] == "resumen" for f in self.faltantes or [])


class VentaFueraPdfResumenDocumento(Base):
    """A document of the last summary report of a scope, kept to cross-check a detailed report uploaded later."""

    __tablename__ = "ventas_fuera_pdf_resumen_documentos"

    id = Column(Integer, primary_key=True)
    alcance_id = Column(
        Integer, ForeignKey("ventas_fuera_pdf_alcances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cliente_codigo = Column(String(50), nullable=True)
    cliente = Column(String(255), nullable=False)
    tipo = Column(String(2), nullable=False)
    letra = Column(String(1), nullable=False)
    punto_venta = Column(Integer, nullable=False)
    numero = Column(Integer, nullable=False)
    fecha = Column(Date, nullable=False)
    fecha_vencimiento = Column(Date, nullable=True)
    vendedor = Column(String(100), nullable=False)
    condicion_venta = Column(String(100), nullable=False)
    importe = Column(MONTO, nullable=False)
    saldo = Column(MONTO, nullable=False)

    @property
    def clave(self) -> tuple[str, str, int, int]:
        return (self.tipo, self.letra, self.punto_venta, self.numero)


class VentaFueraOperacion(Base):
    """A document of the detailed report. Amounts keep GBP's sign: credit notes (Nc) are negative."""

    __tablename__ = "ventas_fuera_operaciones"

    id = Column(Integer, primary_key=True)
    carga_id = Column(Integer, ForeignKey("ventas_fuera_pdf_cargas.id"), nullable=False, index=True)
    empresa = Column(String(200), nullable=False)
    # As printed on the document (GBP cuts it to 12 characters, e.g. "Carla Ejempl").
    vendedor = Column(String(100), nullable=False)
    cliente = Column(String(255), nullable=False)
    cliente_codigo = Column(String(50), nullable=True)
    tipo = Column(String(2), nullable=False)
    letra = Column(String(1), nullable=False)
    punto_venta = Column(Integer, nullable=False)
    numero = Column(Integer, nullable=False)
    fecha = Column(Date, nullable=False)
    fecha_vencimiento = Column(Date, nullable=True)
    condicion_venta = Column(String(100), nullable=True)
    # Header "Importe" of the detailed report: lines plus VAT (plus the cheque surcharge).
    importe = Column(MONTO, nullable=False)
    saldo = Column(MONTO, nullable=False)
    # Sum of the lines' "Precio" (without VAT): the sale.
    total_lineas = Column(MONTO, nullable=False)
    # "Importe" of the summary report (without VAT, cheque surcharge included); NULL without a summary.
    importe_resumen = Column(MONTO, nullable=True)
    # 4% financing surcharge of "CHEQUE 30 D" documents: not a sale, kept apart.
    recargo_financiero = Column(MONTO, nullable=False, default=0)

    lineas = relationship(
        "VentaFueraOperacionLinea",
        back_populates="operacion",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="VentaFueraOperacionLinea.renglon",
    )

    __table_args__ = (
        UniqueConstraint("empresa", "tipo", "letra", "punto_venta", "numero", name="uq_ventas_fuera_operaciones_doc"),
        Index("ix_ventas_fuera_operaciones_empresa_fecha", "empresa", "fecha"),
    )


class VentaFueraOperacionLinea(Base):
    """A line of a document. `precio`, `precio_costo` and `precio_costo_pp` are line totals without VAT."""

    __tablename__ = "ventas_fuera_operacion_lineas"

    id = Column(Integer, primary_key=True)
    operacion_id = Column(
        Integer, ForeignKey("ventas_fuera_operaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    renglon = Column(Integer, nullable=False)
    # EAN = productos_erp.codigo; NULL on manual lines ("Servicio Tecnico (Manual)").
    codigo = Column(String(100), nullable=True, index=True)
    articulo = Column(String(255), nullable=False)
    cantidad = Column(MONTO, nullable=False)
    moneda = Column(String(3), nullable=False)
    precio = Column(MONTO, nullable=False)
    precio_costo = Column(MONTO, nullable=False)
    precio_costo_pp = Column(MONTO, nullable=False)

    operacion = relationship("VentaFueraOperacion", back_populates="lineas")

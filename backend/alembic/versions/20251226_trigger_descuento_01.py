"""add trigger auto descuento prearmado

Revision ID: 20251226_produccion_03
Revises: 20251226_produccion_02
Create Date: 2025-12-26 19:00:00

Agrega trigger que automáticamente descuenta de produccion_prearmado
cuando la cantidad en pedido_preparacion_cache disminuye.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '20251226_produccion_03'
down_revision = '20251226_produccion_02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Crear función
    op.execute("""
        CREATE OR REPLACE FUNCTION auto_descuento_prearmado()
        RETURNS TRIGGER AS $$
        DECLARE
            cantidad_reducida INTEGER;
            prearmado_actual INTEGER;
            nueva_cantidad INTEGER;
        BEGIN
            -- Solo ejecutar cuando la cantidad disminuye
            IF NEW.cantidad < OLD.cantidad THEN
                cantidad_reducida := FLOOR(OLD.cantidad - NEW.cantidad);
                
                -- Buscar si este item tiene pre-armado
                SELECT cantidad INTO prearmado_actual
                FROM produccion_prearmado
                WHERE item_id = NEW.item_id;
                
                -- Si existe pre-armado, descontar
                IF FOUND THEN
                    nueva_cantidad := GREATEST(0, prearmado_actual - cantidad_reducida);
                    
                    IF nueva_cantidad = 0 THEN
                        -- Si llega a 0, eliminar el registro
                        DELETE FROM produccion_prearmado WHERE item_id = NEW.item_id;
                        
                        RAISE NOTICE 'Pre-armado eliminado para item_id % (cantidad llegó a 0)', NEW.item_id;
                    ELSE
                        -- Actualizar la cantidad
                        UPDATE produccion_prearmado
                        SET cantidad = nueva_cantidad,
                            fecha_actualizacion = NOW()
                        WHERE item_id = NEW.item_id;
                        
                        RAISE NOTICE 'Pre-armado actualizado para item_id %: % -> %', 
                            NEW.item_id, prearmado_actual, nueva_cantidad;
                    END IF;
                END IF;
            END IF;
            
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # Crear trigger
    op.execute("""
        DROP TRIGGER IF EXISTS trigger_auto_descuento_prearmado ON pedido_preparacion_cache;
        
        CREATE TRIGGER trigger_auto_descuento_prearmado
            AFTER UPDATE ON pedido_preparacion_cache
            FOR EACH ROW
            WHEN (NEW.cantidad < OLD.cantidad)
            EXECUTE FUNCTION auto_descuento_prearmado();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trigger_auto_descuento_prearmado ON pedido_preparacion_cache;")
    op.execute("DROP FUNCTION IF EXISTS auto_descuento_prearmado();")

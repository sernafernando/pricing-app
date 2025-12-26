"""recalcular severidades notificaciones

Revision ID: 20251226_recalc_01
Revises: 20251226_ignore_01
Create Date: 2025-12-26 13:22:09

FIX CRÍTICO: Recalcular severidades de notificaciones existentes.

El bug: Se calculaba diferencia porcentual RELATIVA en vez de ABSOLUTA.
  - Ejemplo: markup real -1.32% vs objetivo 3.79%
  - Cálculo VIEJO (MALO): |(-1.32-3.79)/3.79*100| = 134.8% → URGENT ❌
  - Cálculo NUEVO (BUENO): |-1.32 - 3.79| = 5.11 puntos → WARNING ✓

Esta migración recalcula las severidades con la lógica correcta.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251226_recalc_01'
down_revision = '20251226_ignore_01'
branch_labels = None
depends_on = None


def calcular_severidad_correcta(markup_real, markup_objetivo):
    """
    Calcula severidad basándose en diferencia ABSOLUTA en puntos porcentuales.
    
    Lógica:
    - >25 puntos → URGENT
    - >15 puntos → CRITICAL  
    - >10 puntos → WARNING
    - <=10 puntos → INFO
    """
    if markup_real is None or markup_objetivo is None:
        return 'INFO'
    
    diferencia_absoluta = abs(float(markup_real) - float(markup_objetivo))
    
    if diferencia_absoluta > 25.0:
        return 'URGENT'
    elif diferencia_absoluta > 15.0:
        return 'CRITICAL'
    elif diferencia_absoluta > 10.0:
        return 'WARNING'
    else:
        return 'INFO'


def upgrade():
    """
    Recalcula las severidades de todas las notificaciones existentes.
    """
    connection = op.get_bind()
    
    # Obtener todas las notificaciones con markup
    result = connection.execute(sa.text("""
        SELECT id, tipo, markup_real, markup_objetivo, severidad
        FROM notificaciones
        WHERE markup_real IS NOT NULL 
          AND markup_objetivo IS NOT NULL
          AND tipo IN ('markup_bajo', 'markup_negativo', 'markup_fuera_rango')
    """))
    
    notificaciones = list(result)
    
    if len(notificaciones) == 0:
        print("ℹ️  No hay notificaciones para recalcular")
        return
    
    print(f"\n🔄 Recalculando severidad de {len(notificaciones)} notificaciones...\n")
    
    cambios = {'URGENT': 0, 'CRITICAL': 0, 'WARNING': 0, 'INFO': 0}
    total_actualizadas = 0
    ejemplos_mostrados = 0
    
    for notif in notificaciones:
        id_notif = notif[0]
        tipo = notif[1]
        markup_real = float(notif[2])
        markup_objetivo = float(notif[3])
        severidad_vieja = notif[4]
        
        # Calcular nueva severidad
        severidad_nueva = calcular_severidad_correcta(markup_real, markup_objetivo)
        
        # Solo actualizar si cambió
        if severidad_nueva != severidad_vieja:
            connection.execute(
                sa.text("UPDATE notificaciones SET severidad = :sev WHERE id = :id"),
                {"sev": severidad_nueva, "id": id_notif}
            )
            
            cambios[severidad_nueva] += 1
            total_actualizadas += 1
            
            # Log primeros 5 ejemplos
            if ejemplos_mostrados < 5:
                diferencia = abs(markup_real - markup_objetivo)
                print(f"  ID {id_notif}: {severidad_vieja} → {severidad_nueva}")
                print(f"    Markup: {markup_real:.2f}% vs {markup_objetivo:.2f}% (Δ={diferencia:.2f} puntos)\n")
                ejemplos_mostrados += 1
    
    print(f"✅ Actualizadas {total_actualizadas} de {len(notificaciones)} notificaciones:")
    print(f"   • INFO:     {cambios['INFO']}")
    print(f"   • WARNING:  {cambios['WARNING']}")
    print(f"   • CRITICAL: {cambios['CRITICAL']}")
    print(f"   • URGENT:   {cambios['URGENT']}\n")


def downgrade():
    """
    No hay downgrade. Las severidades viejas estaban mal calculadas.
    """
    print("⚠️  No hay downgrade para esta migración (las severidades viejas estaban mal).")
    pass

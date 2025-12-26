#!/bin/bash
# Script para aplicar migraciones de Alembic
# Uso: ./APLICAR_MIGRACIONES.sh

set -e  # Exit on error

echo "🔄 Aplicando migraciones de base de datos..."
echo ""

cd "$(dirname "$0")"

# Verificar que alembic esté disponible
if ! command -v alembic &> /dev/null; then
    echo "❌ Error: alembic no está instalado"
    echo "   Instalá con: pip install alembic"
    exit 1
fi

# Mostrar migraciones pendientes
echo "📋 Verificando migraciones pendientes..."
alembic current
echo ""

# Aplicar migraciones
echo "⬆️  Aplicando upgrade head..."
alembic upgrade head

echo ""
echo "✅ Migraciones aplicadas correctamente"
echo ""
echo "📊 Estado actual:"
alembic current

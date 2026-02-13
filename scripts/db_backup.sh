#!/bin/bash

# =============================================================================
# Backup diario de PostgreSQL - pricing_db
# Guarda los últimos 30 días en /srv/db-backup comprimidos con gzip
#
# Uso manual:
#   bash /var/www/html/pricing-app/scripts/db_backup.sh
#
# Cron (diario a la 01:00, ANTES de los syncs incrementales):
#   0 1 * * * /var/www/html/pricing-app/scripts/db_backup.sh >> /var/log/pricing-app/db_backup.log 2>&1
# =============================================================================

set -euo pipefail

# --- Config ---
BACKUP_DIR="/srv/db-backup"
RETENTION_DAYS=30
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/pricing_db_${TIMESTAMP}.dump.gz"

# DB config (lee del .env del backend o usa defaults)
ENV_FILE="/var/www/html/pricing-app/backend/.env"
if [ -f "$ENV_FILE" ]; then
    # Extraer datos de DATABASE_URL
    DB_URL=$(grep -E "^DATABASE_URL=" "$ENV_FILE" | cut -d'=' -f2-)
    DB_USER=$(echo "$DB_URL" | sed -n 's|postgresql://\([^:]*\):.*|\1|p')
    DB_PASS=$(echo "$DB_URL" | sed -n 's|postgresql://[^:]*:\([^@]*\)@.*|\1|p')
    DB_HOST=$(echo "$DB_URL" | sed -n 's|.*@\([^:]*\):.*|\1|p')
    DB_PORT=$(echo "$DB_URL" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
    DB_NAME=$(echo "$DB_URL" | sed -n 's|.*/\([^?]*\).*|\1|p')
else
    DB_USER="pricing_user"
    DB_PASS="GaussDB1214"
    DB_HOST="localhost"
    DB_PORT="5432"
    DB_NAME="pricing_db"
fi

# --- Setup ---
echo "============================================"
echo "🗄️  Backup PostgreSQL - ${TIMESTAMP}"
echo "============================================"
echo "   DB: ${DB_NAME}@${DB_HOST}:${DB_PORT}"
echo "   Destino: ${BACKUP_FILE}"

# Crear directorio si no existe
mkdir -p "${BACKUP_DIR}"

# --- Backup ---
echo "   Ejecutando pg_dump..."
PGPASSWORD="${DB_PASS}" pg_dump \
    -U "${DB_USER}" \
    -h "${DB_HOST}" \
    -p "${DB_PORT}" \
    -d "${DB_NAME}" \
    -F c \
    | gzip > "${BACKUP_FILE}"

# Verificar que el archivo no esté vacío
FILESIZE=$(stat -c%s "${BACKUP_FILE}" 2>/dev/null || stat -f%z "${BACKUP_FILE}" 2>/dev/null)
if [ "${FILESIZE}" -lt 1024 ]; then
    echo "   ❌ Error: backup demasiado pequeño (${FILESIZE} bytes), algo falló"
    rm -f "${BACKUP_FILE}"
    exit 1
fi

FILESIZE_MB=$(echo "scale=2; ${FILESIZE}/1048576" | bc)
echo "   ✅ Backup completado: ${FILESIZE_MB} MB"

# --- Limpieza: borrar backups de más de N días ---
echo "   Limpiando backups con más de ${RETENTION_DAYS} días..."
DELETED=$(find "${BACKUP_DIR}" -name "pricing_db_*.dump.gz" -mtime +${RETENTION_DAYS} -print -delete | wc -l)
echo "   🗑️  Eliminados: ${DELETED} backups antiguos"

# --- Resumen ---
TOTAL=$(find "${BACKUP_DIR}" -name "pricing_db_*.dump.gz" | wc -l)
TOTAL_SIZE=$(du -sh "${BACKUP_DIR}" | cut -f1)
echo ""
echo "   📊 Backups almacenados: ${TOTAL}"
echo "   💾 Espacio total: ${TOTAL_SIZE}"
echo "============================================"
echo "   ✅ Backup finalizado: $(date +"%Y-%m-%d %H:%M:%S")"
echo "============================================"

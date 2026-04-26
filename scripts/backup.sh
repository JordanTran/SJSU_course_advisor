#!/bin/bash
# ──────────────────────────────────────────────
#  backup.sh  —  Backs up the course_advisor_db
#  Usage: ./backup.sh
# ──────────────────────────────────────────────

DB_NAME="course_advisor_db"
DB_USER="postgres"
BACKUP_DIR="./backups"
DATE=$(date '+%Y-%m-%d_%H-%M-%S')
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${DATE}.sql"

# Create backups folder if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "Starting backup of $DB_NAME..."

# Run the backup
pg_dump -U "$DB_USER" -d "$DB_NAME" > "$BACKUP_FILE"

# Check if it worked
if [ $? -eq 0 ]; then
    echo "Backup saved to: $BACKUP_FILE"
else
    echo "Backup failed. Make sure PostgreSQL is running."
fi

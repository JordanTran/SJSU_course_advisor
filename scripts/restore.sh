#!/bin/bash
# ──────────────────────────────────────────────
#  restore.sh  —  Restores the course_advisor_db
#  Usage: ./restore.sh backups/course_advisor_db_2024-01-01.sql
# ──────────────────────────────────────────────

DB_NAME="course_advisor_db"
DB_USER="postgres"
BACKUP_FILE="$1"

# Check that the user gave a backup file
if [ -z "$BACKUP_FILE" ]; then
    echo "Please provide a backup file."
    echo "Example: ./restore.sh backups/course_advisor_db_2024-01-01.sql"
    exit 1
fi

# Check the file actually exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo "File not found: $BACKUP_FILE"
    exit 1
fi

# Ask for confirmation before wiping the database
echo "WARNING: This will overwrite $DB_NAME with data from $BACKUP_FILE"
read -p "Are you sure? Type YES to continue: " CONFIRM

if [ "$CONFIRM" != "YES" ]; then
    echo "Restore cancelled."
    exit 0
fi

echo "Restoring $DB_NAME from $BACKUP_FILE..."

# Drop and recreate the database
psql -U "$DB_USER" -c "DROP DATABASE IF EXISTS $DB_NAME;"
psql -U "$DB_USER" -c "CREATE DATABASE $DB_NAME;"

# Restore the backup
psql -U "$DB_USER" -d "$DB_NAME" < "$BACKUP_FILE"

# Check if it worked
if [ $? -eq 0 ]; then
    echo "Restore complete!"
else
    echo "Restore failed. Check the backup file and try again."
fi

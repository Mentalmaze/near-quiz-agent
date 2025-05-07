#!/bin/bash
set -e

# Extract database host and port from DATABASE_URL or use environment variables
DB_HOST="${DATABASE_HOST:-$(echo $DATABASE_URL | sed -n 's/.*@\([^:]*\).*/\1/p')}"
DB_PORT="${DATABASE_PORT:-$(echo $DATABASE_URL | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')}"

if [ -n "$DB_HOST" ]; then
  echo "Checking connection to database at $DB_HOST..."
  # Wait for database to be ready
  for i in {1..30}; do
    if pg_isready -h $DB_HOST -p "${DB_PORT:-5432}"; then
      echo "Database connection is ready!"
      break
    fi
    echo "Waiting for database connection... ($i/30)"
    sleep 1
  done
fi

# Run database migrations and initialize DB
echo "Initializing application..."
python -c "
import sys, os
sys.path.append('.')
from src.store.database import init_db, migrate_schema
if 'postgres' in os.environ.get('DATABASE_URL', ''):
    print('Running database migrations...')
    migrate_schema()
print('Initializing database tables...')
init_db()
"

# Execute the main command
echo "Starting application..."
exec "$@"

#!/bin/sh
set -eu
python manage.py migrate --noinput
# Seed a fresh installation once. Preserve subsequent dictionary reviews.
if [ "$(python manage.py shell -c 'from dictionary.models import Sign; print(Sign.objects.exists())' --verbosity 0)" = False ]; then
    python manage.py import_slovo assets/slovo
fi
exec uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers 1

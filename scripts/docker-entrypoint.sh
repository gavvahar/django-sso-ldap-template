#!/bin/sh
# Applies any pending migrations, then hands over to the command in CMD.
# Keeping it here rather than in the image build means the database can live on
# a volume that only exists once the container runs.
set -eu

python manage.py migrate --noinput

exec "$@"

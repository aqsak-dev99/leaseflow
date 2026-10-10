#!/usr/bin/env bash
# Runs on Render every time the app is deployed.
set -o errexit

pip install -r requirements/base.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py restore_demo_documents

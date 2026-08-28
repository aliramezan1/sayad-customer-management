#!/usr/bin/env bash
echo "Starting Sayad Customer Management Web App..."
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

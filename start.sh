#!/bin/bash

# Start the FastAPI backend with 2 workers for better concurrency
# It serves both the API endpoints and the React frontend statically
echo "[DEPLOY] Starting unified FastAPI server on port 7860 with 2 workers..."
uvicorn app.main:app --host 0.0.0.0 --port 7860 --workers 2

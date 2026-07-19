#!/bin/bash

# Start the FastAPI backend directly on port 7860
# It serves both the API endpoints and the React frontend statically
echo "[DEPLOY] Starting unified FastAPI server on port 7860..."
uvicorn api:app --host 0.0.0.0 --port 7860

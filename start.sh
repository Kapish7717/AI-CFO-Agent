#!/bin/bash

# 1. Start the FastAPI backend in the background
echo "[DEPLOY] Starting FastAPI on port 8000..."
uvicorn api:app --host 0.0.0.0 --port 8000 &

# 2. Give the backend a second to warm up
sleep 2

# 3. Start the Gradio frontend in the foreground
# Hugging Face Spaces will look for activity on port 7860
echo "[DEPLOY] Starting Gradio on port 7860..."
python gradio_app.py

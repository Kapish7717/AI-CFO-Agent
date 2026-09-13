# STAGE 1: BUILD REACT FRONTEND
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* frontend/bun.lock* ./
RUN npm install --legacy-peer-deps
COPY frontend/ ./
RUN npm run build

# STAGE 2: PYTHON BACKEND
FROM python:3.12-slim
WORKDIR /app

# Install system dependencies for PDF generation (reportlab / matplotlib)
RUN apt-get update && apt-get install -y \
    libfontconfig1 \
    libfreetype6-dev \
    libjpeg-dev \
    libpng-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Copy built frontend dist from STAGE 1
COPY --from=frontend-build /app/frontend/dist/client /app/frontend/dist/client

# Create uploads directory
RUN mkdir -p uploads && chmod -R 777 uploads

# Use Render's $PORT env var (defaults to 10000)
ENV PORT=10000
EXPOSE $PORT

# Start command — uses $PORT from Render
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT

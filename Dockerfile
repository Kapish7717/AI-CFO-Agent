# STAGE 1: BUILD REACT FRONTEND USING OFFICIAL NODE IMAGE
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install --legacy-peer-deps
COPY frontend/ ./
RUN npm run build

# STAGE 2: PYTHON BACKEND & FINAL IMAGE
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
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

# Set permissions for Hugging Face Spaces (user ID 1000)
ENV HOME=/tmp
RUN chmod -R 777 /app && chmod -R 777 /tmp

# Expose default Hugging Face port
EXPOSE 7860

# Start command
RUN chmod +x start.sh
CMD ["./start.sh"]

# 1. BASE IMAGE
FROM python:3.12-slim

# 2. INSTALL SYSTEM DEPENDENCIES
# Necessary for matplotlib, reportlab (PDF generation), Node.js and npm
RUN apt-get update && apt-get install -y \
    libfontconfig1 \
    libfreetype6-dev \
    libjpeg-dev \
    libpng-dev \
    curl \
    ca-certificates \
    gnupg \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# 3. WORKDIR
WORKDIR /app

# Ensure Python logs are sent straight to terminal without buffering
ENV PYTHONUNBUFFERED=1

# 4. INSTALL PYTHON DEPENDENCIES
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. COPY PROJECT FILES
COPY . .

# 6. BUILD REACT FRONTEND
WORKDIR /app/frontend
RUN npm install --legacy-peer-deps
# Vite build uses public and src assets to output assets to dist
RUN npm run build
WORKDIR /app

# 7. SET PERMISSIONS FOR HUGGING FACE
# Hugging Face runs as user 1000. /tmp is always writable.
ENV HOME=/tmp
RUN chmod -R 777 /app && chmod -R 777 /tmp

# 8. EXPOSE PORTS
# 7860 is the port HF Spaces will look for activity on
EXPOSE 7860

# 9. START COMMAND
RUN chmod +x start.sh
CMD ["./start.sh"]

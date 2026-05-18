# 1. BASE IMAGE
FROM python:3.12-slim

# 2. INSTALL SYSTEM DEPENDENCIES
# Necessary for matplotlib and reportlab (PDF generation)
RUN apt-get update && apt-get install -y \
    libfontconfig1 \
    libfreetype6-dev \
    libjpeg-dev \
    libpng-dev \
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

# 6. SET PERMISSIONS FOR HUGGING FACE
# Hugging Face runs as user 1000. /tmp is always writable.
ENV HOME=/tmp
RUN chmod -R 777 /app && chmod -R 777 /tmp

# 6. EXPOSE PORTS
# 8000 for FastAPI, 7860 for Gradio
EXPOSE 8000 7860

# 7. START COMMAND
# We use a startup script to manage both the FastAPI and Gradio processes
RUN chmod +x start.sh
CMD ["./start.sh"]

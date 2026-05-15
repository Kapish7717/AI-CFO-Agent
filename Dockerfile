# 1. BASE IMAGE: Think of this as your starting operating system.
# We are using a lightweight version of Linux that comes with Python 3.12 pre-installed.
FROM python:3.12-slim

# 2. WORKDIR: This creates a folder named '/app' inside the container 
# and makes it the current working directory. Everything we do happens here.
WORKDIR /app

# 3. COPY REQUIREMENTS: We copy your requirements.txt from your Windows PC 
# into the container's /app folder.
COPY requirements.txt .

# 4. INSTALL DEPENDENCIES: We tell the container to install your Python packages.
RUN pip install --no-cache-dir -r requirements.txt

# 5. COPY THE REST: Now we copy ALL your code (agent.py, app.py, credentials, etc.)
# into the container.
COPY . .

# 6. EXPOSE PORTS: We declare which ports this container will use to talk to the outside world.
# 8000 is for FastAPI, 7860 is for Gradio.
EXPOSE 8000 7860

# 7. START COMMAND: This is the command that runs when the container is turned on.
# We are telling it to start the FastAPI backend AND the Gradio frontend at the same time.
# We use host 0.0.0.0 so that the FastAPI server can be accessed from outside the container.
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port 8000 & python gradio_app.py"]

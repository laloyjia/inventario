# Dockerfile para PanolERP
FROM python:3.11-slim

# Variables de entorno básicas
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Carpeta de trabajo
WORKDIR /app

# Dependencias del sistema (psycopg2 necesita libpq, openpyxl no necesita nada extra)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python primero (cacheable layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Render asigna el puerto via $PORT
ENV PORT=10000
EXPOSE 10000

# Arrancar con gunicorn
CMD gunicorn app:app --workers 2 --threads 2 --timeout 120 --bind 0.0.0.0:$PORT

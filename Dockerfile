# Plataforma ABGA: un solo contenedor que sirve la API y el panel.
#
# No lleva `.env` (no está en git y no debe estarlo): en producción todo entra por variables de
# entorno de Coolify. `backend/scripts/arranque.py` comprueba la base, crea el usuario interno si
# falta y lanza uvicorn.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Las dependencias van primero para que cambiar el código no invalide la capa de pip.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

# El contenedor no necesita root para nada: usuario propio y sin shell.
RUN useradd --create-home --uid 10001 abga \
    && chown -R abga:abga /app
USER abga

EXPOSE 8000

# El panel es información pública hasta que alguien inicia sesión (ahí manda la cookie), así que
# sirve como comprobación de vida.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4).status == 200 else 1)"

# exec en arranque.py: uvicorn sustituye al proceso y recibe las señales de Docker (parada limpia).
CMD ["python", "backend/scripts/arranque.py"]

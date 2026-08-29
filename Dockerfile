FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git openssh-client curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir fastapi uvicorn[standard]

# Copy source
COPY . .

# Create data/output dirs
RUN mkdir -p data output deploy/keys

# Expose port for deploy_server
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command: serve dashboard + API
CMD ["python", "-m", "uvicorn", "deploy_server:app", "--host", "0.0.0.0", "--port", "8000"]

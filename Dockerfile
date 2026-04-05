FROM python:3.12-slim

WORKDIR /app

# Build dependencies for llama-cpp-python (compiled from source)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ cmake make git curl \
    && rm -rf /var/lib/apt/lists/*

COPY agent/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY agent/ ./agent/
COPY personalities/ ./personalities/

# Models and database are mounted at runtime — do not bake into image.
# Mount a workspace and set sandbox_root in runtime_config to a path inside the mount (e.g. /data/workspace).
VOLUME ["/app/models", "/app/data"]

ENV PYTHONUNBUFFERED=1
WORKDIR /app/agent

# Default config: database and knowledge under /app/data (set in runtime_config.json)
ENV LAYLA_DB_PATH=/app/data/layla.db

EXPOSE 8000

# Resource caps: prefer docker run --cpus=... --memory=... (see docs/RUNBOOKS.md).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

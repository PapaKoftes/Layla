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

# Models and database are mounted at runtime — do not bake into image
VOLUME ["/app/models", "/app/data"]

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/agent

# Default config: database and knowledge under /app/data
ENV LAYLA_DB_PATH=/app/data/layla.db

EXPOSE 8000

CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

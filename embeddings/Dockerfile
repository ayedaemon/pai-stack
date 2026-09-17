FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the default embedding model so it starts instantly without network delay
ARG EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL}
RUN python3 -c "from fastembed import TextEmbedding; print('Pre-caching model...'); TextEmbedding(model_name='${EMBEDDING_MODEL}')"

COPY server.py .

EXPOSE 8080

CMD ["python", "server.py"]

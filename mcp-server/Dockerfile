FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY skills/ /app/skills/
COPY tools/ /app/tools/
COPY kb/ /app/kb/

EXPOSE 8000

CMD ["python", "server.py"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Sao_Paulo \
    ENDPOINTS_DIR=/app/endpoints

WORKDIR /app
COPY pyproject.toml README.md ./
COPY franca_collectors ./franca_collectors
RUN pip install ".[postgres]" && useradd --create-home --uid 10001 coletor
COPY endpoints ./endpoints

USER coletor
ENTRYPOINT ["python", "-m", "franca_collectors"]
CMD ["--help"]

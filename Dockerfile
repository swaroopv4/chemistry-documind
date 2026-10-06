FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
COPY requirements-tested.txt .
RUN pip install --no-cache-dir -r requirements-tested.txt
ENV PYTHONUNBUFFERED=1 TIKTOKEN_CACHE_DIR=/opt/tiktoken DOCUMIND_SERVER_ADDRESS=0.0.0.0
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base'); tiktoken.get_encoding('o200k_base')"
COPY core ./core
COPY phases ./phases
COPY ui ./ui
COPY deploy ./deploy
COPY benchmarks ./benchmarks
CMD ["python", "ui/launch.py"]

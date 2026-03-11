FROM python:3.10-alpine
WORKDIR /app

RUN apk add --no-cache \
    gcc \
    musl-dev \
    postgresql-dev \
    mupdf-dev \
    mupdf-tools \
    freetype-dev \
    jpeg-dev \
    openjpeg-dev \
    zlib-dev \
    build-base

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
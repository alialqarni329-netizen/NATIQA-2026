FROM python:3.10-alpine
WORKDIR /app
RUN apk add --no-cache gcc musl-dev postgresql-dev

# هنا السر: بنقول له ادخل مجلد backend وخذ الملف
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# انسخ كل شيء من مجلد backend إلى السيرفر
COPY backend/ .

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV MIN_PROFIT_PERCENT=0.3
ENV SCAN_INTERVAL=5

EXPOSE 5000

CMD ["gunicorn", "App:app", "--bind", "0.0.0.0:5000"]

FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc python3-dev libpq-dev && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip

RUN useradd --system --uid 10001 --create-home collector

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

USER collector

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]

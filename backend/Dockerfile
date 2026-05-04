FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Run uvicorn using shell form so  is expanded
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}
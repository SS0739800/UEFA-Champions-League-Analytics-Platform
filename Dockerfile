FROM python:3.13-slim

WORKDIR /app

# Install dependencies first so this layer is cached when only the code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY sql ./sql
COPY app ./app
COPY .streamlit ./.streamlit

# Lets `app` and `src` be imported from anywhere in the container.
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8501

CMD ["python", "-m", "streamlit", "run", "app/Home.py", "--server.port", "8501", "--server.address", "0.0.0.0"]

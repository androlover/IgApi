FROM python:3.12-slim

RUN apt-get update && apt-get install -y ffmpeg

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["gunicorn", "App:app", "--bind", "0.0.0.0:10000"]
# One long-running process (jobbot.serve): Telegram buttons + scheduled scans + nightly DB backup.
FROM python:3.13-slim
# pango and harfbuzz for WeasyPrint (CV as PDF); Liberation Sans is metric-compatible with Arial;
# gnupg for the weekly encrypted backup
RUN apt-get update && apt-get install -y --no-install-recommends tzdata libpango-1.0-0 libpangoft2-1.0-0 \
    libharfbuzz-subset0 fonts-liberation gnupg && rm -rf /var/lib/apt/lists/*
ENV TZ=Europe/Warsaw PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY jobbot jobbot
COPY examples examples
# .env and facts.yaml are mounted at runtime, never baked into the image
CMD ["python", "-m", "jobbot.serve"]

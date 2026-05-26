FROM python:3.13-slim

# Install system dependencies (ffmpeg is needed for media processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 ytsubs \
    && useradd --uid 10001 --gid ytsubs --create-home --home-dir /home/ytsubs --shell /usr/sbin/nologin ytsubs

WORKDIR /app

COPY requirements.txt .
COPY ytsubs ./ytsubs

RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt \
    && mkdir -p /app/data /app/.cache /app/.config /app/downloads /app/mods \
    && chown -R ytsubs:ytsubs /app /home/ytsubs

ENV HOME=/home/ytsubs
USER ytsubs

ENTRYPOINT ["python", "-m", "ytsubs"]

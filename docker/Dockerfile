FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl aria2 ca-certificates openssh-client ffmpeg tini \
      && pip install --no-cache-dir yt-dlp \
      && apt-get clean && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY scripts/ scripts/
COPY config.example.json .
RUN useradd -m -r -s /usr/sbin/nologin pan && mkdir -p /data/download /data/state && \
      chown -R pan:pan /app /data
USER pan
ENV PAN_CONFIG=/data/state/config.json PAN_STATE_DIR=/data/state \
    PAN_LOG=/data/state/pan.log
EXPOSE 17890
ENTRYPOINT ["tini", "--", "python3", "scripts/pan.py"]
CMD ["serve", "--host", "0.0.0.0", "--port", "17890"]

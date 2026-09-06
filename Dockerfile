# One image, two roles: the site and the transcription worker.
FROM docker.io/library/python:3.12-slim-bookworm

# ffmpeg does every transcode; git versions data/ from inside the container.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/models \
    VEILLEE_DATA_DIR=/data \
    VEILLEE_DB_PATH=/data/veillee.db \
    VEILLEE_QUESTIONS_DIR=/app/questions

WORKDIR /app

# Dependencies first, so editing source does not re-resolve them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY questions ./questions
RUN uv sync --frozen --no-dev

# Bake the transcription model in, so the first recording in the morning is not
# waiting on a download. A failure here must NOT fail the build: the app is
# required to come up green with jobs simply sitting queued.
ARG WHISPER_MODEL=small
RUN mkdir -p /opt/models && \
    (python -c "from faster_whisper import WhisperModel; \
        WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8')" \
     && echo "model ${WHISPER_MODEL} baked in" \
     || echo "WARNING: could not pre-download ${WHISPER_MODEL}; jobs will queue until it can be fetched") \
    && chmod -R a+rX /opt/models

# The entrypoint works out the right uid at start-up, so no configuration is
# needed on either runtime. See docker-entrypoint.sh for why.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /data && chmod 777 /data /opt/models

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4).status==200 else 1)"

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["veillee", "serve", "--host", "0.0.0.0", "--port", "8000"]

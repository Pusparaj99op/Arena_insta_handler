# Everything the agent needs, in one image: ffmpeg with libass, Python, Node for
# Remotion/HyperFrames, and the repo itself.
#
#   docker build -t ig-agent .
#   docker run --rm -v $(pwd)/state:/app/state -v $(pwd)/build:/app/build \
#     --env-file automation/.env ig-agent doctor
#
# The two volumes matter: state/ is the queue and the conversations, build/ is
# what gets published. Everything else in the image is disposable.
FROM node:22-bookworm-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg from Debian ships libass, libfreetype and libx264, which is the set the
# renderer needs. A static build would also work but pins us to one host arch.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        python3 \
        python3-pip \
        ca-certificates \
        curl \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The engine has no Python dependencies, on purpose. Adding one here means every
# user needs it too, so it has to earn its place.
COPY automation ./automation
COPY brand ./brand
COPY examples ./examples
COPY .claude ./.claude
COPY state ./state
COPY build ./build

# Optional extras, in one layer so they can be dropped by rebuilding without this
# block: Pillow for image QA, faster-whisper for local caption timings.
RUN python3 -m pip install --break-system-packages --no-cache-dir \
        pillow \
    || echo "pillow install skipped; the renderer does not need it"

ENV PYTHONPATH=/app/automation

# The webhook is the only port this serves.
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -fsS http://127.0.0.1:8080/ || exit 1

CMD ["python3", "-m", "ig", "doctor"]

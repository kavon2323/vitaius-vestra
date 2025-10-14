# ---- Base: Blender headless worker (x86_64) ----
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1

# Core OS deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates gnupg2 xz-utils \
    python3 python3-pip python3-venv \
    libxi6 libxxf86vm1 libxfixes3 libxrender1 libxcomposite1 libasound2 \
    libgl1 libglx-mesa0 libegl1 libsm6 libice6 libx11-6 libxext6 libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

# Install Blender (3.6 LTS headless)
# You can bump BLENDER_VERSION to a newer LTS if needed.
ENV BLENDER_VERSION=3.6.15
RUN wget -q https://download.blender.org/release/Blender$BLENDER_VERSION/\
blender-$BLENDER_VERSION-linux-x64.tar.xz -O /tmp/blender.tar.xz && \
    mkdir -p /opt/blender && \
    tar -xf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 && \
    ln -s /opt/blender/blender /usr/local/bin/blender && \
    rm -f /tmp/blender.tar.xz

# Python deps for your worker scripts (adjust if you add S3/Redis later)
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install boto3 redis psycopg2-binary

WORKDIR /app
COPY . /app

# Default entrypoint (can be overridden by compose)
ENTRYPOINT ["/app/worker/entrypoint.sh"]

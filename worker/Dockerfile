FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y wget xz-utils python3 python3-pip libgl1 libxrender1 libxi6 libxxf86vm1 libxfixes3 libxext6 libx11-6 libxcursor1 libxinerama1 libsm6 libice6 libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

# Install Blender (headless build)
RUN wget -qO /tmp/blender.tar.xz https://download.blender.org/release/Blender4.0/blender-4.0.2-linux-x64.tar.xz \
 && tar -xJf /tmp/blender.tar.xz -C /usr/local/ \
 && mv /usr/local/blender-4.0.2-linux-x64 /usr/local/blender \
 && rm /tmp/blender.tar.xz
ENV BLENDER_PATH=/usr/local/blender/blender

# Python deps
RUN pip3 install boto3 redis rq python-dotenv

WORKDIR /app
COPY headless/ /app/headless/
COPY server/worker.py /app/worker.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]

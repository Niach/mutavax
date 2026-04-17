# Base: NVIDIA Parabricks 4.7.0-1 ships CUDA 12.9.1, GATK, samtools, and `pbrun`.
# We layer Python + FastAPI + the app's other tool chain (strobealign, pigz) on top.
FROM nvcr.io/nvidia/clara/clara-parabricks:4.7.0-1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG STROBEALIGN_VERSION=0.17.0
ARG GATK_VERSION=4.5.0.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-venv \
        python3-pip \
        pigz \
        curl \
        ca-certificates \
        build-essential \
        cmake \
        pkg-config \
        zlib1g-dev \
        libisal-dev \
        libzstd-dev \
        openjdk-17-jre-headless \
        unzip \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 100 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 100 \
    && rm -rf /var/lib/apt/lists/*

# GATK 4.x — Parabricks ships the GPU-accelerated subcommands via `pbrun`
# but not the standalone `gatk` wrapper. We need it for FilterMutectCalls
# (post-pbrun) and for the CPU Mutect2 fallback path.
RUN curl -fsSL \
        "https://github.com/broadinstitute/gatk/releases/download/${GATK_VERSION}/gatk-${GATK_VERSION}.zip" \
        -o /tmp/gatk.zip \
    && unzip -q /tmp/gatk.zip -d /opt \
    && mv "/opt/gatk-${GATK_VERSION}" /opt/gatk \
    && ln -sf /opt/gatk/gatk /usr/local/bin/gatk \
    && rm /tmp/gatk.zip

RUN curl -fsSL \
        "https://github.com/ksahlin/strobealign/archive/refs/tags/v${STROBEALIGN_VERSION}.tar.gz" \
        -o /tmp/strobealign.tar.gz \
    && tar -xzf /tmp/strobealign.tar.gz -C /tmp \
    && cmake -B "/tmp/strobealign-${STROBEALIGN_VERSION}/build" \
             -S "/tmp/strobealign-${STROBEALIGN_VERSION}" \
             -DCMAKE_BUILD_TYPE=Release \
    && make -C "/tmp/strobealign-${STROBEALIGN_VERSION}/build" -j"$(nproc)" \
    && install -m 0755 \
        "/tmp/strobealign-${STROBEALIGN_VERSION}/build/strobealign" \
        /usr/local/bin/strobealign \
    && rm -rf /tmp/strobealign*

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt

COPY backend/app /app/app
COPY backend/tests /app/tests
COPY pytest.ini /app/pytest.ini

ENV CANCERSTUDIO_APP_DATA_DIR=/app-data \
    CANCERSTUDIO_INBOX_DIR=/inbox \
    PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

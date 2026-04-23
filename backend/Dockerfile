# Combined cancerstudio image — FastAPI backend + Next.js frontend in a single
# container. Only port 3000 is exposed; Next.js rewrites /backend/* to the
# in-container backend on loopback 127.0.0.1:8000.
#
# Base: NVIDIA Parabricks 4.7.0-1 ships CUDA 12.9.1, GATK, samtools, and `pbrun`.
# We layer Python + FastAPI + the app's other tool chain (strobealign, pigz) +
# Node.js 22 + the built Next.js frontend on top.

# Stage 1: build the Next.js standalone bundle on a debian-slim node image
# (glibc matches the Parabricks/Ubuntu final stage).
FROM node:22-bookworm-slim AS web-builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci
COPY next.config.ts tsconfig.json postcss.config.mjs ./
COPY eslint.config.mjs ./
COPY public ./public
COPY src ./src
# src/lib/demo-fixtures.ts imports JSON fixtures from ../../backend/app/data.
COPY backend/app/data ./backend/app/data
RUN npm run build

# Stage 2: the full backend image with Node runtime + the prebuilt frontend.
FROM nvcr.io/nvidia/clara/clara-parabricks:4.7.0-1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG STROBEALIGN_VERSION=0.17.0
ARG GATK_VERSION=4.5.0.0
ARG VEP_RELEASE=111
ARG LINEARDESIGN_REF=main
ARG DIAMOND_VERSION=2.1.9

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-venv \
        python3.11-dev \
        python3.11-tk \
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
        git \
        perl \
        libperl-dev \
        libssl-dev \
        libdbi-perl \
        libarchive-zip-perl \
        libjson-perl \
        libwww-perl \
        libhttp-tiny-perl \
        libset-intervaltree-perl \
        libmodule-build-perl \
        libperlio-gzip-perl \
        libbio-perl-perl \
        libbio-db-hts-perl \
        libfile-copy-recursive-perl \
        tabix \
        tcsh \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 100 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 100 \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 LTS runtime for the Next.js standalone server.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
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

# DIAMOND — stage 6 self-identity safety check. BLAST-compatible
# short-peptide aligner used to match picked epitopes against the
# species-specific UniProt Swiss-Prot proteome. Much faster than
# classic BLAST on 8-11 aa queries, which is all we ever throw at it.
RUN curl -fsSL \
        "https://github.com/bbuchfink/diamond/releases/download/v${DIAMOND_VERSION}/diamond-linux64.tar.gz" \
        -o /tmp/diamond.tar.gz \
    && tar -xzf /tmp/diamond.tar.gz -C /tmp diamond \
    && install -m 0755 /tmp/diamond /usr/local/bin/diamond \
    && rm -f /tmp/diamond.tar.gz /tmp/diamond

# LinearDesign — stage 7 codon optimizer (Zhang et al. Nature 2023). The
# repo's `lineardesign` wrapper is python2-only; we skip it and call the
# compiled binary `bin/LinearDesign_2D` directly from our Python service.
RUN git clone --depth 1 --branch "${LINEARDESIGN_REF}" \
        https://github.com/LinearDesignSoftware/LinearDesign.git /opt/lineardesign \
    && make -C /opt/lineardesign \
    && ln -sf /opt/lineardesign/bin/LinearDesign_2D /usr/local/bin/LinearDesign_2D

# Ensembl VEP — installed natively so the backend can call `vep` as a subprocess
# like the other bioinformatics binaries. Bio::DB::HTS comes from the distro
# libbio-db-hts-perl package (Ubuntu 22.04 ships 3.01), avoiding a from-source
# cpanm build that requires libhts-dev headers. We install the Perl API only
# (no cache downloads at build time); caches are lazily downloaded per species
# on first annotation run and persisted to the host via the shared vep-cache
# volume.
RUN git clone --branch "release/${VEP_RELEASE}" --depth 1 \
        https://github.com/Ensembl/ensembl-vep.git /opt/vep \
    && cd /opt/vep \
    && perl INSTALL.pl --AUTO a --NO_HTSLIB --NO_TEST --NO_UPDATE \
    && ln -sf /opt/vep/vep /usr/local/bin/vep \
    && printf '#!/bin/sh\nexec perl /opt/vep/INSTALL.pl "$@"\n' > /usr/local/bin/vep_install \
    && chmod +x /usr/local/bin/vep_install

# VEP plugins: Ensembl's repo + the two pVACseq plugins (Frameshift, Wildtype)
# so stage 5 (neoantigen prediction) can be a drop-in consumer of stage-4
# output VCFs.
RUN git clone --branch "release/${VEP_RELEASE}" --depth 1 \
        https://github.com/Ensembl/VEP_plugins.git /opt/vep-plugins \
    && curl -fsSL \
        https://raw.githubusercontent.com/griffithlab/pVACtools/master/pvactools/tools/pvacseq/VEP_plugins/Wildtype.pm \
        -o /opt/vep-plugins/Wildtype.pm \
    && curl -fsSL \
        https://raw.githubusercontent.com/griffithlab/pVACtools/master/pvactools/tools/pvacseq/VEP_plugins/Frameshift.pm \
        -o /opt/vep-plugins/Frameshift.pm

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt \
    && python -m pip install "pvactools==5.4.0" "numpy<2" \
    # pvactools 5.4.0's pip wheel omits the cancer-hotspot gene list its
    # post-processing step requires. Fetch it from the matching GitHub tag;
    # without this file, pvacseq runs fail right before aggregation.
    # pvactools is a namespace package (no __file__), so resolve via a submodule.
    && PVAC_SUPPORT=$(python -c "import os, pvactools.tools; print(os.path.join(os.path.dirname(os.path.dirname(pvactools.tools.__file__)), 'supporting_files'))") \
    && mkdir -p "$PVAC_SUPPORT" \
    && curl -fsSL \
        https://raw.githubusercontent.com/griffithlab/pVACtools/v5.4.0/pvactools/supporting_files/cancer_census_hotspot_gene_list.tsv \
        -o "$PVAC_SUPPORT/cancer_census_hotspot_gene_list.tsv" \
    # MHCflurry is a license-free alternative to NetMHCpan for class-I binding
    # prediction. Pulled in transitively by pvactools 5.4.0 (pinned to 2.0.6),
    # but 2.0.6 was built against Keras 2.x and breaks on Keras 3.x. The
    # tf-keras package plus TF_USE_LEGACY_KERAS=1 restores compatibility;
    # see CLAUDE.md stage 5 for the runtime configuration.
    && python -m pip install tf-keras \
    # Pre-fetch the class-I pan models so first-run predictions don't block
    # on a 164 MB download. Stores at /root/.local/share/mhcflurry/...
    && mhcflurry-downloads fetch models_class1_pan

# Mount point for externally-licensed MHC binding predictors (NetMHCpan 4.2 +
# NetMHCIIpan 4.3). We cannot redistribute these, so the user drops the
# DTU-shipped install directories into ${CANCERSTUDIO_NETMHC_DIR} on the host;
# docker-compose bind-mounts that dir at /tools/src:ro so the stock DTU wrapper
# scripts (which hardcode NMHOME=/tools/src/netMHCpan-4.2 etc.) work with no
# user-side edits. pVACseq invokes the binaries via the env vars below.
RUN mkdir -p /tools/src

COPY backend/app /app/app
COPY backend/tests /app/tests
COPY pytest.ini /app/pytest.ini

# Prebuilt Next.js standalone frontend from stage 1.
COPY --from=web-builder /app/public /app/web/public
COPY --from=web-builder /app/.next/standalone /app/web
COPY --from=web-builder /app/.next/static /app/web/.next/static

COPY backend/entrypoint.sh /usr/local/bin/cancerstudio-entrypoint
RUN chmod +x /usr/local/bin/cancerstudio-entrypoint

ENV CANCERSTUDIO_APP_DATA_DIR=/app-data \
    CANCERSTUDIO_VEP_PLUGINS_DIR=/opt/vep-plugins \
    CANCERSTUDIO_VEP_RELEASE=111 \
    CANCERSTUDIO_NETMHC_DIR=/tools/src \
    CANCERSTUDIO_NETMHCPAN_BIN=/tools/src/netMHCpan-4.2/netMHCpan \
    CANCERSTUDIO_NETMHCIIPAN_BIN=/tools/src/netMHCIIpan-4.3/netMHCIIpan \
    TF_USE_LEGACY_KERAS=1 \
    PYTHONPATH=/app \
    INTERNAL_API_URL=http://127.0.0.1:8000 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

EXPOSE 3000

CMD ["/usr/local/bin/cancerstudio-entrypoint"]

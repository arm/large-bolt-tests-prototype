# syntax=docker/dockerfile:1.7

ARG TARGETPLATFORM=linux/arm64
ARG UBUNTU_IMAGE=ubuntu:24.04

FROM --platform=${TARGETPLATFORM} ${UBUNTU_IMAGE} AS builder

ARG BZIP2_VERSION=1.0.8
ARG BZIP2_SHA256=ab5a03176ee106d3f0fa90e381da478ddae405918153cca248e682cd0c4a2269

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        clang \
        curl \
        lld \
        make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN curl -fsSLO https://sourceware.org/pub/bzip2/bzip2-${BZIP2_VERSION}.tar.gz \
    && echo "${BZIP2_SHA256}  bzip2-${BZIP2_VERSION}.tar.gz" | sha256sum -c - \
    && tar -xzf bzip2-${BZIP2_VERSION}.tar.gz \
    && mv bzip2-${BZIP2_VERSION} src

WORKDIR /build/src

# Match the Nix recipe: force the link step to respect LDFLAGS.
RUN sed -i 's/$(CC) $(CFLAGS) -o bzip2 /$(CC) $(CFLAGS) $(LDFLAGS) -o bzip2 /' Makefile \
    && sed -i 's/$(CC) $(CFLAGS) -o bzip2recover /$(CC) $(CFLAGS) $(LDFLAGS) -o bzip2recover /' Makefile

RUN make -j"$(nproc)" \
        PREFIX=/opt/bzip2 \
        CC=clang \
        "CFLAGS+=-fPIC" \
        "CFLAGS+=-fPIE" \
        "CFLAGS+=-g" \
        "LDFLAGS+=-pie" \
        "LDFLAGS+=-fuse-ld=lld" \
        "LDFLAGS+=-Wl,--emit-relocs"

# bzip2's Makefile does not honor DESTDIR, so create the target layout first.
RUN mkdir -p /opt/bzip2/bin /opt/bzip2/lib /opt/bzip2/include /opt/bzip2/share/man/man1 \
    && make install PREFIX=/opt/bzip2

FROM scratch AS artifact
COPY --from=builder /opt/bzip2/ /


# syntax=docker/dockerfile:1

ARG JBROWSE_VERSION=4.3.0
ARG JBROWSE_SHA256=a9d42417102ee088a1cbf85c6d857c1065d66984ea6c56f3115ef9dd56d76702

FROM alpine:3.22 AS jbrowse

ARG JBROWSE_VERSION
ARG JBROWSE_SHA256

RUN apk add --no-cache curl unzip \
    && curl --fail --location --retry 3 \
        "https://github.com/GMOD/jbrowse-components/releases/download/v${JBROWSE_VERSION}/jbrowse-web-v${JBROWSE_VERSION}.zip" \
        --output /tmp/jbrowse-web.zip \
    && echo "${JBROWSE_SHA256}  /tmp/jbrowse-web.zip" | sha256sum -c - \
    && mkdir -p /out \
    && unzip -q /tmp/jbrowse-web.zip -d /out \
    && test -f /out/index.html

FROM nginxinc/nginx-unprivileged:1.29.1-alpine

USER root

COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/jbrowser.locations.conf /etc/nginx/snippets/jbrowser.locations.conf
COPY --chown=101:101 site/ /srv/jbrowser/site/
COPY --from=jbrowse --chown=101:101 /out/ /srv/jbrowser/app/

RUN mkdir -p /data/bundles \
    && chown 101:101 /data/bundles

USER 101

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

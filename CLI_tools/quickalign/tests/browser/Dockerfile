# Test-only pinned JBrowse renderer, adapted from cc_gcev's browser verifier.
FROM mcr.microsoft.com/playwright:v1.55.0-noble
USER root
RUN npm install --global --no-audit --no-fund \
        playwright@1.55.0 @jbrowse/cli@4.3.0 \
    && jbrowse create /opt/jbrowse --tag v4.3.0 --force
ENV NODE_PATH=/usr/local/lib/node_modules:/usr/lib/node_modules
WORKDIR /work

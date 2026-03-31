FROM jt/temp4:latest

# 1. Put primer3 binaries on PATH
ENV PATH="/primer3/src:${PATH}"

# 2. Install supervisord
RUN apt-get update && \
    apt-get install -y --no-install-recommends supervisor && \
    rm -rf /var/lib/apt/lists/*

# 3. Build the frontend to static files instead of running Parcel dev server
RUN cd /primer3plus/client && \
    echo 'API_URL=http://localhost:3300/api/v1' > .env.production && \
    npx parcel build src/index.html --dist-dir /primer3plus/client/dist --no-source-maps

# 4. Copy supervisord config
COPY supervisord.conf /etc/supervisor/conf.d/primer3plus.conf

EXPOSE 1234 3300

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/primer3plus.conf"]

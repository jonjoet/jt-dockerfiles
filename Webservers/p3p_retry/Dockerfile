FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    g++ \
    git \
    python3 \
    python3-flask \
    python3-flask-cors \
    nodejs \
    npm \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Build primer3 from source
RUN git clone --depth 1 https://github.com/primer3-org/primer3.git /primer3 && \
    cd /primer3/src && \
    make

ENV PATH="/primer3/src:${PATH}"

# Clone primer3plus
RUN git clone --depth 1 https://github.com/primer3-org/primer3plus.git /primer3plus

# Create data and log directories the server expects
RUN mkdir -p /primer3plus/data /primer3plus/log

# Install client dependencies and build static files
RUN cd /primer3plus/client && \
    npm install && \
    echo 'API_URL=http://localhost:3300/api/v1' > .env.production && \
    echo 'HELP_LINK_URL=primer3plusHelp.html' >> .env.production && \
    echo 'INDEX_LINK_URL=http://localhost:1234/index.html' >> .env.production && \
    npx parcel build src/index.html --no-cache --no-source-maps --public-url ./

# Copy supervisord config
COPY supervisord.conf /etc/supervisor/conf.d/primer3plus.conf

EXPOSE 1234 3300

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/primer3plus.conf"]

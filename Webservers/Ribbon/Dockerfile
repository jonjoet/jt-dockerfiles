FROM python:3.9-slim

WORKDIR /app

# Install dependencies for downloading and unzipping
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Download Ribbon release 2.1.0
# We use the specific release URL found during research
RUN wget https://github.com/MariaNattestad/Ribbon/releases/download/2.1.0/ribbon_splitthreader.zip \
    && unzip ribbon_splitthreader.zip \
    && rm ribbon_splitthreader.zip

# The release unzip creates a subdirectory named 'ribbon_splitthreader'
WORKDIR /app/ribbon_splitthreader

# Expose the default port for python http.server
EXPOSE 8000

# Start a simple HTTP server to serve the static files
CMD ["python3", "-m", "http.server", "8000"]

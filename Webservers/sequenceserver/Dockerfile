# SequenceServer Dockerfile (Alternative - Interactive Setup)
# This Dockerfile runs 'sequenceserver -s' by default.
# USE THIS WITH INTERACTIVE MODE: docker run -it -p 4567:4567 -v /path/to/db:/db my-seq-alt

# ARG for BLAST version
ARG BLAST_VERSION=2.16.0

## Stage 1: BLAST+ binaries
FROM ncbi/blast-static:${BLAST_VERSION} AS ncbi-blast

## Stage 2: Final Image
FROM ruby:3.2-bookworm

LABEL Description="SequenceServer Docker Image (Interactive Setup)"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy BLAST+ binaries
COPY --from=ncbi-blast \
  /blast/bin/blast_formatter \
  /blast/bin/blastdbcmd \
  /blast/bin/blastn \
  /blast/bin/blastp \
  /blast/bin/blastx \
  /blast/bin/makeblastdb \
  /blast/bin/tblastn \
  /blast/bin/tblastx \
  /blast/bin/

# Add BLAST+ binaries to PATH
ENV PATH=/blast/bin:${PATH}

# Install SequenceServer via RubyGems
RUN gem install sequenceserver

# Setup working directory and database directory
WORKDIR /sequenceserver
RUN mkdir /db

# Expose the default SequenceServer port
EXPOSE 4567

# Entrypoint
# Setting ENTRYPOINT to "sequenceserver" and CMD to "-s" means:
# 1. By default, it runs "sequenceserver -s" (Setup mode).
# 2. You can override CMD to run a normal server, e.g.:
#    docker run ... my-seq-alt sequenceserver (but wait, entrypoint is sequenceserver, so just pass empty? No.)
#    If ENTRYPOINT is ["sequenceserver"], then `docker run ... img` executes `sequenceserver -s`.
#    If you want to run the server normally (after setup is persisted or if you just want defaults), you would run:
#    `docker run ... img` -> runs setup? 
#    Actually, the default run command for SequenceServer IS just `sequenceserver` (which starts the server).
#    So having CMD ["-s"] makes the default the setup mode.
#    To run the server normally, the user would need to override CMD with empty string or specific args?
#    Better: Just run `docker run ... img` for setup. 
#    To run server: `docker run ... img` ? No, that runs setup.
#    To run server: `docker run ... img sequenceserver` -> `sequenceserver sequenceserver` (Error).
#    
#    Let's stick to the user's request: "runs sequenceserver -s as the entrypoint".
#    If I set ENTRYPOINT ["sequenceserver", "-s"], it ALWAYS runs -s.
#    That seems to be what the user wants for *this* specific file.
#    
#    However, `ENTRYPOINT ["sequenceserver"]` and `CMD ["-s"]` is more "Docker-idiomatic".
#    Default: `sequenceserver -s`.
#    Override: `docker run ... img -d /db` -> `sequenceserver -d /db` (Starts server).
#    This is perfect.

# Entrypoint & CMD
# We chain the setup command (-s) with the run command.
# This ensures that after the interactive setup finishes, the server starts immediately.
ENTRYPOINT []
CMD ["/bin/sh", "-c", "sequenceserver -s && echo 'Setup complete. Starting SequenceServer...' && sequenceserver"]

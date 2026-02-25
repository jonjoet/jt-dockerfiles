# Use the official micromamba image (lighter and faster than standard conda images)
FROM mambaorg/micromamba:1.5.8

# Set the working directory to a standard mount point
WORKDIR /data

# Install vulcan and its dependencies (minimap2, ngmlr, samtools) into the base environment.
# We use the 'base' environment to avoid needing complex activation scripts during runtime.
# Specifying channels (-c) ensures correct dependency resolution.
RUN micromamba install -y -n base -c bioconda -c conda-forge vulcan && \
    micromamba clean --all --yes

# The mambaorg/micromamba image uses a special entrypoint script to activate the environment.
# We prepend that script to the 'vulcan' command.
# This ensures 'vulcan' runs inside the conda environment automatically.
ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "vulcan"]

# Default command arguments (optional, can be overridden by user)
CMD ["--help"]

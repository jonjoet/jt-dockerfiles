# Micromamba base (lighter/faster than full conda images), mirroring the
# Vulcan CLI in this repo.
FROM mambaorg/micromamba:1.5.8

WORKDIR /data

# biopython powers the conversion; agat provides the optional GFF3 standardizer
# used by --validate (and pulls in Perl/BioPerl as a side effect).
RUN micromamba install -y -n base -c bioconda -c conda-forge \
        biopython \
        agat \
    && micromamba clean --all --yes

# The converter script lives outside /data so it is never shadowed by a mount.
COPY gb2gff_fna.py /opt/gb2gff_fna.py

# The mambaorg/micromamba entrypoint shim activates the base env, then runs the
# converter. User arguments are appended after the script path.
ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "python3", "/opt/gb2gff_fna.py"]
CMD ["--help"]

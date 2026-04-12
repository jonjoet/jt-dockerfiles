FROM quay.io/biocontainers/hmmer:3.4--hdbdd923_1

# ── System deps & Prodigal ───────────────────────────────────────────
USER root
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        wget ca-certificates prodigal && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Fetch the three RCR Rep Pfam profiles ────────────────────────────
#    PF01446 = Rep_1     (pC194/pUB110 family)
#    PF01719 = Rep_2     (pMV158 family)
#    PF02486 = Rep_trans (pT181/pC221 family)
#
#    We pull individual HMMs from the EBI Pfam REST API so we don't need
#    the full 1.5 GB Pfam-A.hmm file.
RUN mkdir -p /opt/rep_hmms && \
    for acc in PF01446 PF01719 PF02486; do \
        wget -q -O /opt/rep_hmms/${acc}.hmm \
            "https://www.ebi.ac.uk/interpro/wwwapi//entry/pfam/${acc}?annotation=hmm" ; \
    done && \
    cat /opt/rep_hmms/PF01446.hmm \
        /opt/rep_hmms/PF01719.hmm \
        /opt/rep_hmms/PF02486.hmm \
        > /opt/rep_hmms/Rep_RCR.hmm && \
    hmmpress /opt/rep_hmms/Rep_RCR.hmm

ENV REP_HMM_DB=/opt/rep_hmms/Rep_RCR.hmm

WORKDIR /data
ENTRYPOINT []
CMD ["bash"]

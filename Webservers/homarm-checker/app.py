from pathlib import Path
import tempfile
import pandas as pd
import streamlit as st
from homarm import HomarmError, arm_hit_rows, build_minimap2_command, candidate_rows, filter_arm_hits, normalize_sequence, pair_arm_hits, parse_paf, rows_to_tsv, run_minimap2, write_query_fasta

st.set_page_config(page_title="Homology-arm checker", layout="wide")
st.title("Yeast homology-arm off-target checker")
ref = st.file_uploader("Reference genome FASTA", type=["fa", "fasta", "fna"])
left = st.text_area("Left homology arm")
right = st.text_area("Right homology arm")
c1, c2, c3 = st.columns(3)
max_gap = c1.number_input("Maximum arm separation", 1, 1000000, 20000)
min_cov = c2.slider("Minimum arm coverage", 0.0, 1.0, 0.80)
min_id = c3.slider("Minimum arm identity", 0.0, 1.0, 0.90)

if st.button("Check homology arms", type="primary"):
    try:
        if ref is None:
            raise HomarmError("Upload a reference FASTA.")
        left_seq = normalize_sequence(left, "Left arm")
        right_seq = normalize_sequence(right, "Right arm")
        with tempfile.TemporaryDirectory(prefix="homarm_") as tmp:
            reference = Path(tmp) / "reference.fa"
            queries = Path(tmp) / "arms.fa"
            reference.write_bytes(ref.getvalue())
            write_query_fasta(queries, left_seq, right_seq)
            command = build_minimap2_command(reference, queries, max_gap=int(max_gap))
            run = run_minimap2(command)
        alignments = parse_paf(run.stdout)
        left_hits = filter_arm_hits(alignments, "left", min_coverage=min_cov, min_identity=min_id)
        right_hits = filter_arm_hits(alignments, "right", min_coverage=min_cov, min_identity=min_id)
        joined = [a for a in alignments if a.qname == "joined"]
        pairs = pair_arm_hits(left_hits, right_hits, max_gap=int(max_gap), joined_alignments=joined, left_length=len(left_seq), right_length=len(right_seq))
        st.session_state.result = (candidate_rows(pairs), arm_hit_rows(left_hits, "left") + arm_hit_rows(right_hits, "right"), run.stdout, run.stderr)
    except HomarmError as exc:
        st.error(str(exc))

if "result" in st.session_state:
    pairs, hits, paf, stderr = st.session_state.result
    st.metric("Compatible paired loci", len(pairs))
    st.subheader("Paired loci")
    if pairs:
        st.dataframe(pd.DataFrame(pairs), use_container_width=True, hide_index=True)
        st.download_button("Download paired loci TSV", rows_to_tsv(pairs), "homarm_paired_loci.tsv")
    else:
        st.info("No compatible pairs passed the thresholds.")
    st.subheader("Individual arm hits")
    if hits:
        st.dataframe(pd.DataFrame(hits), use_container_width=True, hide_index=True)
        st.download_button("Download arm hits TSV", rows_to_tsv(hits), "homarm_arm_hits.tsv")
    st.download_button("Download raw PAF", paf, "homarm_raw.paf")
    if stderr.strip():
        with st.expander("minimap2 diagnostics"):
            st.code(stderr)

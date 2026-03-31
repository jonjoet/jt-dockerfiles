import streamlit as st
import subprocess
import tempfile
import os
import shutil
from pathlib import Path

st.set_page_config(page_title="CHOPCHOP Guide Designer", layout="wide")
st.title("CHOPCHOP Cpf1 Guide RNA Designer")

# --- Form ---
with st.form("chopchop_form"):
    fasta_file = st.file_uploader("Upload target FASTA (required)", type=["fasta", "fa", "fna"])
    genbank_file = st.file_uploader("Upload GenBank for annotation (optional)", type=["gb", "gbk", "genbank"])

    col1, col2, col3 = st.columns(3)
    with col1:
        pam = st.text_input("PAM sequence", value="TTTM")
    with col2:
        guide_length = st.number_input("Guide length", min_value=20, max_value=25, value=21)
    with col3:
        max_mismatches = st.number_input("Max mismatches", min_value=0, max_value=5, value=3)

    submitted = st.form_submit_button("Run CHOPCHOP")

# --- Run ---
if submitted:
    if fasta_file is None:
        st.error("Please upload a FASTA file.")
    else:
        stem = Path(fasta_file.name).stem
        work_dir = tempfile.mkdtemp(prefix="chopchop_", dir="/tmp")

        try:
            fasta_path = os.path.join(work_dir, fasta_file.name)
            with open(fasta_path, "wb") as f:
                f.write(fasta_file.getvalue())

            genbank_path = None
            if genbank_file is not None:
                genbank_path = os.path.join(work_dir, genbank_file.name)
                with open(genbank_path, "wb") as f:
                    f.write(genbank_file.getvalue())

            out_dir = os.path.join(work_dir, f"{stem}_output")

            cmd = [
                "chopchop.py",
                "-Target", fasta_path,
                "-F",
                "-G", "ATCC13032",
                "-SC",
                "-scoringMethod", "KIM_2018",
                "-T", "3",
                "-M", pam,
                "--maxMismatches", str(max_mismatches),
                "-g", str(guide_length),
                "-t", "WHOLE",
                "--rm1perfOff",
                "-o", out_dir,
            ]

            with st.spinner("Running CHOPCHOP... this may take a minute."):
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                st.error("CHOPCHOP failed.")
                st.code(result.stderr, language="text")
            else:
                tsv_text = result.stdout
                tsv_filename = f"{stem}_guides.tsv"

                if result.stderr.strip():
                    st.session_state["chopchop_warnings"] = result.stderr

                if not tsv_text.strip():
                    st.warning("CHOPCHOP returned no results.")
                else:
                    st.session_state["tsv_text"] = tsv_text
                    st.session_state["tsv_filename"] = tsv_filename
                    st.session_state["annotated_gb"] = None

                    if genbank_path is not None:
                        annotated_path = os.path.join(work_dir, f"{stem}_annotated.gb")
                        tsv_path = os.path.join(work_dir, tsv_filename)
                        with open(tsv_path, "w") as f:
                            f.write(tsv_text)

                        annot_result = subprocess.run(
                            ["/app/annotate_targets.sh", genbank_path, tsv_path, annotated_path],
                            capture_output=True, text=True,
                        )

                        if annot_result.returncode != 0:
                            st.session_state["annot_error"] = annot_result.stderr
                        else:
                            with open(annotated_path, "r") as f:
                                st.session_state["annotated_gb"] = f.read()
                            st.session_state["annotated_filename"] = f"{stem}_annotated.gb"
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

# --- Display results (persists across reruns) ---
if "tsv_text" in st.session_state:
    if "chopchop_warnings" in st.session_state:
        with st.expander("CHOPCHOP warnings (stderr)"):
            st.code(st.session_state["chopchop_warnings"], language="text")

    st.download_button(
        "Download results TSV",
        data=st.session_state["tsv_text"],
        file_name=st.session_state["tsv_filename"],
        mime="text/tab-separated-values",
    )

    if st.session_state.get("annotated_gb") is not None:
        st.download_button(
            "Download annotated GenBank",
            data=st.session_state["annotated_gb"],
            file_name=st.session_state["annotated_filename"],
            mime="application/octet-stream",
        )
    elif "annot_error" in st.session_state:
        st.error("GenBank annotation failed.")
        st.code(st.session_state["annot_error"], language="text")

    with st.expander("Preview results", expanded=True):
        lines = st.session_state["tsv_text"].strip().split("\n")
        if len(lines) > 1:
            import pandas as pd
            header = lines[0].split("\t")
            rows = [line.split("\t") for line in lines[1:]]
            df = pd.DataFrame(rows, columns=header)
            st.dataframe(df, use_container_width=True)
        else:
            st.code(st.session_state["tsv_text"], language="text")

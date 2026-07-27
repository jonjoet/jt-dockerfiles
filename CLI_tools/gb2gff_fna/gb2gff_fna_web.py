#!/usr/bin/env python3
"""Streamlit interface for the GenBank to GFF3 + FASTA converter."""

import io
import os
import tempfile
import threading
import unicodedata
import warnings
import zipfile
from contextlib import redirect_stderr
from dataclasses import dataclass
from pathlib import Path

import streamlit as st
from Bio import SeqIO

import gb2gff_fna


_CONVERSION_LOCK = threading.Lock()


class ConversionError(ValueError):
    """Raised when an uploaded file cannot be converted."""


@dataclass(frozen=True)
class ConversionResult:
    """In-memory output from one web conversion."""

    prefix: str
    record_count: int
    total_bases: int
    feature_rows: int
    gff3: bytes
    fna: bytes
    archive: bytes
    diagnostics: str
    validated: bool | None


def output_prefix(uploaded_name, requested_prefix=""):
    """Return a safe basename for downloads and ZIP members."""
    candidate = requested_prefix.strip() or Path(uploaded_name).stem.strip()
    if not candidate:
        candidate = "converted"
    if (
        candidate in (".", "..")
        or "/" in candidate
        or "\\" in candidate
        or "\x00" in candidate
    ):
        raise ConversionError(
            "Output basename must be a filename, not a path."
        )
    if '"' in candidate or any(
        unicodedata.category(character).startswith("C")
        for character in candidate
    ):
        raise ConversionError(
            "Output basename cannot contain quotes or control characters."
        )
    if len(candidate) > 128:
        raise ConversionError("Output basename must be 128 characters or fewer.")
    return candidate


def _zip_outputs(prefix, gff3, fna):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{prefix}.gff3", gff3)
        archive.writestr(f"{prefix}.fna", fna)
    return buffer.getvalue()


def convert_upload(
    uploaded_bytes,
    uploaded_name,
    requested_prefix="",
    source="GenBank",
    validate=True,
):
    """Convert an uploaded GenBank document and return downloadable bytes."""
    if not uploaded_bytes:
        raise ConversionError("The uploaded file is empty.")
    source = source.strip()
    if not source:
        raise ConversionError("GFF3 source cannot be empty.")
    prefix = output_prefix(uploaded_name, requested_prefix)

    try:
        text = uploaded_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConversionError(
            "The uploaded GenBank file is not valid UTF-8 text."
        ) from exc

    diagnostics = io.StringIO()
    caught_warnings = []

    # The converter reports warnings through process-global stderr. Streamlit
    # serves sessions on threads, so serialize this short section to keep one
    # user's diagnostics from leaking into another user's result.
    with _CONVERSION_LOCK:
        with warnings.catch_warnings(record=True) as warning_records:
            warnings.simplefilter("always")
            with redirect_stderr(diagnostics):
                try:
                    records = list(SeqIO.parse(io.StringIO(text), "genbank"))
                except Exception as exc:
                    raise ConversionError(
                        f"Failed to parse the GenBank file: {exc}"
                    ) from exc
                if not records:
                    raise ConversionError(
                        "No GenBank records were found in the uploaded file."
                    )
                try:
                    gb2gff_fna.normalize_ids(records)
                except ValueError as exc:
                    raise ConversionError(str(exc)) from exc

                gff_text = "\n".join(gb2gff_fna.convert(records, source)) + "\n"
                fasta_handle = io.StringIO()
                SeqIO.write(records, fasta_handle, "fasta")
                fna_text = fasta_handle.getvalue()

                validated = None
                if validate:
                    temp_root = os.environ.get("GB2GFF_FNA_TMPDIR") or None
                    try:
                        with tempfile.NamedTemporaryFile(
                            mode="w",
                            encoding="utf-8",
                            suffix=".gff3",
                            dir=temp_root,
                        ) as gff_file:
                            gff_file.write(gff_text)
                            gff_file.flush()
                            validated = gb2gff_fna.validate_gff(gff_file.name)
                    except OSError as exc:
                        raise ConversionError(
                            f"Unable to create a temporary validation file: {exc}"
                        ) from exc
            caught_warnings = [
                f"{record.category.__name__}: {record.message}"
                for record in warning_records
            ]

    diagnostics_text = diagnostics.getvalue().strip()
    if caught_warnings:
        warning_text = "\n".join(caught_warnings)
        diagnostics_text = "\n".join(
            part for part in (warning_text, diagnostics_text) if part
        )
    gff3 = gff_text.encode("utf-8")
    fna = fna_text.encode("utf-8")
    return ConversionResult(
        prefix=prefix,
        record_count=len(records),
        total_bases=sum(len(record.seq) for record in records),
        feature_rows=sum(
            1
            for line in gff_text.splitlines()
            if line and not line.startswith("#")
        ),
        gff3=gff3,
        fna=fna,
        archive=_zip_outputs(prefix, gff3, fna),
        diagnostics=diagnostics_text,
        validated=validated,
    )


def _preview(data, max_lines):
    text = data.decode("utf-8")
    lines = text.splitlines()
    preview = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        preview += f"\n… {len(lines) - max_lines:,} more line(s)"
    return preview


def main():
    st.set_page_config(
        page_title="GenBank → GFF3 + FASTA",
        page_icon="🧬",
        layout="centered",
    )
    st.title("GenBank → GFF3 + FASTA")
    st.write(
        "Upload a GenBank file and download a standards-conscious GFF3 "
        "annotation plus nucleotide FASTA."
    )

    with st.form("conversion"):
        uploaded = st.file_uploader(
            "GenBank file",
            type=["gb", "gbk", "genbank"],
            help="Single- or multi-record GenBank; circular records are supported.",
        )
        prefix = st.text_input(
            "Output basename (optional)",
            placeholder="Defaults to the uploaded filename",
        )
        source = st.text_input(
            "GFF3 source",
            value="GenBank",
            help="Value written to column 2 of each GFF3 feature row.",
        )
        validate = st.checkbox(
            "Validate the generated GFF3",
            value=True,
            help="Reports structural problems without rewriting the annotation.",
        )
        submitted = st.form_submit_button(
            "Convert",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        st.session_state.pop("conversion_result", None)
        if uploaded is None:
            st.error("Choose a GenBank file first.")
        else:
            try:
                with st.spinner("Converting…"):
                    result = convert_upload(
                        uploaded.getvalue(),
                        uploaded.name,
                        requested_prefix=prefix,
                        source=source,
                        validate=validate,
                    )
            except ConversionError as exc:
                st.error(str(exc))
            else:
                st.session_state["conversion_result"] = result

    result = st.session_state.get("conversion_result")
    if result is None:
        return

    if result.validated is False:
        st.warning(
            "Conversion finished, but the generated GFF3 did not pass "
            "validation. The files are retained for inspection."
        )
        if result.diagnostics:
            with st.expander("Validation diagnostics", expanded=True):
                st.code(result.diagnostics, language="text")
    else:
        validation_note = (
            " and passed validation" if result.validated is True else ""
        )
        st.success(f"Converted {result.prefix}{validation_note}.")

    records_col, bases_col, features_col = st.columns(3)
    records_col.metric("Records", f"{result.record_count:,}")
    bases_col.metric("Bases", f"{result.total_bases:,}")
    features_col.metric("Feature rows", f"{result.feature_rows:,}")

    st.download_button(
        "Download both files (.zip)",
        data=result.archive,
        file_name=f"{result.prefix}.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True,
    )
    gff_col, fasta_col = st.columns(2)
    with gff_col:
        st.download_button(
            "Download GFF3",
            data=result.gff3,
            file_name=f"{result.prefix}.gff3",
            mime="text/plain",
            use_container_width=True,
        )
    with fasta_col:
        st.download_button(
            "Download FASTA",
            data=result.fna,
            file_name=f"{result.prefix}.fna",
            mime="text/plain",
            use_container_width=True,
        )

    if result.diagnostics and result.validated is not False:
        with st.expander("Conversion diagnostics"):
            st.code(result.diagnostics, language="text")

    gff_tab, fasta_tab = st.tabs(["GFF3 preview", "FASTA preview"])
    with gff_tab:
        st.code(_preview(result.gff3, 100), language="text")
    with fasta_tab:
        st.code(_preview(result.fna, 40), language="text")


if __name__ == "__main__":
    main()

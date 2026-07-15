# Not just dockerfiles!

This repository holds various dockerfiles, devcontainer specs, background services, and standalone browser tools for bioinformatics and molecular biology work.

## CLI Tools

Dockerfiles for command-line utilities. Meant to be run with `docker run`. All wrap publicly available software, with some customization.

| Tool | Description |
|------|-------------|
| [askcos2xlsx](CLI_tools/askcos2xlsx/) | Convert an ASKCOS retrosynthesis Tree Builder export to an Excel workbook (routes, steps, chemicals, reaction schemes) |
| [ColonyGroundedSAM2](CLI_tools/ColonyGroundedSAM2/) | GPU-accelerated colony segmentation with Grounded SAM2 |
| [gb2gff_fna](CLI_tools/gb2gff_fna/) | Convert GenBank to GFF3 + nucleotide FASTA (tuned for Benchling plasmid maps) |
| [Hashdeep](CLI_tools/Hashdeep/) | Recursive file hashing for verifying large-scale transfers |
| [jt_escher](CLI_tools/jt_escher/) | Escher metabolic pathway map CLI renderer |
| [ml_colonies](CLI_tools/ml_colonies/) | ML-based colony counting |
| [PlasAnn_CLI](CLI_tools/PlasAnn_CLI/) | Plasmid annotation (oriV, rep genes, CDS, etc.) |
| [PRO-barcodes](CLI_tools/PRO-barcodes/) | Nanopore-compatible DNA barcode design (PRO algorithm) |
| [TDFPS](CLI_tools/TDFPS/) | GPU-accelerated nanopore barcode design (TDFPSDesigner) |
| [Vulcan](CLI_tools/Vulcan/) | Two-pass long-read mapping (minimap2 + NGMLR) |
| [xlsx2csv](CLI_tools/xlsx2csv/) | Excel to CSV conversion |

## Webservers

Dockerfiles for tools that run as live web pages. Meant to be run on a VM and served via ports forwarded over SSH.

| Tool | Description |
|------|-------------|
| [ccccui](Webservers/ccccui/) | Web UI for Cpf1 (Cas12a) guide RNA design via CHOPCHOP |
| [D-genies](Webservers/D-genies/) | Interactive dot-plot visualization of genome alignments |
| [p3p_retry](Webservers/p3p_retry/) | Primer3Plus web interface |
| [Ribbon](Webservers/Ribbon/) | Structural variant visualization from split/supplementary alignments |
| [sequenceserver](Webservers/sequenceserver/) | Web frontend for BLAST+ searches against custom databases |

## Dev Containers

Devcontainer specs (devcontainer.json + optional Dockerfiles/scripts) for data analysis and development in Python, R, etc.

| Container | Description |
|-----------|-------------|
| [jt_dna](Dev_containers/jt_dna/) | DNA construct design (Edinburgh Genome Foundry suite + pydna) |
| [jt_FBA](Dev_containers/jt_FBA/) | Flux balance analysis and metabolic modeling |
| [jt_latex](Dev_containers/jt_latex/) | LaTeX document authoring |
| [jt_quarto](Dev_containers/jt_quarto/) | Data analysis in R (tidyverse + Quarto), with Python via reticulate |

## Services

Long-running or scheduled background jobs, meant to run unattended on a VM (e.g. as a systemd service/timer). Each ships a setup guide in place of a Dockerfile.

| Service | Description |
|---------|-------------|
| [Plasmidsaurus_AutoDownloader](Services/Plasmidsaurus_AutoDownloader/) | Stdlib-only Python script that auto-downloads finished Plasmidsaurus sequencing orders to a mounted share on a schedule (see [SETUP.md](Services/Plasmidsaurus_AutoDownloader/SETUP.md)) |

## Standalone HTML

JavaScript apps designed to be shared as single HTML files and run in the browser without installation. Extremely portable and convenient.

| Tool | Description |
|------|-------------|
| [assembly_filter](Standalone_HTML/assembly_filter/) | Filter junk contigs/scaffolds from genome assemblies by length |
| [fasta_gff_combiner](Standalone_HTML/fasta_gff_combiner/) | Combine sequences from multiple FASTAs (+ matching GFFs) into one or more composite genomes — e.g. chromosome + plasmids → strain |
| [har-sanitizer](Standalone_HTML/har-sanitizer/) | Convenient single-file build of [Cloudflare's HAR Sanitizer](https://github.com/cloudflare/har-sanitizer) — redact cookies, tokens & secrets from HAR files before sharing |
| [dna_spec](Standalone_HTML/dna_spec/) | Drag-and-drop assembly of reusable DNA parts into constructs (WIP) |
| [rescount](Standalone_HTML/rescount/) | Count restriction enzyme cut sites across multi-FASTA sequences |

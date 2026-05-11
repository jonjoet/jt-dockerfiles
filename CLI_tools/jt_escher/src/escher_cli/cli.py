"""CLI entry point for generating standalone Escher HTML maps."""

import argparse
import sys
from importlib.resources import files
from pathlib import Path

from escher import Builder

from .data_loader import load_data_file, load_map, load_model

CDN_SCRIPT_TAG = (
    '<script src="https://unpkg.com/escher@1.7.3/dist/escher.min.js"></script>'
)


def inline_escher_js(html_path):
    """Replace the CDN <script> tag with an inlined copy of escher.min.js.

    Escher 1.7.3's save_html() always emits the CDN tag; we read the JS bundle
    shipped inside the escher package and swap it in so the HTML works offline
    and keeps working if unpkg stops serving this version.
    """
    js = files("escher").joinpath("static/escher.min.js").read_text(encoding="utf-8")
    path = Path(html_path)
    html = path.read_text(encoding="utf-8")
    if html.count(CDN_SCRIPT_TAG) != 1:
        raise RuntimeError(
            f"Expected exactly one CDN <script> tag in {html_path}; "
            "escher template may have changed."
        )
    html = html.replace(CDN_SCRIPT_TAG, f"<script>{js}</script>")
    path.write_text(html, encoding="utf-8")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="escher-cli",
        description="Generate standalone Escher metabolic pathway HTML files.",
    )
    parser.add_argument("output", help="Output HTML file path")

    map_group = parser.add_mutually_exclusive_group()
    map_group.add_argument("--map-name", help="Community map name (e.g. 'iJO1366.Central metabolism')")
    map_group.add_argument("--map-file", help="Path to local Escher map JSON file")

    model_group = parser.add_mutually_exclusive_group()
    model_group.add_argument("--model-sbml", help="Path to SBML model file")
    model_group.add_argument("--model-json", help="Path to Escher-compatible model JSON file")

    parser.add_argument("--reaction-data", help="Reaction data file (CSV/TSV or JSON)")
    parser.add_argument("--metabolite-data", help="Metabolite data file (CSV/TSV or JSON)")
    parser.add_argument(
        "--cdn",
        action="store_true",
        help="Keep CDN script tag instead of inlining JS (requires internet to view)",
    )

    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    map_name, map_json = load_map(args.map_name, args.map_file)
    model_json = load_model(args.model_sbml, args.model_json)

    reaction_data = load_data_file(args.reaction_data) if args.reaction_data else None
    metabolite_data = load_data_file(args.metabolite_data) if args.metabolite_data else None

    builder = Builder(
        map_name=map_name,
        map_json=map_json,
        model_json=model_json,
        reaction_data=reaction_data,
        metabolite_data=metabolite_data,
        enable_keys=True,
        enable_search=True,
    )
    builder.save_html(args.output)
    if not args.cdn:
        inline_escher_js(args.output)
    print(f"Saved: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()

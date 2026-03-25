"""Helpers for loading map, model, and data overlay files."""

import json
import os
import tempfile

import pandas as pd


def load_data_file(path):
    """Load a reaction or metabolite data file (CSV/TSV or JSON) into a dict.

    CSV/TSV: uses first column as keys, second column as values.
    JSON: expects a flat {id: value} mapping.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext in (".csv", ".tsv"):
        sep = "\t" if ext == ".tsv" else ","
        df = pd.read_csv(path, sep=sep)
        if df.shape[1] < 2:
            raise ValueError(
                f"{path}: expected at least 2 columns (id, value), got {df.shape[1]}"
            )
        return dict(zip(df.iloc[:, 0].astype(str), df.iloc[:, 1].astype(float)))

    if ext == ".json":
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a JSON object (dict), got {type(data).__name__}")
        return {str(k): float(v) for k, v in data.items()}

    raise ValueError(f"{path}: unsupported format '{ext}' (use .csv, .tsv, or .json)")


def load_map(map_name, map_file):
    """Return (map_name, map_json) for the Builder constructor.

    Exactly one or neither should be provided.
    """
    if map_file:
        with open(map_file) as f:
            return None, f.read()
    return map_name, None


def load_model(model_sbml, model_json):
    """Load a model and return an Escher-compatible JSON string, or None."""
    if model_json:
        with open(model_json) as f:
            return f.read()

    if model_sbml:
        from cobra.io import read_sbml_model, save_json_model

        model = read_sbml_model(model_sbml)
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        try:
            tmp.close()
            save_json_model(model, tmp.name)
            with open(tmp.name) as f:
                return f.read()
        finally:
            os.unlink(tmp.name)

    return None

"""Run explicitly inside the installed runtime image, without a source mount.

Mount fixture inputs at /inputs, empty outputs at /outputs, and work at /work.
The caller creates RUN.txt and preserves stdout and these directories.
"""
import json
from pathlib import Path

import quickalign
from quickalign import jobs
from quickalign.ui.paths import Selection
from streamlit.testing.v1 import AppTest


def main():
    package = Path(quickalign.__file__).resolve()
    assert "site-packages" in package.parts, package
    output = Path("/outputs")
    assert not list(output.iterdir()), "Use a fresh output directory"
    app = AppTest.from_file("/opt/quickalign/streamlit_app.py", default_timeout=120).run()
    assert not app.exception

    for key, name in (("reference", "reference.fasta"),
                      ("annotation", "annotation.gff3"),
                      ("read_0_r1", "single.fastq")):
        app.selectbox(key=f"{key}_file_0_.").select(
            (name, False, Selection(0, name))
        ).run()
        app.button(key=f"{key}_use").click().run()
        assert not app.exception
    assert not list(output.iterdir()), "File selection must not submit a job"
    app.text_input(key="sample_name").set_value("installed-smoke").run()
    app.text_input(key="read_0_label").set_value("Visible warning track").run()
    next(button for button in app.button if button.label == "Build bundle").click().run()
    assert not app.exception
    job_dir, = output.iterdir()
    metadata = jobs.read_metadata(job_dir)
    assert metadata["status"] == "completed", metadata
    assert metadata["warnings"], "The fixture must end with an incomplete single record"
    assert any("incomplete" in warning.value for warning in app.warning)
    assert any("Bundle available" in success.value for success in app.success)
    assert metadata["tracks"][0]["mapped"] > 0

    next(button for button in app.button if button.label == "Prepare ZIP download").click().run()
    assert not app.exception
    metadata = jobs.read_metadata(job_dir)
    assert metadata["status"] == metadata["export_status"] == "completed"
    assert app.get("download_button"), "The finished small ZIP must be offered"
    archive = jobs.downloadable_archive(job_dir, 128 * 1024**2)
    assert archive and archive.is_file()
    app.run()
    assert not app.exception
    assert len(list(output.iterdir())) == 1, "Rendering results must not submit again"
    print(json.dumps({"package": str(package), "job": str(job_dir),
                      "archive": str(archive), "warnings": metadata["warnings"],
                      "checks": ["installed package and launcher", "selection without submission",
                                 "actual build", "rendered truncation warning", "disk ZIP export",
                                 "deferred download offered", "repeat result rendering"]}, indent=2))


if __name__ == "__main__":
    main()

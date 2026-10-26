"""Generated filenames keep recorded case independently of chart name formatting."""

import pytest

from kincade.cli import main

from conftest import ged
from kincade_web import Session


@pytest.mark.parametrize("fan", [False, True], ids=["pedigree", "fan"])
@pytest.mark.parametrize("preserve", [False, True])
def test_cli_filename_keeps_recorded_case_while_pdf_obeys_display_case(
    tmp_path, fan, preserve
):
    source = tmp_path / "family.ged"
    source.write_bytes(ged("0 @R@ INDI", "1 NAME Alice /McClure/", "1 DEAT Y"))
    flags = (["--fan"] if fan else []) + (["--preserve-case"] if preserve else [])
    assert main([str(source), "--root", "R", *flags]) == 0
    suffix = "fan chart" if fan else "cascading pedigree"
    filename = f"Alice McClure {suffix}.pdf"
    assert [p.name for p in tmp_path.glob("*.pdf")] == [filename]
    pdf = (tmp_path / filename).read_bytes()
    displayed = "Alice McClure" if preserve else "Alice McCLURE"
    assert f"/Title ({displayed}".encode() in pdf if fan else displayed.encode() in pdf


@pytest.mark.parametrize("fan", [False, True], ids=["pedigree", "fan"])
@pytest.mark.parametrize("override", ["flag", "config"])
def test_explicit_filename_keeps_exact_spelling_and_case(tmp_path, fan, override):
    source = tmp_path / "family.ged"
    source.write_bytes(ged("0 @R@ INDI", "1 NAME Alice /McClure/", "1 DEAT Y"))
    filename = "MY Chosen NAME.pdf"
    if override == "flag":
        flags = ["-o", filename]
    else:
        config = tmp_path / "options.toml"
        config.write_text(f'output = "{filename}"\n')
        flags = ["--config", str(config)]
    assert main([str(source), "--root", "R", *(["--fan"] if fan else []), *flags]) == 0
    assert [p.name for p in tmp_path.glob("*.pdf")] == [filename]


@pytest.mark.parametrize("chart", ["pedigree", "fan"])
@pytest.mark.parametrize("preserve", [False, True])
def test_browser_download_filename_keeps_recorded_case(chart, preserve):
    session = Session()
    session.open(ged("0 @R@ INDI", "1 NAME Alice /McClure/", "1 DEAT Y"))
    pdf, filename, _ = session.render("R", chart, {"preserve_case": preserve})
    suffix = "fan chart" if chart == "fan" else "cascading pedigree"
    assert filename == f"Alice McClure {suffix}.pdf"
    assert pdf.startswith(b"%PDF")


@pytest.mark.parametrize("fan", [False, True], ids=["pedigree", "fan"])
@pytest.mark.parametrize("language,label", [("en", "Living"), ("de", "Lebende Person")])
def test_cli_generated_filename_keeps_localized_privacy_label(
    tmp_path, fan, language, label
):
    source = tmp_path / "family.ged"
    source.write_bytes(
        ged("0 @R@ INDI", "1 NAME Alice /McClure/", "1 BIRT", "2 DATE 2000")
    )
    assert (
        main(
            [
                str(source),
                "--root",
                "R",
                "--exclude-private",
                "--lang",
                language,
                *(["--fan"] if fan else []),
            ]
        )
        == 0
    )
    filenames = [p.name for p in tmp_path.glob("*.pdf")]
    assert len(filenames) == 1 and label in filenames[0]
    assert "Alice" not in filenames[0] and "McClure" not in filenames[0]

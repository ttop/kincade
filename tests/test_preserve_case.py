"""Surname case is a display choice; matching, sorting and privacy stay intact."""

from copy import deepcopy

import pytest

from kincade import FanOptions, Options, plan_fan, render, render_fan
from kincade.charts import nobody_living, plan_charts
from kincade.cli import main
from kincade.gedcom import read_gedcom
from kincade.lang import display_name, index_name
from kincade.pdf import build_index, render_with_counts

from conftest import FIX, TODAY, ged
from kincade_web import Session
from pdfread import _text, drawn, text_objects


@pytest.mark.parametrize("surname", ["van Riper", "McClure", "de la Cruz", "mIxEd"])
def test_preserve_case_draws_recorded_names_and_index_without_mutating_tree(surname):
    tree = read_gedcom(
        ged("0 @I1@ INDI", f"1 NAME Dr. Alice /{surname}/ Jr.", "1 DEAT Y")
    )
    original = deepcopy(tree)
    result = render_with_counts(
        tree, "I1", Options(preserve_case=True, fonts="base14", compress=False)
    )
    assert f"Dr. Alice {surname} Jr." in drawn(result.pdf)
    assert any(f"{surname}, Dr. Alice Jr." in row for row in drawn(result.pdf))
    assert result.root_name == f"Dr. Alice {surname} Jr."
    assert result.root_name in _text(result.pdf)
    assert display_name(tree.people["I1"], preserve_case=True) == result.root_name
    assert (
        index_name(tree.people["I1"], preserve_case=True) == f"{surname}, Dr. Alice Jr."
    )
    assert tree == original


def test_preserve_case_keeps_index_order():
    tree = read_gedcom((FIX / "pedigree.ged").read_bytes())
    charts = plan_charts(tree, "I1", None)
    upper = build_index(tree, charts, nobody_living, False)
    kept = build_index(tree, charts, nobody_living, False, preserve_case=True)
    assert [line.casefold() for line in upper] == [line.casefold() for line in kept]
    assert upper != kept


def test_preserve_case_does_not_reveal_living_identity():
    tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Alice /McClure/", "1 BIRT", "2 DATE 2000")
    )
    pdf = render(
        tree,
        "I1",
        Options(
            preserve_case=True,
            exclude_private=True,
            fonts="base14",
            compress=False,
            today=TODAY,
        ),
    )
    assert "Living" in drawn(pdf)
    assert b"Alice" not in pdf and b"McClure" not in pdf


@pytest.mark.parametrize("mode", ["--find", "--root"])
def test_cli_preserves_case_in_search_and_ambiguous_candidates(mode, capsys):
    code = main([str(FIX / "pedigree.ged"), mode, "mcclure", "--preserve-case"])
    captured = capsys.readouterr()
    assert code == (0 if mode == "--find" else 2)
    listing = captured.out if mode == "--find" else captured.err
    assert "I3\tMary McClure\t1952-" in listing
    assert "I6\tWilliam McCLURE\t1925-1999" in listing


def test_cli_config_preserves_case_and_default_filename(tmp_path, capsys):
    config = tmp_path / "case.toml"
    config.write_text("preserve_case = true\n")
    assert (
        main([str(FIX / "pedigree.ged"), "--root", "I3", "--config", str(config)]) == 0
    )
    assert (tmp_path / "Mary McClure cascading pedigree.pdf").is_file()
    capsys.readouterr()
    assert (
        main([str(FIX / "pedigree.ged"), "--find", "I3", "--config", str(config)]) == 0
    )
    assert "Mary McClure" in capsys.readouterr().out


def test_cli_preserve_case_privacy_and_fan_mode(tmp_path, capsys):
    assert (
        main(
            [
                str(FIX / "pedigree.ged"),
                "--find",
                "I1",
                "--preserve-case",
                "--exclude-private",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == "I1\tLiving\t\n    F101\tLiving\t(default)\n"
    assert (
        main([str(FIX / "pedigree.ged"), "--root", "I1", "--fan", "--preserve-case"])
        == 0
    )
    assert (tmp_path / "Jane ASHFORD fan chart.pdf").is_file()


def test_browser_preserves_case_in_pedigree_pdf_and_filename():
    session = Session()
    session.open((FIX / "pedigree.ged").read_bytes())
    pdf, filename, _ = session.render("I3", "pedigree", {"preserve_case": True})
    assert filename == "Mary McClure cascading pedigree.pdf"
    assert pdf.startswith(b"%PDF")
    assert (
        session.render("I3", "fan", {"preserve_case": True})[1]
        == "Mary McClure fan chart.pdf"
    )


def test_preserve_case_config_requires_a_boolean(tmp_path, capsys):
    config = tmp_path / "case.toml"
    config.write_text('preserve_case = "yes"\n')
    assert main(["--config", str(config), "--show-config"]) == 2
    assert "preserve_case" in capsys.readouterr().err


@pytest.mark.parametrize(
    "surname,upper",
    [("van Riper", "VAN RIPER"), ("McClure", "McCLURE"), ("de la Cruz", "DE LA CRUZ")],
)
@pytest.mark.parametrize("preserve", [False, True])
def test_fan_case_applies_to_cells_title_and_metadata_without_mutating_tree(
    surname, upper, preserve
):
    tree = read_gedcom(ged("0 @I1@ INDI", f"1 NAME Alice /{surname}/", "1 DEAT Y"))
    original = deepcopy(tree)
    fan = plan_fan(tree, "I1", preserve_case=preserve)
    expected = surname if preserve else upper
    assert fan.cells[0].surname == expected
    assert fan.name == f"Alice {expected}"
    pdf = render_fan(fan, FanOptions(fonts="base14", compress=False))
    strings = [text for text, _ in text_objects(pdf)]
    assert fan.name in strings
    assert f"{fan.name} — Fan chart" in strings
    assert fan.name in _text(pdf)
    assert tree == original


@pytest.mark.parametrize("setting", ["default", "flag", "config"])
def test_cli_fan_case_controls_metadata_but_keeps_recorded_filename(tmp_path, setting):
    gedcom = tmp_path / "names.ged"
    gedcom.write_bytes(ged("0 @I1@ INDI", "1 NAME Alice /McClure/", "1 DEAT Y"))
    flags = []
    if setting == "flag":
        flags = ["--preserve-case"]
    elif setting == "config":
        config = tmp_path / "case.toml"
        config.write_text("preserve_case = true\n")
        flags = ["--config", str(config)]
    assert main([str(gedcom), "--root", "alice mcclure", "--fan", *flags]) == 0
    name = "Alice McCLURE" if setting == "default" else "Alice McClure"
    filename = "Alice McClure fan chart.pdf"
    assert [p.name for p in tmp_path.glob("*.pdf")] == [filename]
    assert f"/Title ({name}".encode() in (tmp_path / filename).read_bytes()


def test_fan_preserving_case_still_conceals_living_names():
    tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Alice /McClure/", "1 BIRT", "2 DATE 2000")
    )
    original = deepcopy(tree)
    fan = plan_fan(tree, "I1", preserve_case=True, exclude_private=True)
    assert fan.name == "Living"
    assert fan.cells[0].surname == "" and fan.cells[0].given == "Living"
    pdf = render_fan(fan, FanOptions(fonts="base14", compress=False))
    assert b"Alice" not in pdf and b"McClure" not in pdf
    assert tree == original


@pytest.mark.parametrize(
    "preserve,name", [(False, "Mary McCLURE"), (True, "Mary McClure")]
)
def test_browser_fan_accepts_casing_setting_and_names_download(preserve, name):
    session = Session()
    session.open((FIX / "pedigree.ged").read_bytes())
    pdf, filename, _ = session.render("I3", "fan", {"preserve_case": preserve})
    assert pdf.startswith(b"%PDF")
    assert filename == "Mary McClure fan chart.pdf"
    assert name.encode() in pdf

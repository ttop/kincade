"""Private chart exports redact identities without changing the source tree."""

from copy import deepcopy

import pytest

from kincade import FanOptions, Options, plan_fan, render_fan
from kincade.cli import main
from kincade.gedcom import read_gedcom
from kincade.pdf import render_with_counts

from conftest import TODAY, ged
from kincade_web import Session
from pdfread import _text, drawn, text_objects


def private_tree():
    return read_gedcom(
        ged(
            "0 @SECRET-ID@ INDI",
            "1 NAME Jane /Secret/",
            "2 NPFX Dr.",
            "2 NSFX Jr.",
            "1 BIRT",
            "2 DATE 1990",
            "2 PLAC Hidden birthplace",
            "1 FAMC @F1@",
            "2 PEDI adopted",
            "0 @PUBLIC-ID@ INDI",
            "1 NAME John /Public/",
            "1 DEAT Y",
            "0 @F1@ FAM",
            "1 HUSB @PUBLIC-ID@",
        )
    )


@pytest.mark.parametrize("chart", ["pedigree", "fan"])
@pytest.mark.parametrize(
    "lang,label",
    [
        (None, "Living"),
        ("de", "Lebende Person"),
        ({"living_name": "Private"}, "Private"),
    ],
)
def test_private_pdf_redacts_identity_in_text_and_metadata(chart, lang, label):
    tree = private_tree()
    original = deepcopy(tree)
    if chart == "pedigree":
        result = render_with_counts(
            tree,
            "SECRET-ID",
            Options(
                exclude_private=True,
                show_ids=True,
                lang=lang,
                fonts="base14",
                compress=False,
                today=TODAY,
            ),
        )
        pdf = result.pdf
        text = drawn(pdf)
    else:
        fan = plan_fan(tree, "SECRET-ID", exclude_private=True, lang=lang)
        assert fan.name == label
        pdf = render_fan(
            fan, FanOptions(lang=lang, fonts="base14", compress=False, today=TODAY)
        )
        text = [t for t, _ in text_objects(pdf)]
    assert label in text
    for secret in (
        "Jane",
        "Dr.",
        "Jr.",
        "Secret",
        "SECRET-ID",
        "Hidden birthplace",
        "1990",
        "adopted",
    ):
        assert secret.casefold() not in " ".join(text).casefold()
        assert secret.casefold() not in _text(pdf).casefold()
    assert "John" in " ".join(text)
    assert tree == original


@pytest.mark.parametrize(
    "chart,lang,filename",
    [
        ("pedigree", None, "Living cascading pedigree.pdf"),
        ("fan", None, "Living fan chart.pdf"),
        ("pedigree", "de", "Ahnentafel Lebende Person.pdf"),
        ("fan", "de", "Fächerahnentafel Lebende Person.pdf"),
    ],
)
def test_cli_default_filename_redacts_living_root(
    tmp_path, capsys, chart, lang, filename
):
    path = tmp_path / "private.ged"
    path.write_bytes(ged("0 @I1@ INDI", "1 NAME Jane /Secret/"))
    args = [str(path), "--root", "I1", "--exclude-private"]
    if chart == "fan":
        args.append("--fan")
    if lang:
        args.extend(("--lang", lang))
    assert main(args) == 0
    assert (tmp_path / filename).exists()
    assert "Jane" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "chart,suffix", [("pedigree", "cascading pedigree"), ("fan", "fan chart")]
)
def test_browser_export_filename_is_private_while_picker_names_remain(chart, suffix):
    session = Session()
    session.tree = private_tree()
    original = deepcopy(session.tree)
    assert "Jane" in session.search("SECRET-ID", True, True)[1][0][1]
    _, filename, _ = session.render("SECRET-ID", chart, {"exclude_private": True})
    assert filename == f"Living {suffix}.pdf"
    _, public_filename, _ = session.render("SECRET-ID", chart, {})
    assert "Jane" in public_filename and "secret" in public_filename.casefold()
    assert session.tree == original


def test_private_default_filename_uses_full_ancestry_estimate(tmp_path):
    # An undated root is also the parent of its own dated ancestor. The full
    # ancestry estimates its birth as 1775, so privacy must preserve its name.
    data = ged(
        "0 @I1@ INDI",
        "1 NAME Root /Old/",
        "1 FAMC @F1@",
        "0 @I2@ INDI",
        "1 NAME Ancestor /Old/",
        "1 BIRT",
        "2 DATE 1800",
        "1 FAMC @F2@",
        "0 @F1@ FAM",
        "1 HUSB @I2@",
        "0 @F2@ FAM",
        "1 HUSB @I1@",
    )
    session = Session()
    session.open(data)
    _, filename, _ = session.render(
        "I1", "pedigree", {"generations": 1, "exclude_private": True}
    )
    assert filename == "Root Old cascading pedigree.pdf"
    path = tmp_path / "old.ged"
    path.write_bytes(data)
    assert (
        main([str(path), "--root", "I1", "--generations", "1", "--exclude-private"])
        == 0
    )
    assert (tmp_path / "Root Old cascading pedigree.pdf").exists()


@pytest.mark.parametrize("chart", ["pedigree", "fan"])
def test_private_export_preserves_explicit_title_and_footer(chart):
    tree = private_tree()
    if chart == "pedigree":
        pdf = render_with_counts(
            tree,
            "SECRET-ID",
            Options(
                exclude_private=True,
                title="Jane's custom title",
                footer="Jane's custom footer",
                fonts="base14",
                compress=False,
            ),
        ).pdf
        text = drawn(pdf)
    else:
        pdf = render_fan(
            plan_fan(tree, "SECRET-ID", exclude_private=True),
            FanOptions(
                title="Jane's custom title",
                footer="Jane's custom footer",
                fonts="base14",
                compress=False,
            ),
        )
        text = [t for t, _ in text_objects(pdf)]
    assert "Jane's custom title" in text
    assert "Jane's custom footer" in text

"""--blank: one blank pedigree sheet to fill in by hand. One page with the title, the
chart's numbered boxes (1-15, or 1-7 in large print) and their connecting lines, laid
out like chart 1, including the root spouse row. Each box holds only the labels to
write after (b./bp./m./mp./d./dp. in English; the marriage lines on box 1 and the
fathers' boxes, as in a real chart), with an empty name line. No chart label, page
number, chart note, continuation line or record ID, and the footer has no date
("Created using Kincade", the footer_blank string). The --blank CLI mode has no config
key, needs no GEDCOM file or --root, and ignores gedcom or root from any source. The
library exposes render_blank.

Synthetic fixtures only."""

import datetime
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import replace

import pytest

import kincade.charts
import kincade.cli
import kincade.gedcom
import kincade.lang
import kincade.pdf
from kincade.pdf import Options

from conftest import PAPERS, PRINTS, ROOT, TODAY, config_keys, render_chart
from pdfread import count_pages, drawn, first_page, lines, rectangles, runs

BLANK_NAME = "Blank cascading pedigree.pdf"


def blank(**opts):
    opts.setdefault("today", TODAY)
    opts.setdefault("fonts", "base14")  # plain, searchable text
    opts.setdefault("compress", False)
    return kincade.pdf.render_blank(Options(**opts))


def labels_expected(large_print):
    """The label counts of a blank chart: every box has b./bp./d./dp.; the root and the
    fathers also m./mp., and the root has one spouse row.
    """
    boxes_, married = (7, 4) if large_print else (15, 8)
    return {
        "b.": boxes_,
        "bp.": boxes_,
        "d.": boxes_,
        "dp.": boxes_,
        "m.": married,
        "mp.": married,
        "spouse:": 1,
    }


# ---------------------------------------------------------------- the page


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
@pytest.mark.parametrize("paper", PAPERS)
def test_a_blank_chart_is_exactly_one_page(paper, large_print):
    pdf = blank(paper=paper, large_print=large_print)
    assert pdf.startswith(b"%PDF") and count_pages(pdf) == 1
    assert len(rectangles(pdf, "B*")) == (7 if large_print else 15)
    assert count_pages(blank(paper=paper, large_print=large_print, compress=True)) == 1


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
def test_the_text_is_the_title_the_footer_the_numbers_and_the_labels(large_print):
    text = Counter(t for t in drawn(blank(large_print=large_print)) if t)
    numbers = {str(n): 1 for n in range(1, 8 if large_print else 16)}
    assert text == Counter(
        {
            "Cascading Pedigree": 1,
            "Created using Kincade": 1,
            **numbers,
            **labels_expected(large_print),
        }
    )


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
def test_the_labels_appear_the_expected_number_of_times(large_print):
    pdf = blank(large_print=large_print)
    for label, count in labels_expected(large_print).items():
        assert pdf.count(b"(" + label.encode() + b") Tj") == count, label


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
def test_the_marriage_lines_are_on_box_1_and_the_fathers_only(large_print):
    pdf = blank(large_print=large_print)
    geom = kincade.pdf.page_geom("letter", large_print)
    rows = runs(pdf)
    boxes = rectangles(pdf, "B*")
    married = {
        pos for pos in range(1, 2**geom.gens) if kincade.pdf.has_marriage_lines(pos)
    }
    assert married == ({1, 2, 4, 6} if large_print else {1, 2, 4, 6, 8, 10, 12, 14})
    for pos in range(1, 2**geom.gens):
        _, top, _, height = boxes[pos - 1]
        in_box = [
            r.text
            for r in rows
            if abs(r.x - (geom.box_x0[pos] + geom.inset_left)) < 0.01
            and top < r.y < top + height
        ]
        assert ("m." in in_box and "mp." in in_box) == (pos in married), pos
        assert in_box[:2] == ["b.", "bp."] and in_box[-2:] == ["d.", "dp."], pos


def test_nothing_that_belongs_to_a_real_chart_is_drawn():
    pdf = blank(show_ids=True, page_numbers=True, index=True)
    text = " ".join(drawn(pdf))
    for absent in (
        "Chart",
        "Page",
        "Ancestry continues",
        "Number 1 on this chart",
        "[",
        "Index",
        "2026",
        "Oct",
    ):
        assert absent not in text, absent
    assert not any(re.fullmatch(r"\d+ \w+ \d{4}", t) for t in drawn(pdf))


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
def test_the_name_line_is_empty_and_the_labels_start_below_it(large_print):
    geom = kincade.pdf.page_geom("letter", large_print)
    pdf = blank(large_print=large_print)
    rows = [r for r in runs(pdf) if r.text]
    boxes = rectangles(pdf, "B*")
    for pos in range(1, 2**geom.gens):
        left, top, width, height = boxes[pos - 1]
        right = left + width
        inside = [
            (r.y, r.text)
            for r in rows
            if left <= r.x < right and top < r.y < top + height
        ]
        # the first detail line's baseline
        first = top + geom.name_base + geom.detail_gap
        # nothing on the name line
        assert inside and min(y for y, _ in inside) == pytest.approx(first, abs=0.02), (
            pos
        )
        assert min(inside)[1] == "b."  # the topmost text is the first label


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("shadow", [False, True], ids=["flat", "shadow"])
def test_the_boxes_and_lines_are_those_of_chart_1(pedigree, paper, large_print, shadow):
    ours = blank(paper=paper, large_print=large_print, shadow=shadow)
    real = render_chart(pedigree, large_print=large_print, paper=paper, shadow=shadow)
    assert rectangles(ours, "B*") == rectangles(real, "B*")
    assert lines(ours) == lines(real)
    assert rectangles(ours, "f*") == rectangles(real, "f*")
    assert bool(rectangles(ours, "f*")) is shadow


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
@pytest.mark.parametrize("paper", PAPERS)
def test_the_labels_sit_where_a_filled_boxs_labels_sit(pedigree, paper, large_print):
    ours = runs(blank(paper=paper, large_print=large_print))
    real = runs(render_chart(pedigree, large_print=large_print, paper=paper))
    for label in ("b.", "bp.", "spouse:", "m.", "mp.", "d.", "dp."):
        # a filled box draws "b. 14 Feb 1980": the same start; the number of the box is
        # drawn left of the box
        want = sorted(
            (r.x, r.y)
            for r in real
            if r.text == label or r.text.startswith(label + " ")
        )
        mine = sorted((r.x, r.y) for r in ours if r.text == label)
        assert set(mine) <= set(want) and mine, label
    # the box numbers
    assert {(r.x, r.y) for r in ours if re.fullmatch(r"\d+", r.text)} <= {
        (r.x, r.y) for r in real
    }


def test_the_header_and_footer_are_where_a_real_charts_are(pedigree):
    ours, real = runs(blank()), runs(render_chart(pedigree))
    title = next((r.x, r.y) for r in ours if r.text == "Cascading Pedigree")
    assert title == next(
        (r.x, r.y) for r in real if r.text.startswith("Cascading Pedigree — ")
    )
    footer = next(r.y for r in ours if r.text == "Created using Kincade")
    # on the footer's baseline
    assert footer == next(r.y for r in real if r.text.startswith("Created "))
    assert b"/Title (Cascading Pedigree)" in blank()


# ----------------------------------------------------------------
# the options it respects and ignores


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
def test_the_options_that_do_not_apply_change_nothing(large_print):
    plain = first_page(blank(large_print=large_print))
    ignored = {
        "index": False,
        "empty_boxes": False,
        "exclude_private": True,
        "show_ids": True,
        "adoptive_parents": True,
        "event_standins": False,
        "shorten_places": False,
        "page_numbers": False,
        "generations": 2,
    }
    assert first_page(blank(large_print=large_print, **ignored)) == plain
    assert (
        first_page(blank(large_print=large_print, index=True, page_numbers=True))
        == plain
    )


def test_the_title_the_footer_and_no_footer():
    assert "My title" in drawn(
        blank(title="My title")
    ) and "Cascading Pedigree" not in drawn(blank(title="My title"))
    mine = drawn(blank(footer="Compiled by me"))
    assert "Compiled by me" in mine and "Created using Kincade" not in mine
    off = drawn(blank(footer=False))
    assert not any(t.startswith("Created") for t in off) and "Cascading Pedigree" in off
    assert Counter(t for t in off if t) == Counter(
        {
            "Cascading Pedigree": 1,
            **{str(n): 1 for n in range(1, 16)},
            **labels_expected(False),
        }
    )


def test_the_footer_has_no_date_whatever_the_clock_says():
    for today in (datetime.date(2026, 10, 11), datetime.date(1999, 1, 1)):
        assert "Created using Kincade" in drawn(blank(today=today))


def test_the_default_options_make_a_letter_page():
    pdf = kincade.pdf.render_blank()
    assert (
        pdf.startswith(b"%PDF")
        and count_pages(pdf) == 1
        and b"/MediaBox [ 0 0 612 792 ]" in pdf
    )


@pytest.mark.parametrize(
    "paper,box", [("letter", b"612 792"), ("a4", b"595.28 841.89")]
)
def test_the_paper(paper, box):
    assert b"/MediaBox [ 0 0 " + box + b" ]" in blank(paper=paper)


def test_shadows_are_drawn_on_request():
    assert blank(shadow=True).count(b"re f*") > 0 and blank().count(b"re f*") == 0
    assert count_pages(blank(shadow=True, large_print=True, paper="a4")) == 1


def test_a_bad_paper_is_a_value_error():
    with pytest.raises(ValueError):
        blank(paper="legal")


# ---------------------------------------------------------------- languages


def test_the_footer_blank_string_is_in_every_language_file():
    assert kincade.lang.DEFAULT_STRINGS["footer_blank"] == "Created using Kincade"
    assert kincade.lang.PLACEHOLDERS["footer_blank"] == ()
    assert kincade.lang.load_strings("en")["footer_blank"] == "Created using Kincade"
    assert kincade.lang.load_strings("de")["footer_blank"] == "Erstellt mit Kincade"
    assert "{" not in kincade.lang.load_strings("de")["footer_blank"]


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
def test_a_german_blank_chart(large_print):
    pdf = blank(lang="de", large_print=large_print)
    assert count_pages(pdf) == 1
    text = Counter(t for t in drawn(pdf) if t)
    boxes_, married = (7, 4) if large_print else (15, 8)
    assert (
        text["geb."] == boxes_ and text["gest."] == boxes_ and text["verh."] == married
    )
    # the place line of each date line reads "in"
    assert text["Ehe mit:"] == 1
    assert text["in"] == 2 * boxes_ + married
    assert text["Ahnentafel"] == 1 and text["Erstellt mit Kincade"] == 1
    for absent in ("Tafel", "Seite", "Fortsetzung", "Created"):
        assert not any(absent in t for t in text), absent
    # no English label is left
    assert not {"b.", "bp.", "d.", "dp.", "m.", "mp."} & set(text)


def test_the_blank_footer_can_be_overridden_in_the_strings():
    assert "Own words" in drawn(blank(lang={"footer_blank": "Own words"}))


def test_a_font_that_cannot_draw_a_label_is_not_a_crash():
    no_g = kincade.pdf.FontSet(supports=lambda ch: ch != "g")  # the German "geb."
    pdf = blank(lang="de", fonts=no_g)
    assert count_pages(pdf) == 1
    assert "?eb." in drawn(pdf)


# ---------------------------------------------------------------- the command line


def test_blank_needs_no_file_and_no_root_and_writes_the_default_name(tmp_path, capsys):
    # the working folder is tmp_path (conftest)
    assert kincade.cli.main(["--blank"]) == 0
    out = tmp_path / BLANK_NAME
    assert out.read_bytes().startswith(b"%PDF") and count_pages(out.read_bytes()) == 1
    err = capsys.readouterr().err
    assert (
        err.startswith("wrote ")
        and BLANK_NAME in err
        and "blank" in err
        and err.count("\n") == 1
    )


def test_blank_with_o_writes_that_file_and_makes_the_folder(tmp_path):
    out = tmp_path / "forms" / "sheet.pdf"
    assert kincade.cli.main(["--blank", "-o", str(out)]) == 0
    assert count_pages(out.read_bytes()) == 1 and not (tmp_path / BLANK_NAME).exists()


def test_blank_with_find_is_a_usage_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        kincade.cli.main(["--blank", "--find", "jane", "-o", str(tmp_path / "x.pdf")])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("usage: kincade") and "--blank" in err and "--find" in err
    assert not (tmp_path / "x.pdf").exists()


def test_a_file_and_a_root_on_the_command_line_are_ignored(tmp_path):
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [str(tmp_path / "missing.ged"), "--root", "@I1@", "--blank", "-o", str(out)]
        )
        == 0
    )
    assert count_pages(out.read_bytes()) == 1


def test_a_gedcom_and_a_root_from_a_config_file_are_ignored(tmp_path):
    (tmp_path / "kincade.toml").write_text(
        'gedcom = "missing.ged"\nroot = "@I99@"\n', encoding="utf-8"
    )
    out = tmp_path / "x.pdf"
    assert kincade.cli.main(["--blank", "-o", str(out)]) == 0
    assert count_pages(out.read_bytes()) == 1


def test_blank_is_not_a_config_key(tmp_path, capsys):
    (tmp_path / "kincade.toml").write_text("blank = true\n", encoding="utf-8")
    assert kincade.cli.main(["--show-config"]) == 2
    assert "unknown key 'blank'" in capsys.readouterr().err
    assert "blank" not in config_keys()
    assert kincade.cli.main(["--show-config", "--no-config", "--blank"]) == 0
    assert "blank" not in capsys.readouterr().out


@pytest.fixture
def captured(monkeypatch):
    """The Options each blank render receives, in order; the PDF is made as usual."""
    seen = []
    real = kincade.pdf.render_blank
    monkeypatch.setattr(
        kincade.cli, "render_blank", lambda opts=None: seen.append(opts) or real(opts)
    )
    return seen


def test_the_page_options_reach_the_blank_chart(tmp_path, captured):
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                "--blank",
                "--paper",
                "a4",
                "--large-print",
                "--shadow",
                "--lang",
                "de",
                "--title",
                "Mine",
                "--footer",
                "Footer",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    (opts,) = captured
    assert (opts.paper, opts.large_print, opts.shadow, opts.title, opts.footer) == (
        "a4",
        True,
        True,
        "Mine",
        "Footer",
    )
    assert opts.lang["footer_blank"] == "Erstellt mit Kincade"
    assert kincade.cli.main(["--blank", "--no-footer", "-o", str(out)]) == 0
    assert captured[-1].footer is False


def test_the_config_file_supplies_the_page_options(tmp_path, captured):
    (tmp_path / "kincade.toml").write_text(
        'paper = "a4"\nlarge_print = true\nlang = "de"\n', encoding="utf-8"
    )
    out = tmp_path / "x.pdf"
    assert kincade.cli.main(["--blank", "-o", str(out)]) == 0
    assert (captured[0].paper, captured[0].large_print) == ("a4", True)
    assert b"/MediaBox [ 0 0 595.28 841.89 ]" in out.read_bytes()


def test_the_options_that_do_not_apply_are_accepted_and_ignored(tmp_path, captured):
    out = tmp_path / "x.pdf"
    ignored = [
        "--generations",
        "3",
        "--no-index",
        "--no-empty",
        "--exclude-private",
        "--show-ids",
        "--adoptive-parents",
        "--no-event-standins",
        "--no-shorten-places",
        "--no-page-numbers",
    ]
    assert kincade.cli.main(["--blank", *ignored, "-o", str(out)]) == 0
    assert count_pages(out.read_bytes()) == 1
    # not checked: it does not apply
    assert kincade.cli.main(["--blank", "--generations", "0", "-o", str(out)]) == 0
    for opts in captured:  # the page options keep their defaults
        assert (opts.paper, opts.large_print, opts.shadow, opts.title, opts.footer) == (
            "letter",
            False,
            False,
            None,
            None,
        )


def test_what_the_command_line_makes_is_what_the_library_makes(tmp_path, captured):
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                "--blank",
                "--paper",
                "a4",
                "--footer",
                "Footer",
                "--title",
                "Mine",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    replay = kincade.pdf.render_blank(
        replace(captured[0], compress=False, fonts="base14")
    )
    assert {"Mine", "Footer"} <= set(drawn(replay)) and count_pages(replay) == 1
    assert count_pages(out.read_bytes()) == 1 and out.stat().st_size > 1000


def test_an_unusable_language_exits_1(tmp_path, capsys):
    assert (
        kincade.cli.main(
            ["--blank", "--lang", "no-such-language", "-o", str(tmp_path / "x.pdf")]
        )
        == 1
    )
    err = capsys.readouterr().err
    assert (
        err.startswith("kincade: ")
        and "no-such-language" in err
        and not (tmp_path / "x.pdf").exists()
    )


def test_an_output_that_cannot_be_written_exits_1(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert kincade.cli.main(["--blank", "-o", str(blocker / "x.pdf")]) == 1
    assert capsys.readouterr().err.startswith("kincade: cannot write ")


def test_a_bad_config_file_stops_a_blank_run(tmp_path, capsys):
    (tmp_path / "kincade.toml").write_text('paper = "legal"\n', encoding="utf-8")
    assert kincade.cli.main(["--blank"]) == 2
    assert "paper" in capsys.readouterr().err and not (tmp_path / BLANK_NAME).exists()
    # --no-config skips the file
    assert kincade.cli.main(["--blank", "--no-config"]) == 0


def test_the_help_names_blank(capsys):
    with pytest.raises(SystemExit):
        kincade.cli.main(["--help"])
    out = capsys.readouterr().out
    assert "       kincade --blank [options]\n" in out
    assert "make one blank chart to fill in by hand (no GEDCOM file)" in " ".join(
        out.split()
    )


@pytest.mark.system_fonts
def test_blank_works_through_the_module_itself(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    done = subprocess.run(
        [sys.executable, "-m", "kincade.cli", "--blank", "-o", "sheet.pdf"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert count_pages((tmp_path / "sheet.pdf").read_bytes()) == 1

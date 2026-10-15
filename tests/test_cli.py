"""The command line: --help prints the help and exits 0, also from the config-file
parse, where every default is suppressed.

The help has four sections (person, content, page, config file), lists the one flag of
each on/off option (the one that changes the default; it has no opposite), and never
breaks an option name at its hyphens.

Synthetic fixtures only.
"""

import errno
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path

import pytest
from reportlab import rl_config

import kincade
import kincade.charts
import kincade.cli
import kincade.gedcom
import kincade.lang
import kincade.pdf
from kincade import Options
from kincade.charts import plan_charts
from kincade.fan import Fan, FanCell
from kincade.model import Person, Tree
from kincade.pdf import Rendered

from conftest import FIX, ROOT, TODAY, TOO_LONG, ged
from pdfread import count_pages


def test_help_prints_the_options_and_exits_0(capsys):
    with pytest.raises(SystemExit) as e:
        kincade.cli.main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    for option in (
        "--root",
        "--generations",
        "--config",
        "--paper",
        "--show-config",
        "--no-page-numbers",
    ):
        assert option in out, option
    assert "(default: letter)" in out


def test_help_works_through_the_module_itself():
    done = subprocess.run(
        [sys.executable, "-m", "kincade.cli", "--help"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("usage: kincade")
    assert done.stderr == ""


# ---------------------------------------------------------------- the help text

# every option the help lists, as it prints them, in order
LISTED = [
    "-h, --help",
    "FILE.ged",
    "--root PERSON",
    "--root-family FAMILY",
    "--find TEXT",
    "--fan",
    "--generations N",
    "--exclude-private",
    "--preserve-case",
    "--adoptive-parents",
    "--no-event-standins",
    "--no-empty",
    "--show-ids",
    "--no-shorten-places",
    "--no-index",
    "-o, --output FILE",
    "--paper {letter,a4,tabloid,a3}",
    "--ink {color,grayscale,bw}",
    "--large-print",
    "--shadow",
    "--lang LANG",
    "--title TEXT",
    "--footer TEXT",
    "--no-footer",
    "--no-page-numbers",
    "--blank",
    "--config FILE",
    "--no-config",
    "--show-config",
]


def help_text(monkeypatch, capsys, columns=80):
    monkeypatch.setenv("COLUMNS", str(columns))
    with pytest.raises(SystemExit) as e:
        kincade.cli.main(["--help"])
    assert e.value.code == 0
    return capsys.readouterr().out


def listed_options(text):
    """The invocation of each option line (two spaces, then the option), without its
    help.
    """
    return [
        re.split(r"\s{2,}", line.strip())[0]
        for line in text.splitlines()
        if re.match(r"^ {2}(-|FILE)", line)
    ]


def test_the_usage_has_five_forms(monkeypatch, capsys):
    out = help_text(monkeypatch, capsys)
    assert out.startswith(
        "usage: kincade FILE.ged --root PERSON [options]\n"
        "       kincade FILE.ged --root PERSON --fan [options]\n"
        "       kincade FILE.ged --find TEXT [options]\n"
        "       kincade --blank [options]\n"
        "       kincade --show-config [options]\n"
    )


def test_the_help_has_the_four_sections_in_order(monkeypatch, capsys):
    out = help_text(monkeypatch, capsys)
    positions = [
        out.index(f"\n{name}:\n")
        for name in ("person", "content", "page", "config file")
    ]
    assert positions == sorted(positions)
    # -h stays where argparse puts it
    assert "positional arguments" not in out and "\noptions:\n" in out


def test_the_help_lists_the_flag_that_changes_the_default_and_there_are_no_opposites(
    monkeypatch, capsys
):
    out = help_text(monkeypatch, capsys)
    assert listed_options(out) == LISTED


def test_each_option_is_in_its_help_section(monkeypatch, capsys):
    out = help_text(monkeypatch, capsys)
    sections = re.split(r"\n(?=[a-z ]+:\n)", out)
    by_name = {
        section.split(":", 1)[0]: listed_options(section) for section in sections[1:]
    }
    assert by_name["options"] == ["-h, --help"]
    assert by_name["person"] == [
        "FILE.ged",
        "--root PERSON",
        "--root-family FAMILY",
        "--find TEXT",
    ]
    assert by_name["content"] == [
        "--fan",
        "--generations N",
        "--exclude-private",
        "--preserve-case",
        "--adoptive-parents",
        "--no-event-standins",
        "--no-empty",
        "--show-ids",
        "--no-shorten-places",
        "--no-index",
    ]
    assert by_name["page"] == [
        "-o, --output FILE",
        "--paper {letter,a4,tabloid,a3}",
        "--ink {color,grayscale,bw}",
        "--large-print",
        "--shadow",
        "--lang LANG",
        "--title TEXT",
        "--footer TEXT",
        "--no-footer",
        "--no-page-numbers",
        "--blank",
    ]
    assert by_name["config file"] == ["--config FILE", "--no-config", "--show-config"]


def test_the_help_column_lines_up_at_23_on_80_columns(monkeypatch, capsys):
    out = help_text(monkeypatch, capsys)
    line = next(ln for ln in out.splitlines() if ln.startswith("  --generations N"))
    assert line.index("show N generations") == 23
    assert max(len(ln) for ln in out.splitlines()) <= 80
    # Long invocations put their help on the following line.
    assert "  --paper {letter,a4,tabloid,a3}\n" in out


@pytest.mark.parametrize("columns", [40, 50, 60, 72, 80, 100, 120, 200])
def test_no_option_name_or_word_is_broken_at_a_hyphen(monkeypatch, capsys, columns):
    out = help_text(monkeypatch, capsys, columns)
    for line in out.splitlines():
        # "--no-" / "page-numbers", where argparse's default formatter would break it
        assert not line.rstrip().endswith("-"), line
    # a name broken over two lines would read "--no- page-numbers" here
    flat = " ".join(out.split())
    for option in (w for entry in LISTED for w in re.findall(r"--[a-z][a-z-]+", entry)):
        assert option in flat, option


def test_the_description_and_the_epilog(monkeypatch, capsys):
    flat = " ".join(help_text(monkeypatch, capsys).split())
    assert (
        "Make a cascading pedigree PDF from a GEDCOM file: chart 1 for the root person, a further chart wherever "
        "a line runs past the last column, and a name index at the end."
    ) in flat
    assert (
        'Example: uv run kincade docs/examples/george-washington.ged --root "George Washington"'
        in flat.replace("\\ ", "")
    )
    assert (
        "Exit codes: 0: success (PDF, --find, --show-config or --help) "
        "1: a file cannot be read or written, a GEDCOM file has no people, "
        "a language cannot be used, or no match for --root or --find "
        "2: a usage error, an ambiguous --root or an invalid config file"
    ) in flat


def test_the_help_line_of_each_option(monkeypatch, capsys):
    flat = " ".join(help_text(monkeypatch, capsys, 300).split())
    for text in (
        "--find TEXT list matching people and their spouse families; (default) marks the first spouse family",
        "--root PERSON person at the head of chart 1: a record ID (I12) or part of a name",
        "--root-family FAMILY family record ID for the root's spouse and marriage (default: first spouse family; pedigree only)",
        "--generations N show N generations, counting the root as 1 (default: all; with --fan, 2 to 7, default 6)",
        "--exclude-private hide the names and details of people who may be living",
        (
            "--adoptive-parents where a person has adoptive or foster parents, draw those instead of birth parents; on the pedigree a "
            "note follows the name"
        ),
        (
            "--no-event-standins show only births and deaths; privacy still uses christenings, baptisms, burials "
            "and cremations"
        ),
        "--no-empty leave out the boxes of unknown ancestors",
        "--show-ids show each person's record ID beside their name, on the charts and in the index",
        '--no-shorten-places cut a long place with "…" instead of first leaving out its country and middle parts',
        "--no-index leave out the name index page(s) at the end",
        '-o, --output FILE PDF to write (default: "<root name> cascading pedigree.pdf"; with --fan: "<root name> fan chart.pdf"; with --blank: "Blank cascading pedigree.pdf")',
        "--paper {letter,a4,tabloid,a3} paper size (default: letter); tabloid and a3 are for the fan chart",
        "--large-print use larger print and three generations per page",
        "--shadow draw a drop shadow under each box",
        "--lang LANG language name (such as de) or .toml path; user files: ~/.config/kincade/lang/ (default: English)",
        "--title TEXT page title (default: chart title and root's name)",
        "--footer TEXT footer text (default: the language's footer)",
        "--no-footer leave out the footer",
        "--no-page-numbers leave out the page numbers",
        "--blank make one blank chart to fill in by hand (no GEDCOM file)",
        "--config FILE read config file FILE instead of ./kincade.toml or ~/.config/kincade/config.toml",
        "--no-config don't read a config file",
        "--show-config print the config in use and where each value came from",
    ):
        assert text in flat, text


def test_a_usage_error_prints_the_usage(capsys):
    with pytest.raises(SystemExit) as e:
        kincade.cli.main(["--bogus"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert (
        err.startswith("usage: kincade FILE.ged --root PERSON [options]")
        and "unrecognized arguments" in err
    )


def test_the_help_works_when_every_default_is_suppressed():
    """The config-file parse builds the parser with its defaults suppressed: its help
    formats all the same."""
    assert "--blank" in kincade.cli._parser(suppress_defaults=True).format_help()


# ---------------------------------------------------------------- the summary line


def test_generations_are_optional_on_the_cli_and_reject_zero(tmp_path, capsys):
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "--generations",
                "3",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    assert "(1 chart," in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        kincade.cli.main(
            [str(FIX / "pedigree.ged"), "--root", "@I1@", "--generations", "0"]
        )
    assert (
        e.value.code == 2
        and "--generations must be at least 1" in capsys.readouterr().err
    )
    # default: all
    assert (
        kincade.cli._parser().parse_args(["x.ged", "--root", "I1"]).generations is None
    )


# ---------------------------------------------------------------- command line


def test_cli_writes_a_pdf(tmp_path, capsys):
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "@I1@", "-o", str(out)])
        == 0
    )
    assert out.read_bytes().startswith(b"%PDF")
    assert "6 charts" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--root", "@I1@"], ["--find", "Doe"]])
def test_a_file_with_no_people_exits_1_with_one_line(tmp_path, capsys, args):
    path = tmp_path / "empty.ged"
    path.write_bytes(ged("0 HEAD", "1 GEDC", "2 VERS 5.5.1", "0 @F1@ FAM"))
    out = tmp_path / "x.pdf"
    assert kincade.cli.main([str(path), *args, "-o", str(out)]) == 1
    assert capsys.readouterr().err == f"kincade: no people found in {path}\n"
    assert not out.exists()


def test_cli_root_by_name_and_both_record_id_forms(tmp_path):
    for root in ("Jane ASHFORD", "jane ash", "I1"):
        out = tmp_path / "x.pdf"
        assert (
            kincade.cli.main(
                [
                    str(FIX / "pedigree.ged"),
                    "--root",
                    root,
                    "-o",
                    str(out),
                    "--generations",
                    "4",
                    "--no-index",
                ]
            )
            == 0
        )


def test_cli_ambiguous_root_exits_2(capsys):
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "ASHFORD"]) == 2
    err = capsys.readouterr().err
    assert "  I1\tJane ASHFORD" in err and "  I2\tJohn ASHFORD" in err


def test_cli_no_match_and_bad_file_exit_1(tmp_path):
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "Nobody Here"]) == 1
    assert kincade.cli.main([str(tmp_path / "missing.ged"), "--root", "x"]) == 1


def test_person_line_is_the_package_shipped_listing_helper(pedigree):
    line = kincade.cli.person_line(pedigree.people["I1"], lambda _pid: False, True)
    assert line == "I1\tJane ASHFORD\t1980-"
    assert not hasattr(kincade.cli, "_person_line")


def test_web_cli_helpers_are_not_added_to_the_promised_library_api():
    assert {"person_line", "pedigree_summary", "fan_summary"}.isdisjoint(
        kincade.__all__
    )


def test_cli_find_lists_matches(capsys):
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--find", "mcclure"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "I3\tMary McCLURE\t1952-",
        "    F1\tJohn ASHFORD\tm. 12 Jun 1975\tmp. Akron, Ohio",
        "I6\tWilliam McCLURE\t1925-1999",
        "    F3\tAnn BOND\tm. 1950",
        "I12\tSamuel McCLURE\t1900-1970",
        "    F6\tJane BRUCE\tm. 1 Feb 1925",
    ]


def test_find_with_no_match_says_so_and_exits_1(capsys):
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--find", "zzzz"]) == 1
    assert capsys.readouterr() == ("", "kincade: no person matches 'zzzz'\n")


@pytest.mark.parametrize("people", [50, 53])
def test_an_ambiguous_root_list_cut_at_50_says_how_many_more(tmp_path, capsys, people):
    path = tmp_path / "many.ged"
    lines = []
    for n in range(1, people + 1):
        lines += [f"0 @I{n}@ INDI", "1 NAME Jane /DOE/"]
    path.write_bytes(ged(*lines))
    assert kincade.cli.main([str(path), "--root", "Jane DOE"]) == 2
    err = capsys.readouterr().err.splitlines()
    assert err[0] == f"kincade: {people} people match 'Jane DOE'; use a record ID:"
    assert err[1:51] == [f"  I{n}\tJane DOE\t" for n in range(1, 51)]
    assert err[51:] == ([] if people == 50 else ["  … and 3 more"])


def test_cli_requires_root_or_find():
    with pytest.raises(SystemExit) as e:
        kincade.cli.main([str(FIX / "pedigree.ged")])
    assert e.value.code == 2


def test_find_private_redacts_living_names_and_years(capsys):
    assert (
        kincade.cli.main(
            [str(FIX / "pedigree.ged"), "--find", "ashford", "--exclude-private"]
        )
        == 0
    )
    out = capsys.readouterr().out
    # Record IDs remain available for selecting the redacted person.
    assert "I1\tLiving\t" in out and "1980" not in out
    assert "Jane" not in out
    assert "1950-2020" in out  # John is dead: years shown
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--find", "ashford"]) == 0
    assert "1980-" in capsys.readouterr().out


def test_ambiguous_root_candidates_redact_living_names_and_years(capsys):
    assert (
        kincade.cli.main(
            [str(FIX / "pedigree.ged"), "--root", "ASHFORD", "--exclude-private"]
        )
        == 2
    )
    err = capsys.readouterr().err
    assert "I1\tLiving\t" in err and "Jane" not in err
    assert "1980" not in err and "1950-2020" in err


def test_reading_errors_become_one_clean_line(monkeypatch, capsys):
    def boom(_):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(kincade.cli, "read_gedcom", boom)
    monkeypatch.delenv("KINCADE_DEBUG", raising=False)
    assert kincade.cli.main(["whatever.ged", "--root", "x"]) == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "kaboom" in err and "Traceback" not in err
    monkeypatch.setenv("KINCADE_DEBUG", "1")
    with pytest.raises(RuntimeError):
        kincade.cli.main(["whatever.ged", "--root", "x"])


def test_candidate_lists_hide_years_of_possibly_living_people(tmp_path, capsys):
    path = tmp_path / "a.ged"
    path.write_bytes(
        ged(
            "0 @I1@ INDI",
            "1 NAME Wide /RANGE/",
            "1 BIRT",
            "2 DATE BET 1900 AND 2000",
            "0 @I2@ INDI",
            "1 NAME Open /RANGE/",
            "1 BIRT",
            "2 DATE AFT 1900",
            "0 @I3@ INDI",
            "1 NAME Old /RANGE/",
            "1 BIRT",
            "2 DATE BEF 1900",
        )
    )
    assert kincade.cli.main([str(path), "--find", "range", "--exclude-private"]) == 0
    lines = capsys.readouterr().out.splitlines()
    # only the BEF 1900 man shows a year
    assert [ln.split("\t")[2] for ln in lines] == ["", "", "1900-"]


# ---- output file name and write errors ----------------------------------------------


def test_generated_output_name_is_bounded_and_clean(tmp_path):
    long_name = "A" * 400
    path = tmp_path / "long.ged"
    path.write_bytes(
        ged(
            "0 @I1@ INDI",
            f"1 NAME {long_name} /W\u0001\u007fE\\B\\/:*?/",
            "1 BIRT",
            "2 DATE 1900",
        )
    )
    assert kincade.cli.main([str(path), "--root", "@I1@", "--generations", "4"]) == 0
    (pdf,) = list(tmp_path.glob("*.pdf"))
    assert pdf.name.endswith(" cascading pedigree.pdf")
    stem = pdf.name[: -len(" cascading pedigree.pdf")]
    assert 0 < len(stem) <= 100 and not any(ch in stem for ch in '\\/:*?"<>|\x01\x7f')
    assert kincade.cli.default_output_name("..") == "pedigree cascading pedigree.pdf"
    assert (
        kincade.cli.default_output_name("Zoë/Wilks")
        == "Zoë_Wilks cascading pedigree.pdf"
    )
    assert len(
        kincade.cli.default_output_name("中" * 150).encode("utf-8")
    ) <= 200 + len(" cascading pedigree.pdf")


def test_write_errors_become_one_clean_line(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "--generations",
                "4",
                "-o",
                str(blocker / "x.pdf"),
            ]
        )
        == 1
    )
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("kincade: cannot write")


def test_cli_no_footer_and_footer_text(tmp_path, rendered_options):
    base = [str(FIX / "pedigree.ged"), "--root", "@I1@", "-o", str(tmp_path / "x.pdf")]
    assert kincade.cli.main(base + ["--no-footer"]) == 0
    assert kincade.cli.main(base + ["--footer", "Mine"]) == 0
    assert kincade.cli.main(base) == 0
    assert [o.footer for o in rendered_options] == [False, "Mine", None]
    with pytest.raises(SystemExit) as e:  # the two footer options contradict each other
        kincade.cli.main(base + ["--footer", "Mine", "--no-footer"])
    assert e.value.code == 2


@pytest.mark.parametrize("root", ["I1", "@I1@", " I1 "])
def test_the_command_line_accepts_both_forms_of_an_id(root, tmp_path):
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                root,
                "-o",
                str(out),
                "--generations",
                "2",
            ]
        )
        == 0
    )
    assert out.read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("text", ["I3", "@I3@"])
def test_find_matches_an_id_written_either_way(text, capsys):
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--find", text]) == 0
    # the listing shows the record ID without its @ signs
    assert capsys.readouterr().out.splitlines() == [
        "I3\tMary McCLURE\t1952-",
        "    F1\tJohn ASHFORD\tm. 12 Jun 1975\tmp. Akron, Ohio",
    ]


def test_find_people_takes_either_form(pedigree):
    assert [p.id for p in kincade.cli.find_people(pedigree, "@I3@")] == ["I3"]
    assert [p.id for p in kincade.cli.find_people(pedigree, "I3")] == ["I3"]


@pytest.mark.parametrize("text", ["i3", "@i3@"])
def test_find_matches_a_record_id_in_another_case(text, capsys):
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--find", text]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "I3\tMary McCLURE\t1952-",
        "    F1\tJohn ASHFORD\tm. 12 Jun 1975\tmp. Akron, Ohio",
    ]


def test_an_exact_record_id_wins_over_one_in_another_case():
    tree = Tree(
        {
            pid: Person(pid, given=name)
            for pid, name in (("i1", "Ann"), ("I1", "Bo"), ("x", "Cy"))
        }
    )
    assert [p.id for p in kincade.cli.find_people(tree, "i1")] == ["i1"]
    assert [p.id for p in kincade.cli.find_people(tree, "I1")] == ["I1"]
    assert [p.id for p in kincade.cli.find_people(tree, "X")] == ["x"]


ZOE_NFC, ZOE_NFD = "Zo\u00eb", "Zoe\u0308"


@pytest.mark.parametrize(
    "stored,typed",
    [
        (ZOE_NFD, ZOE_NFC),
        (ZOE_NFC, ZOE_NFD),
        (ZOE_NFC, "ZO\u00cb"),
        ("Stra\u00dfe", "strasse"),
    ],
)
def test_find_matches_a_name_in_another_case_or_unicode_form(stored, typed):
    tree = Tree({"I1": Person("I1", given=stored, surname="Doe")})
    assert [p.id for p in kincade.cli.find_people(tree, typed)] == ["I1"]


@pytest.mark.parametrize("stored", [ZOE_NFC, ZOE_NFD], ids=["NFC", "NFD"])
def test_find_prints_a_name_in_either_unicode_form_composed(stored, tmp_path, capsys):
    path = tmp_path / "f.ged"
    path.write_bytes(ged("0 @I1@ INDI", f"1 NAME {stored} /DOE/"))
    assert kincade.cli.main([str(path), "--find", "doe"]) == 0
    assert f"\t{ZOE_NFC} DOE\t" in capsys.readouterr().out


def test_an_exact_root_name_in_another_unicode_form_is_one_match(tmp_path):
    path = tmp_path / "f.ged"
    path.write_bytes(
        ged(
            "0 @I1@ INDI",
            f"1 NAME {ZOE_NFD} /DOE/",
            "0 @I2@ INDI",
            f"1 NAME {ZOE_NFD} Ann /DOE/",
        )
    )
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main([str(path), "--root", f"{ZOE_NFC} doe", "-o", str(out)]) == 0
    )


# ----------------------------------------------------------------
# the command line takes its counts from the render


def test_render_returns_bytes_and_only_bytes(pedigree):
    pdf = kincade.render(pedigree, "I1", Options(fonts="base14", today=TODAY))
    assert type(pdf) is bytes and pdf.startswith(b"%PDF")


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"index": False},
        {"large_print": True},
        {"generations": 3},
        {"generations": 1, "index": False},
        {"large_print": True, "generations": 5, "empty_boxes": False},
        {"adoptive_parents": True, "paper": "a4"},
    ],
)
def test_render_with_counts_gives_the_pdf_and_the_counts_of_what_it_drew(
    pedigree, options, monkeypatch
):
    # no creation date or random id: equal runs, equal bytes
    monkeypatch.setattr(rl_config, "invariant", 1)
    opts = Options(fonts="base14", today=TODAY, **options)
    rendered = kincade.pdf.render_with_counts(pedigree, "I1", opts)
    assert rendered.pdf == kincade.render(pedigree, "I1", opts)
    charts = plan_charts(
        pedigree, "I1", opts.generations, opts.parents, opts.large_print
    )
    assert rendered.chart_pages == len(charts)
    assert rendered.index_pages == count_pages(rendered.pdf) - len(charts)
    assert rendered.pages == count_pages(rendered.pdf)
    assert (rendered.index_pages == 0) == (options.get("index") is False)


def _record_planning(monkeypatch):
    """Record each call to plan_charts (its arguments, in order)."""
    planned = []
    real = kincade.charts.plan_charts

    def counting(*args, **kw):
        planned.append(args)
        return real(*args, **kw)

    # wherever the name is looked up
    for module in (kincade.pdf, kincade.cli, kincade.charts):
        monkeypatch.setattr(module, "plan_charts", counting, raising=False)
    return planned


def test_without_exclude_private_the_summary_counts_add_no_second_plan(
    monkeypatch, tmp_path, capsys
):
    """Without --exclude-private the charts are planned once, for the PDF. The summary
    line's counts come from the render, so they add no plan_charts call and no count of
    the PDF's pages.
    """
    planned = _record_planning(monkeypatch)
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "I1", "-o", str(out)])
        == 0
    )
    assert len(planned) == 1  # the charts are planned for the PDF and for nothing else
    assert capsys.readouterr().err == f"wrote {out} (6 charts, 1 index page, 7 pages)\n"


def test_with_exclude_private_the_charts_are_planned_twice_and_no_more(
    monkeypatch, tmp_path, capsys
):
    """With --exclude-private the charts are planned twice and no more: first with the
    chosen generations, for the drawing, then with None, for the living estimate, which
    needs the whole pedigree. The summary counts add nothing.
    """
    planned = _record_planning(monkeypatch)
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "I1",
                "-o",
                str(out),
                "--generations",
                "2",
                "--exclude-private",
            ]
        )
        == 0
    )
    assert [(root, generations) for _, root, generations, *_ in planned] == [
        ("I1", 2),
        ("I1", None),
    ]
    assert out.read_bytes().startswith(b"%PDF")
    assert capsys.readouterr().err.startswith(f"wrote {out} (")


@pytest.mark.parametrize(
    "charts,index_pages,summary",
    [
        (6, 1, "6 charts, 1 index page, 7 pages"),
        (1, 0, "1 chart, 0 index pages, 1 page"),
        (1, 2, "1 chart, 2 index pages, 3 pages"),
    ],
)
def test_pedigree_summary_is_shared(charts, index_pages, summary):
    rendered = Rendered(b"", charts, index_pages)
    assert kincade.cli.pedigree_summary(rendered) == summary


def test_fan_summary_is_shared(pedigree):
    fan = kincade.plan_fan(pedigree, "I1")
    assert kincade.cli.fan_summary(fan) == "fan chart, 6 generations, 23 people"


def test_fan_summary_counts_copies_and_ignores_empty_cells():
    fan = Fan(
        3,
        [
            FanCell(1),
            FanCell(2, copies=2),
            FanCell(3, copies=2),
            *[FanCell(slot, empty=True) for slot in range(4, 8)],
        ],
    )
    assert kincade.cli.fan_summary(fan) == "fan chart, 3 generations, 2 people"
    only_root = Fan(2, [FanCell(1), FanCell(2, empty=True), FanCell(3, empty=True)])
    assert kincade.cli.fan_summary(only_root) == "fan chart, 2 generations, 1 person"


@pytest.mark.parametrize(
    "flags,summary",
    [
        ([], "6 charts, 1 index page, 7 pages"),
        (["--no-index"], "6 charts, 0 index pages, 6 pages"),
        (["--generations", "1"], "1 chart, 1 index page, 2 pages"),
        (["--generations", "1", "--no-index"], "1 chart, 0 index pages, 1 page"),
        (["--large-print"], None),
    ],
)
def test_the_summary_line(flags, summary, tmp_path, capsys):
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [str(FIX / "pedigree.ged"), "--root", "I1", "-o", str(out), *flags]
        )
        == 0
    )
    err = capsys.readouterr().err
    if summary:
        assert err == f"wrote {out} ({summary})\n"
    else:  # large print: the counts agree with the file that was written
        charts, index, pages = map(int, re.findall(r"\d+", err.split("(")[1]))
        assert pages == charts + index == count_pages(out.read_bytes())


def run_cli(*args):
    return kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "@I1@", *args])


def test_cli_a_language_name_too_long_for_the_file_system_exits_1_with_one_line(
    tmp_path, capsys
):
    assert run_cli("--lang", TOO_LONG, "-o", str(tmp_path / "x.pdf")) == 1
    err = capsys.readouterr().err
    assert err.startswith("kincade: ") and len(err.splitlines()) == 1
    assert not (tmp_path / "x.pdf").exists()


@pytest.mark.parametrize(
    "error",
    [
        OSError(errno.ENAMETOOLONG, "File name too long"),
        PermissionError(13, "Permission denied"),
        OSError(5, "Input/output error"),
    ],
)
def test_cli_a_config_lookup_that_fails_exits_1_with_one_line(
    tmp_path, monkeypatch, capsys, error
):
    def fail(self):
        raise error

    monkeypatch.setattr(Path, "is_file", fail)
    assert run_cli("-o", str(tmp_path / "x.pdf")) == 1
    err = capsys.readouterr().err
    assert (
        err.startswith("kincade: ")
        and len(err.splitlines()) == 1
        and error.strerror in err
    )
    assert not (tmp_path / "x.pdf").exists()


def test_cli_a_home_folder_the_file_system_rejects_is_never_a_traceback(
    tmp_path, monkeypatch, capsys
):
    """The real thing: a per-user config path with a component longer than the file
    system allows. Where Path.is_file raises OSError for it (Python 3.11 to 3.13 on
    POSIX), the run stops with one `kincade:` line and exit 1; where it reads as no file
    (Python 3.14), the run goes on without a config file."""
    path = tmp_path / TOO_LONG / "config.toml"
    try:
        path.is_file()
    except OSError:
        refused = True
    else:
        refused = False
    monkeypatch.setattr(kincade.cli, "_user_config_file", lambda: path)
    out = tmp_path / "x.pdf"
    rc = run_cli("--generations", "1", "-o", str(out))
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    if refused:
        assert rc == 1 and err.startswith("kincade: ") and not out.exists()
    else:
        assert rc == 0 and err.startswith("wrote ") and out.exists()


@pytest.mark.usefixtures("no_home_folder")
def test_cli_with_no_home_folder_reads_no_user_files_and_never_shows_a_traceback(
    tmp_path, capsys
):
    out = tmp_path / "x.pdf"
    assert run_cli("--generations", "1", "-o", str(out)) == 0
    assert out.exists()
    capsys.readouterr()
    assert run_cli("--lang", "zz", "-o", str(out)) == 1
    assert capsys.readouterr().err == (
        f"kincade: no language file zz.toml in {kincade.lang.LANG_DIR}\n"
    )
    assert kincade.cli.main(["--show-config"]) == 0
    assert "# no config file is read" in capsys.readouterr().out


def test_cli_no_config_never_looks_for_one(tmp_path, monkeypatch):
    def fail(self):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "is_file", fail)
    assert (
        run_cli("--no-config", "--generations", "1", "-o", str(tmp_path / "x.pdf")) == 0
    )


def test_cli_a_gedcom_config_and_output_name_the_file_system_rejects_each_exit_1_with_one_line(
    tmp_path, monkeypatch, capsys
):
    real_open = Path.open
    rejected = []
    reason = "synthetic path rejection"

    def reject_long_name(self, *args, **kwargs):
        if self.name == TOO_LONG:
            rejected.append(self)
            raise OSError(errno.ENAMETOOLONG, reason, str(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_long_name)
    fixture = str(FIX / "pedigree.ged")
    for argv, path in (
        ([TOO_LONG, "--root", "@I1@"], TOO_LONG),
        ([fixture, "--root", "@I1@", "--config", TOO_LONG], TOO_LONG),
        (
            [fixture, "--root", "@I1@", "-o", str(tmp_path / TOO_LONG)],
            str(tmp_path / TOO_LONG),
        ),
    ):
        assert kincade.cli.main(argv) == 1
        err = capsys.readouterr().err
        assert (
            err.startswith("kincade: ")
            and len(err.splitlines()) == 1
            and err.count(path) == 1
            and reason in err
        )
    assert len(rejected) == 3


def test_messages_on_stderr_start_with_the_command_name(capsys):
    assert (
        kincade.cli.main(
            ["--no-config", str(FIX / "pedigree.ged"), "--root", "no such person xyz"]
        )
        == 1
    )
    assert capsys.readouterr().err.startswith("kincade: ")


def test_cli_formats_library_warnings_as_plain_lines(tmp_path, capsys):
    language = tmp_path / "wording.toml"
    language.write_text('extra = "invented"\n', encoding="utf-8")
    assert (
        kincade.cli.main(
            ["--no-config", "--blank", "--lang", str(language), "-o", "blank.pdf"]
        )
        == 0
    )
    messages = capsys.readouterr().err.splitlines()
    assert len(messages) == 2
    assert messages[0].startswith("kincade: warning: ")
    assert "unknown key 'extra' ignored" in messages[0]
    assert messages[1].startswith("wrote blank.pdf ")
    assert not any("KincadeWarning" in message for message in messages)


def test_cli_leaves_unrelated_warnings_with_the_callers_handler(monkeypatch):
    make_blank = kincade.cli._make_blank

    def warn_and_make_blank(args):
        warnings.warn("dependency notice", RuntimeWarning, stacklevel=2)
        return make_blank(args)

    monkeypatch.setattr(kincade.cli, "_make_blank", warn_and_make_blank)
    with pytest.warns(RuntimeWarning, match="dependency notice"):
        assert kincade.cli.main(["--no-config", "--blank", "-o", "blank.pdf"]) == 0


def test_the_footer_names_the_tool_in_both_languages():
    assert kincade.lang.DEFAULT_STRINGS["footer"] == "Created {date} using Kincade"
    assert kincade.lang.load_strings("de")["footer"] == "Erstellt am {date} mit Kincade"


def test_the_pdf_creator_is_kincade():
    tree = kincade.gedcom.read_gedcom(FIX / "pedigree.ged")
    pdf = kincade.pdf.render_pdf(
        kincade.charts.plan_charts(tree, "I1", 1),
        tree,
        kincade.pdf.Options(fonts="base14", compress=False),
    )
    assert b"/Creator (Kincade)" in pdf


def test_the_chart_type_keeps_its_name():
    assert kincade.lang.DEFAULT_STRINGS["title"] == "Cascading Pedigree"
    assert (
        kincade.cli.default_output_name("Jane DOE") == "Jane DOE cascading pedigree.pdf"
    )


# ---------------------------------------------------------------- fan chart


@pytest.mark.parametrize("generations,people", [(None, 23), (3, 7)])
def test_fan_writes_one_landscape_page_with_its_default_name_and_summary(
    tmp_path, capsys, generations, people
):
    flags = [] if generations is None else ["--generations", str(generations)]
    assert run_cli("--fan", *flags) == 0
    out = tmp_path / "Jane ASHFORD fan chart.pdf"
    pdf = out.read_bytes()
    assert pdf.startswith(b"%PDF") and count_pages(pdf) == 1
    assert b"/MediaBox [ 0 0 792 612 ]" in pdf
    assert capsys.readouterr().err == (
        f"wrote {out.name} (fan chart, {generations or 6} generations, {people} people)\n"
    )


@pytest.mark.parametrize("ink", ["color", "grayscale", "bw"])
@pytest.mark.parametrize(
    "paper,size",
    [
        ("letter", "792 612"),
        ("a4", "841.89 595.28"),
        ("tabloid", "1224 792"),
        ("a3", "1190.55 841.89"),
    ],
)
def test_fan_accepts_each_ink_and_paper_and_an_output_path(tmp_path, ink, paper, size):
    out = tmp_path / "charts" / "fan.pdf"
    assert run_cli("--fan", "--ink", ink, "--paper", paper, "-o", str(out)) == 0
    pdf = out.read_bytes()
    assert count_pages(pdf) == 1
    assert f"/MediaBox [ 0 0 {size} ]".encode() in pdf


@pytest.mark.parametrize(
    "footer_flags,footer",
    [([], None), (["--no-footer"], False), (["--footer", "Mine"], "Mine")],
)
def test_fan_shared_options_reach_the_planner_and_renderer(
    monkeypatch, tmp_path, footer_flags, footer
):
    planned, rendered = [], []
    real_plan, real_render = kincade.plan_fan, kincade.render_fan

    def plan(tree, root, **kwargs):
        planned.append((root, kwargs))
        return real_plan(tree, root, **kwargs)

    def render(fan, opts):
        rendered.append((fan, opts))
        opts.fonts, opts.compress, opts.today = "base14", False, TODAY
        return real_render(fan, opts)

    monkeypatch.setattr(kincade.cli, "plan_fan", plan, raising=False)
    monkeypatch.setattr(kincade.cli, "render_fan", render, raising=False)
    out = tmp_path / "fan.pdf"
    assert (
        run_cli(
            "--fan",
            "--generations",
            "3",
            "--exclude-private",
            "--adoptive-parents",
            "--no-event-standins",
            "--title",
            "Jane Doe",
            "--lang",
            "de",
            "--ink",
            "grayscale",
            "--paper",
            "a3",
            "-o",
            str(out),
            *footer_flags,
        )
        == 0
    )
    ((root, kwargs),) = planned
    assert root == "I1"
    assert {k: v for k, v in kwargs.items() if k != "lang"} == {
        "generations": 3,
        "exclude_private": True,
        "adoptive_parents": True,
        "event_standins": False,
        "preserve_case": False,
        "ink": "grayscale",
    }
    ((fan, opts),) = rendered
    assert kwargs["lang"] == opts.lang == kincade.lang.load_strings("de")
    assert (opts.ink, opts.paper, opts.title, opts.footer) == (
        "grayscale",
        "a3",
        "Jane Doe",
        footer,
    )
    assert fan.cells[0].years == ""
    assert b"/Title (Jane Doe)" in out.read_bytes()


@pytest.mark.parametrize(
    "flags,flag",
    [
        (["--no-index"], "--no-index"),
        (["--large-print"], "--large-print"),
        (["--shadow"], "--shadow"),
        (["--show-ids"], "--show-ids"),
        (["--no-empty"], "--no-empty"),
        (["--no-shorten-places"], "--no-shorten-places"),
        (["--no-page-numbers"], "--no-page-numbers"),
        *[(["--generations", str(n)], "--generations") for n in (-1, 0, 1, 8, 10)],
        (["--blank"], "--blank"),
    ],
)
@pytest.mark.parametrize("config_fan", [False, True])
def test_fan_rejects_inapplicable_command_line_flags(
    tmp_path, capsys, flags, flag, config_fan
):
    if config_fan:
        (tmp_path / "kincade.toml").write_text("fan = true\n")
        fan_flags = []
        if flag == "--blank":
            fan_flags = ["--fan"]
    else:
        fan_flags = ["--fan"]
    with pytest.raises(SystemExit) as e:
        run_cli(*fan_flags, *flags)
    assert e.value.code == 2 and flag in capsys.readouterr().err
    assert not list(tmp_path.glob("*.pdf"))


@pytest.mark.parametrize("mode", [[], ["--blank"]])
@pytest.mark.parametrize(
    "flags,flag",
    [
        (["--ink", "bw"], "--ink"),
        (["--paper", "tabloid"], "--paper"),
        (["--paper", "a3"], "--paper"),
    ],
)
def test_pedigree_and_blank_reject_fan_only_command_line_flags(
    capsys, mode, flags, flag
):
    with pytest.raises(SystemExit) as e:
        run_cli(*mode, *flags)
    assert e.value.code == 2 and flag in capsys.readouterr().err


@pytest.mark.parametrize(
    "name,filename",
    [
        ("Zoë/Wilks", "Zoë_Wilks fan chart.pdf"),
        ("..", "fan chart.pdf"),
        ("", "fan chart.pdf"),
    ],
)
def test_fan_default_file_names_are_safe(name, filename):
    assert kincade.cli.default_fan_output_name(name) == filename
    assert len(kincade.cli.default_fan_output_name("中" * 150).encode()) <= 200 + len(
        " fan chart.pdf"
    )


def test_a_nameless_fan_root_has_a_fallback_file_name_and_one_person(tmp_path, capsys):
    path = tmp_path / "nameless.ged"
    path.write_bytes(ged("0 @I1@ INDI"))
    assert kincade.cli.main([str(path), "--root", "I1", "--fan"]) == 0
    assert (tmp_path / "fan chart.pdf").read_bytes().startswith(b"%PDF")
    assert (
        capsys.readouterr().err
        == "wrote fan chart.pdf (fan chart, 6 generations, 1 person)\n"
    )


def test_fan_summary_counts_distinct_people_with_pedigree_collapse(tmp_path, capsys):
    path = tmp_path / "repeat.ged"
    path.write_bytes(
        ged(
            "0 @I1@ INDI",
            "1 NAME Jane /DOE/",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME John /DOE/",
            "1 FAMC @F2@",
            "0 @I3@ INDI",
            "1 NAME Mary /DOE/",
            "1 FAMC @F2@",
            "0 @I4@ INDI",
            "1 NAME Pat /DOE/",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 WIFE @I3@",
            "0 @F2@ FAM",
            "1 HUSB @I4@",
        )
    )
    assert (
        kincade.cli.main([str(path), "--root", "I1", "--fan", "--generations", "3"])
        == 0
    )
    assert capsys.readouterr().err.endswith("(fan chart, 3 generations, 4 people)\n")


@pytest.mark.parametrize("columns", [40, 80])
def test_help_examples_are_indented_and_exit_codes_have_hanging_indents(
    monkeypatch, capsys, columns
):
    help = help_text(monkeypatch, capsys, columns)
    example, codes = help.split("Example:\n", 1)[1].split("\n\nExit codes:\n")
    assert all(line.startswith("  ") for line in example.splitlines())
    current_code = None
    for line in codes.splitlines():
        if re.match(r"^  [012]: ", line):
            current_code = line[2]
        else:
            assert current_code is not None
            assert line.startswith("     "), line
    assert current_code == "2"


@pytest.mark.parametrize("columns", [40, 50, 80])
def test_copying_help_example_keeps_one_shell_command(monkeypatch, capsys, columns):
    import shlex

    help = help_text(monkeypatch, capsys, columns)
    example = help.split("Example:\n", 1)[1].split("\n\nExit codes:\n")[0]
    command = example.replace("\\\n", "").strip()
    assert "\n" not in command
    assert shlex.split(command) == [
        "uv",
        "run",
        "kincade",
        "docs/examples/george-washington.ged",
        "--root",
        "George Washington",
    ]

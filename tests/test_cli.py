"""The command line (cli.py): --help, --root/--find/--fan/--blank runs, the written PDF
and its summary line, generated file names, and how CLI flags reach the library
options. Each run is kincade.cli.main([...]) in the conftest tmp folder.

Synthetic fixtures only.
"""

import os
import re
import subprocess
import sys
import warnings
from dataclasses import replace

import pytest
from reportlab import rl_config

import kincade.cli
import kincade.lang
import kincade.pdf
from kincade.model import Person, Tree

from conftest import FIX, ROOT, ged
from pdfread import count_pages, drawn


def run_cli(*args):
    """A pedigree run of pedigree.ged, rooted at I1, with extra args appended."""
    return kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "@I1@", *args])


def help_text(monkeypatch, capsys, columns=80):
    monkeypatch.setenv("COLUMNS", str(columns))
    with pytest.raises(SystemExit) as e:
        kincade.cli.main(["-h"])
    assert e.value.code == 0
    return capsys.readouterr().out


# ---------------------------------------------------------------- 1. the help


def test_the_help(monkeypatch, capsys):
    out = help_text(monkeypatch, capsys)
    assert out.startswith(
        "usage: kincade FILE.ged --root PERSON [options]\n"
        "       kincade FILE.ged --root PERSON --fan [options]\n"
        "       kincade FILE.ged --find TEXT [options]\n"
        "       kincade --blank [options]\n"
        "       kincade --show-config [options]\n"
    )
    positions = [
        out.index(f"\n{name}:\n")
        for name in ("person", "content", "page", "config file")
    ]
    assert positions == sorted(positions) and len(set(positions)) == 4
    line = next(ln for ln in out.splitlines() if ln.startswith("  --generations N"))
    assert line.index("show N generations") == 23
    assert max(len(ln) for ln in out.splitlines()) <= 80
    # multi-hyphen option names that argparse's own wrapper would break
    hyphenated = ("--no-event-standins", "--no-shorten-places", "--no-page-numbers")
    for columns in (40, 50, 60, 72, 80, 100, 120):
        wide = help_text(monkeypatch, capsys, columns)
        for line in wide.splitlines():
            assert not line.rstrip().endswith("-"), (columns, line)
        flat = " ".join(wide.split())
        for option in hyphenated:
            assert option in flat, (columns, option)
    example, codes = out.split("Example:\n", 1)[1].split("\n\nExit codes:\n")
    command = example.replace("\\\n", "").strip()
    assert "\n" not in command
    import shlex

    assert shlex.split(command) == [
        "uv",
        "run",
        "kincade",
        "docs/examples/george-washington.ged",
        "--root",
        "George Washington",
    ]
    assert "0: success" in codes and "2: a usage error" in codes


def test_the_module_runs_as_a_command(tmp_path):
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "HOME": str(tmp_path / "home"),
        "USERPROFILE": str(tmp_path / "home"),
    }
    helped = subprocess.run(
        [sys.executable, "-m", "kincade.cli", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert helped.returncode == 0 and helped.stdout.startswith("usage: kincade")
    blanked = subprocess.run(
        [sys.executable, "-m", "kincade.cli", "--blank"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert blanked.returncode == 0, blanked.stderr
    assert (tmp_path / "Blank cascading pedigree.pdf").exists()


# ---------------------------------------------------------------- 3-4. the written PDF


def test_a_pedigree_run(tmp_path, capsys):
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "@I1@"]) == 0
    out = tmp_path / "Jane ASHFORD cascading pedigree.pdf"
    assert count_pages(out.read_bytes()) == 7
    assert (
        capsys.readouterr().err
        == "wrote Jane ASHFORD cascading pedigree.pdf (6 charts, 1 index page, 7 pages)\n"
    )


@pytest.mark.parametrize(
    "flags,summary",
    [
        (["--no-index"], "6 charts, 0 index pages, 6 pages"),
        (["--generations", "1", "--no-index"], "1 chart, 0 index pages, 1 page"),
        (["--large-print"], None),
    ],
)
def test_the_summary_counts(flags, summary, tmp_path, capsys):
    out = tmp_path / "x.pdf"
    assert run_cli("-o", str(out), *flags) == 0
    err = capsys.readouterr().err
    if summary:
        assert err == f"wrote {out} ({summary})\n"
    else:  # large print: the counts agree with the file that was written
        charts, index, pages = map(int, re.findall(r"\d+", err.split("(")[1]))
        assert pages == charts + index == count_pages(out.read_bytes())


# ---------------------------------------------------------------- 5. root resolution


def test_root_resolution(tmp_path):
    out = tmp_path / "Jane ASHFORD cascading pedigree.pdf"
    for root in ("Jane ASHFORD", "jane ash", "I1", "@I1@", "i1"):
        out.unlink(missing_ok=True)
        assert (
            kincade.cli.main(
                [str(FIX / "pedigree.ged"), "--root", root, "--generations", "1"]
            )
            == 0
        ), root
        assert out.exists(), root  # every form writes the same file
    # an exact record ID beats the same ID typed in another case
    tree = Tree(
        {
            pid: Person(pid, given=name)
            for pid, name in (("i1", "Ann"), ("I1", "Bo"), ("x", "Cy"))
        }
    )
    assert [p.id for p in kincade.cli.find_people(tree, "i1")] == ["i1"]
    assert [p.id for p in kincade.cli.find_people(tree, "I1")] == ["I1"]
    # a name in the other Unicode normal form (NFD) is one match
    zoe_nfc, zoe_nfd = "Zoë", "Zoë"
    source = tmp_path / "f.ged"
    source.write_bytes(
        ged(
            "0 @I1@ INDI",
            f"1 NAME {zoe_nfd} /DOE/",
            "0 @I2@ INDI",
            f"1 NAME {zoe_nfd} Ann /DOE/",
        )
    )
    out2 = tmp_path / "x.pdf"
    assert (
        kincade.cli.main([str(source), "--root", f"{zoe_nfc} doe", "-o", str(out2)])
        == 0
    )


# ---------------------------------------------------------------- 6. ambiguous root


def test_an_ambiguous_root_exits_2_with_candidates(tmp_path, capsys):
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "ASHFORD"]) == 2
    err = capsys.readouterr().err
    assert "  I1\tJane ASHFORD" in err and "  I2\tJohn ASHFORD" in err

    path = tmp_path / "many.ged"
    lines = []
    for n in range(1, 61):
        lines += [f"0 @I{n}@ INDI", "1 NAME Jane /DOE/"]
    path.write_bytes(ged(*lines))
    assert kincade.cli.main([str(path), "--root", "Jane DOE"]) == 2
    many = capsys.readouterr().err.splitlines()
    assert many[0] == "kincade: 60 people match 'Jane DOE'; use a record ID:"
    assert many[1:51] == [f"  I{n}\tJane DOE\t" for n in range(1, 51)]
    assert many[51:] == ["  … and 10 more"]

    assert (
        kincade.cli.main(
            [str(FIX / "pedigree.ged"), "--root", "ASHFORD", "--exclude-private"]
        )
        == 2
    )
    private = capsys.readouterr().err
    assert "I1\tLiving\t" in private and "Jane" not in private
    assert "1980" not in private and "1950-2020" in private


# ---------------------------------------------------------------- 7-8. errors


@pytest.mark.parametrize(
    "situation",
    ["no-match", "missing-file", "no-people", "write-error", "bad-lang"],
)
def test_errors_exit_1_with_one_line(situation, tmp_path, capsys, monkeypatch):
    if situation == "no-match":
        assert kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "zzzz"]) == 1
        assert capsys.readouterr() == ("", "kincade: no person matches 'zzzz'\n")
    elif situation == "missing-file":
        monkeypatch.delenv("KINCADE_DEBUG", raising=False)
        assert kincade.cli.main([str(tmp_path / "missing.ged"), "--root", "x"]) == 1
        err = capsys.readouterr().err
        assert err.count("\n") == 1 and err.startswith("kincade: cannot read ")
        monkeypatch.setenv("KINCADE_DEBUG", "1")
        with pytest.raises(FileNotFoundError):
            kincade.cli.main([str(tmp_path / "missing.ged"), "--root", "x"])
    elif situation == "no-people":
        path = tmp_path / "empty.ged"
        path.write_bytes(ged("0 HEAD", "1 GEDC", "2 VERS 5.5.1", "0 @F1@ FAM"))
        assert kincade.cli.main([str(path), "--root", "@I1@"]) == 1
        assert capsys.readouterr().err == f"kincade: no people found in {path}\n"
    elif situation == "write-error":
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        assert (
            kincade.cli.main(
                [
                    str(FIX / "pedigree.ged"),
                    "--root",
                    "@I1@",
                    "-o",
                    str(blocker / "x.pdf"),
                ]
            )
            == 1
        )
        err = capsys.readouterr().err
        assert err.count("\n") == 1 and err.startswith("kincade: cannot write")
    else:  # bad-lang: a bad sort setting with a missing GEDCOM; the language fails first
        bad = tmp_path / "sort.toml"
        bad.write_text('[sort]\nafter_z = ["aa"]\n', encoding="utf-8")
        assert (
            kincade.cli.main(
                [
                    str(tmp_path / "missing.ged"),
                    "--root",
                    "x",
                    "--lang",
                    str(bad),
                ]
            )
            == 1
        )
        err = capsys.readouterr().err
        assert "sort.after_z" in err and err.count("\n") == 1


def test_usage_errors_exit_2(tmp_path, capsys):
    other = tmp_path / "other.toml"
    other.write_text("generations = 9\n", encoding="utf-8")
    argv_by_case = {
        "no file": ["--root", "@I1@"],
        "no root or find": [str(FIX / "pedigree.ged")],
        "zero generations": [
            str(FIX / "pedigree.ged"),
            "--root",
            "@I1@",
            "--generations",
            "0",
        ],
        "blank with find": [str(FIX / "pedigree.ged"), "--blank", "--find", "jane"],
        "config with no-config": ["--config", str(other), "--no-config"],
    }
    needles_by_case = {
        "no file": ("gedcom",),
        "no root or find": ("--root",),
        "zero generations": ("--generations",),
        "blank with find": ("--blank", "--find"),
        "config with no-config": ("--config",),
    }
    for label, argv in argv_by_case.items():
        with pytest.raises(SystemExit) as e:
            kincade.cli.main(argv)
        assert e.value.code == 2, label
        err = capsys.readouterr().err
        for needle in needles_by_case[label]:
            assert needle in err, (label, needle)


# ---------------------------------------------------------------- 9-10. --find


def test_find_lists_people_and_their_families(tmp_path, capsys):
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--find", "mcclure"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "I3\tMary McCLURE\t1952-",
        "    F1\tJohn ASHFORD\tm. 12 Jun 1975\tmp. Akron, Ohio",
        "I6\tWilliam McCLURE\t1925-1999",
        "    F3\tAnn BOND\tm. 1950",
        "I12\tSamuel McCLURE\t1900-1970",
        "    F6\tJane BRUCE\tm. 1 Feb 1925",
    ]

    unions = tmp_path / "unions.ged"
    unions.write_bytes(
        ged(
            "0 @R@ INDI",
            "1 NAME Root /vanDyke/",
            "1 BIRT",
            "2 DATE 1700",
            "1 DEAT",
            "2 DATE 1780",
            "1 FAMS @F2@",
            "1 FAMS @F1@",
            "1 FAMC @FP@",
            "0 @S1@ INDI",
            "1 NAME First /McClure/",
            "1 DEAT Y",
            "0 @S2@ INDI",
            "1 NAME Second /deVries/",
            "1 DEAT Y",
            "0 @P@ INDI",
            "1 NAME Parent /Line/",
            "1 DEAT Y",
            "0 @F1@ FAM",
            "1 HUSB @R@",
            "1 WIFE @S1@",
            "1 MARR",
            "2 DATE 1725",
            "2 PLAC First Town",
            "0 @F2@ FAM",
            "1 HUSB @R@",
            "1 WIFE @S2@",
            "1 MARR",
            "2 DATE 6 JAN 1759",
            "2 PLAC Other Town",
            "0 @FP@ FAM",
            "1 HUSB @P@",
            "1 CHIL @R@",
            "1 MARR",
            "2 DATE 1680",
            "0 @F3@ FAM",  # an actual partner family, missing a reciprocal FAMS
            "1 HUSB @R@",
        )
    )
    assert kincade.cli.main([str(unions), "--find", "R"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "R\tRoot VANDYKE\t1700-1780",
        "    F2\tSecond DEVRIES\tm. 6 Jan 1759\tmp. Other Town\t(default)",
        "    F1\tFirst McCLURE\tm. 1725\tmp. First Town",
        "    F3\tUnknown spouse",
    ]

    for text in ("I3", "@I3@"):
        assert kincade.cli.main([str(FIX / "pedigree.ged"), "--find", text]) == 0
        assert capsys.readouterr().out.splitlines() == [
            "I3\tMary McCLURE\t1952-",
            "    F1\tJohn ASHFORD\tm. 12 Jun 1975\tmp. Akron, Ohio",
        ], text

    zoe_nfd = "Zoë"
    decomposed = tmp_path / "f.ged"
    decomposed.write_bytes(ged("0 @I1@ INDI", f"1 NAME {zoe_nfd} /DOE/"))
    assert kincade.cli.main([str(decomposed), "--find", "doe"]) == 0
    assert "\tZoë DOE\t" in capsys.readouterr().out

    assert kincade.cli.main([str(unions), "--find", "R", "--lang", "de"]) == 0
    assert capsys.readouterr().out.splitlines()[1] == (
        "    F2\tSecond DEVRIES\tverh. 6. Jan. 1759\tin Other Town\t(default)"
    )

    german = tmp_path / "t.ged"
    german.write_bytes(
        ged(
            "0 @I1@ INDI",
            "1 NAME Anna /von der Heide/",
            "1 FAMS @F1@",
            "0 @I2@ INDI",
            "1 NAME Otto /zur Lippe/",
            "1 FAMS @F1@",
            "0 @F1@ FAM",
            "1 WIFE @I1@",
            "1 HUSB @I2@",
        )
    )
    assert kincade.cli.main([str(german), "--find", "Heide", "--lang", "de"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "I1\tAnna von der HEIDE\t",
        "    F1\tOtto zur LIPPE\t(default)",
    ]


def test_find_hides_the_living(tmp_path, capsys):
    assert (
        kincade.cli.main(
            [str(FIX / "pedigree.ged"), "--find", "ashford", "--exclude-private"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "I1\tLiving\t" in out and "1980" not in out
    assert "Jane" not in out
    assert "1950-2020" in out  # John is dead: years shown
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--find", "ashford"]) == 0
    assert "1980-" in capsys.readouterr().out

    for root_living, spouse_living in [(False, True), (True, False)]:
        path = tmp_path / "privacy.ged"
        records = ["0 @R@ INDI", "1 NAME Root /vanDyke/", "1 BIRT"]
        records += ["2 DATE 2000"] if root_living else ["2 DATE 1700", "1 DEAT Y"]
        records += ["1 FAMS @F1@", "0 @S@ INDI", "1 NAME Spouse /deVries/", "1 BIRT"]
        records += ["2 DATE 2000"] if spouse_living else ["2 DATE 1700", "1 DEAT Y"]
        records += [
            "0 @F1@ FAM",
            "1 HUSB @R@",
            "1 WIFE @S@",
            "1 MARR",
            "2 DATE 6 JAN 2021",
            "2 PLAC Private Town",
        ]
        path.write_bytes(ged(*records))
        assert kincade.cli.main([str(path), "--find", "R", "--exclude-private"]) == 0
        rows = capsys.readouterr().out.splitlines()
        assert spouse_living != ("Spouse" in rows[1]), (root_living, spouse_living)
        assert "2021" not in rows[1] and "Private Town" not in rows[1], (
            root_living,
            spouse_living,
        )

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
    assert [ln.split("\t")[2] for ln in lines] == ["", "", "1900-"]


# ---------------------------------------------------------------- 11. fan chart


def test_a_fan_run(tmp_path, capsys):
    assert run_cli("--fan") == 0
    out = tmp_path / "Jane ASHFORD fan chart.pdf"
    pdf = out.read_bytes()
    assert pdf.startswith(b"%PDF") and count_pages(pdf) == 1
    assert b"/MediaBox [ 0 0 792 612 ]" in pdf
    assert (
        capsys.readouterr().err
        == f"wrote {out.name} (fan chart, 6 generations, 23 people)\n"
    )

    out2 = tmp_path / "charts" / "fan.pdf"
    assert run_cli("--fan", "--paper", "a3", "--ink", "bw", "-o", str(out2)) == 0
    pdf2 = out2.read_bytes()
    assert count_pages(pdf2) == 1
    assert b"/MediaBox [ 0 0 1190.55 841.89 ]" in pdf2


# ---------------------------------------------------------------- 12. mode rules


PEDIGREE_ONLY_FLAGS = [
    (["--no-index"], "--no-index"),
    (["--large-print"], "--large-print"),
    (["--shadow"], "--shadow"),
    (["--show-ids"], "--show-ids"),
    (["--no-empty"], "--no-empty"),
    (["--no-shorten-places"], "--no-shorten-places"),
    (["--no-page-numbers"], "--no-page-numbers"),
    (["--generations", "1"], "--generations"),
    (["--generations", "8"], "--generations"),
    (["--blank"], "--blank"),
]
FAN_ONLY_FLAGS = [
    (["--ink", "bw"], "--ink"),
    (["--paper", "tabloid"], "--paper"),
    (["--paper", "a3"], "--paper"),
]


def test_mode_rules_reject_flags_that_do_not_apply(tmp_path, capsys):
    for config_fan in (False, True):
        for flags, flag in PEDIGREE_ONLY_FLAGS:
            config = tmp_path / "kincade.toml"
            if config_fan:
                config.write_text("fan = true\n", encoding="utf-8")
                fan_flags = ["--fan"] if flag == "--blank" else []
            else:
                config.unlink(missing_ok=True)
                fan_flags = ["--fan"]
            with pytest.raises(SystemExit) as e:
                run_cli(*fan_flags, *flags)
            label = (config_fan, flags)
            assert e.value.code == 2, label
            assert flag in capsys.readouterr().err, label
            assert not list(tmp_path.glob("*.pdf")), label

    (tmp_path / "kincade.toml").unlink(missing_ok=True)
    for mode_flags in ([], ["--blank"]):
        for flags, flag in FAN_ONLY_FLAGS:
            with pytest.raises(SystemExit) as e:
                run_cli(*mode_flags, *flags)
            label = (mode_flags, flags)
            assert e.value.code == 2, label
            assert flag in capsys.readouterr().err, label


# ---------------------------------------------------------------- 13-14. file names


def test_generated_file_names_are_safe_and_bounded(tmp_path):
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

    assert kincade.cli.default_output_name("..") == "cascading pedigree.pdf"
    assert (
        kincade.cli.default_output_name("Zoë/Wilks")
        == "Zoë_Wilks cascading pedigree.pdf"
    )
    assert len(
        kincade.cli.default_output_name("中" * 150).encode("utf-8")
    ) <= 200 + len(" cascading pedigree.pdf")

    # the same rules apply to the fan's default name
    assert kincade.cli.default_fan_output_name("Zoë/Wilks") == "Zoë_Wilks fan chart.pdf"
    assert kincade.cli.default_fan_output_name("..") == "fan chart.pdf"
    assert len(
        kincade.cli.default_fan_output_name("中" * 150).encode("utf-8")
    ) <= 200 + len(" fan chart.pdf")

    # a nameless root, with a template that leaves no words once the name is empty
    assert kincade.cli.default_output_name("", {"file_name": "{name}"}) == "Kincade.pdf"


def test_the_file_name_keeps_the_recorded_name_or_says_living(tmp_path, capsys):
    source = tmp_path / "family.ged"
    source.write_bytes(ged("0 @R@ INDI", "1 NAME Alice /McClure/", "1 DEAT Y"))
    assert kincade.cli.main([str(source), "--root", "R"]) == 0
    filename = "Alice McClure cascading pedigree.pdf"
    assert [p.name for p in tmp_path.glob("*.pdf")] == [filename]
    pdf = (tmp_path / filename).read_bytes()
    assert b"Alice McCLURE" in pdf  # the PDF uppercases the surname

    for path in tmp_path.glob("*.pdf"):
        path.unlink()
    private = tmp_path / "private.ged"
    private.write_bytes(ged("0 @I1@ INDI", "1 NAME Jane /Secret/"))
    assert kincade.cli.main([str(private), "--root", "I1", "--exclude-private"]) == 0
    assert (tmp_path / "Living cascading pedigree.pdf").exists()
    assert (
        kincade.cli.main([str(private), "--root", "I1", "--exclude-private", "--fan"])
        == 0
    )
    assert (tmp_path / "Living fan chart.pdf").exists()

    fr = tmp_path / "fr.ged"
    fr.write_bytes(ged("0 @R@ INDI", "1 NAME Alice /McClure/", "1 DEAT Y"))
    assert kincade.cli.main([str(fr), "--root", "R", "--lang", "fr"]) == 0
    assert (tmp_path / "Arbre d'ascendance Alice McClure.pdf").exists()

    # the living verdict uses the full ancestry, not --generations
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
    old = tmp_path / "old.ged"
    old.write_bytes(data)
    assert (
        kincade.cli.main(
            [str(old), "--root", "I1", "--generations", "1", "--exclude-private"]
        )
        == 0
    )
    assert (tmp_path / "Root Old cascading pedigree.pdf").exists()


# ---------------------------------------------------------------- 15-17


def test_warnings_are_plain_lines(tmp_path, capsys, monkeypatch):
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

    make_blank = kincade.cli._make_blank

    def warn_and_make_blank(args):
        warnings.warn("dependency notice", UserWarning, stacklevel=2)
        return make_blank(args)

    monkeypatch.setattr(kincade.cli, "_make_blank", warn_and_make_blank)
    with pytest.warns(UserWarning, match="dependency notice"):
        assert kincade.cli.main(["--no-config", "--blank", "-o", "blank2.pdf"]) == 0


@pytest.mark.usefixtures("no_home_folder")
def test_with_no_home_folder(tmp_path, capsys):
    out = tmp_path / "x.pdf"
    assert run_cli("--generations", "1", "-o", str(out)) == 0
    assert out.exists()
    capsys.readouterr()
    assert run_cli("--lang", "zz", "-o", str(out)) == 1
    err = capsys.readouterr().err
    assert err.startswith("kincade: ") and "Traceback" not in err
    assert kincade.cli.main(["--show-config"]) == 0
    assert "# no config file is read" in capsys.readouterr().out


def test_blank(tmp_path, capsys, monkeypatch, frozen_today):
    monkeypatch.setattr(rl_config, "invariant", 1)
    assert kincade.cli.main(["--blank"]) == 0
    out = tmp_path / "Blank cascading pedigree.pdf"
    assert capsys.readouterr().err == f"wrote {out.name} (1 blank chart, 1 page)\n"

    nested = tmp_path / "new" / "dir" / "x.pdf"
    assert kincade.cli.main(["--blank", "-o", str(nested)]) == 0
    assert nested.exists()

    (tmp_path / "kincade.toml").write_text(
        'gedcom = "missing.ged"\nroot = "@I99@"\n', encoding="utf-8"
    )
    ignored_out = tmp_path / "y.pdf"
    assert (
        kincade.cli.main(
            [
                str(tmp_path / "missing.ged"),
                "--root",
                "@I1@",
                "--blank",
                "-o",
                str(ignored_out),
            ]
        )
        == 0
    )
    assert ignored_out.exists()  # FILE, --root, and the file's gedcom/root are ignored

    (tmp_path / "kincade.toml").write_text('paper = "legal"\n', encoding="utf-8")
    assert kincade.cli.main(["--blank"]) == 2
    assert "paper" in capsys.readouterr().err

    (tmp_path / "kincade.toml").unlink()
    de_out_name = tmp_path / "Leere Ahnentafel.pdf"
    assert kincade.cli.main(["--blank", "--lang", "de"]) == 0
    assert de_out_name.exists()

    assert out.read_bytes() == kincade.pdf.render_blank(
        kincade.pdf.Options(lang=kincade.lang.DEFAULT_STRINGS)
    )


# ---------------------------------------------------------------- 18-19. library options


def test_flags_reach_the_library_options(tmp_path, rendered_options):
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "--generations",
                "3",
                "--paper",
                "a4",
                "--large-print",
                "--shadow",
                "--show-ids",
                "--no-empty",
                "--no-shorten-places",
                "--no-page-numbers",
                "--no-index",
                "--footer",
                "F",
                "--title",
                "T",
                "--lang",
                "de",
                "--adoptive-parents",
                "--no-event-standins",
                "--exclude-private",
                "--preserve-case",
                "--root-family",
                "F101",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    (opts,) = rendered_options
    assert (
        opts.generations,
        opts.exclude_private,
        opts.adoptive_parents,
        opts.event_standins,
        opts.empty_boxes,
        opts.show_ids,
        opts.shorten_places,
        opts.index,
        opts.page_numbers,
        opts.footer,
        opts.title,
        opts.paper,
        opts.large_print,
        opts.shadow,
        opts.preserve_case,
        opts.root_family,
    ) == (
        3,
        True,
        True,
        False,
        False,
        True,
        False,
        False,
        False,
        "F",
        "T",
        "a4",
        True,
        True,
        True,
        "F101",
    )
    assert opts.lang == kincade.lang.load_strings("de")

    rendered_options.clear()
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "--no-footer",
                "-o",
                str(tmp_path / "y.pdf"),
            ]
        )
        == 0
    )
    assert rendered_options[0].footer is False


def test_root_family_on_the_command_line(tmp_path, capsys, monkeypatch):
    gw = ROOT / "docs" / "examples" / "george-washington.ged"
    real = kincade.pdf.render_with_counts
    monkeypatch.setattr(
        kincade.cli,
        "render_with_counts",
        lambda tree, root, opts: real(
            tree, root, replace(opts, compress=False, fonts="base14")
        ),
    )
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                str(gw),
                "--root",
                "I2",
                "--root-family",
                "F2",
                "--generations",
                "2",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    text = drawn(out.read_bytes())
    assert "Mary BALL" in text and "m. 6 Mar 1731" in text
    assert "Jane BUTLER" not in text

    out2 = tmp_path / "y.pdf"
    assert (
        kincade.cli.main(
            [
                str(gw),
                "--root",
                "I2",
                "--root-family",
                "@f2@",
                "--generations",
                "2",
                "-o",
                str(out2),
            ]
        )
        == 0
    )
    assert "Mary BALL" in drawn(out2.read_bytes())

    assert (
        kincade.cli.main(
            [
                str(gw),
                "--root",
                "I2",
                "--root-family",
                "bogus",
                "--generations",
                "2",
                "-o",
                str(tmp_path / "z.pdf"),
            ]
        )
        == 2
    )
    assert "root_family" in capsys.readouterr().err
    assert not (tmp_path / "z.pdf").exists()

    with pytest.raises(SystemExit) as e:
        kincade.cli.main(["--fan", "--root-family", "F2", "--show-config"])
    assert e.value.code == 2
    assert "--root-family is for the pedigree only" in capsys.readouterr().err

    (tmp_path / "kincade.toml").write_text(
        'fan = true\nroot_family = "missing"\n', encoding="utf-8"
    )
    assert kincade.cli.main(["--show-config"]) == 0
    shown = capsys.readouterr().out
    assert "root_family" in shown and "missing" not in shown

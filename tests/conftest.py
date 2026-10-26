"""Fixtures and helpers that many test modules share. The PDF-reading helpers are in
pdfread.py. Every GEDCOM file and tree in the tests is synthetic."""

import datetime
import os
import tempfile
from functools import partial
from pathlib import Path

import pytest

# Reportlab reads home customization files and RL_* overrides at import time.
_IMPORT_HOME = tempfile.TemporaryDirectory(prefix="kincade-tests-")
os.environ["HOME"] = _IMPORT_HOME.name
os.environ["USERPROFILE"] = _IMPORT_HOME.name
for _key in list(os.environ):
    if _key.startswith("RL_"):
        del os.environ[_key]

import kincade.cli  # noqa: E402
import kincade.lang  # noqa: E402
import kincade.pdf  # noqa: E402
from kincade.gedcom import read_gedcom  # noqa: E402
from kincade.pdf import Options  # noqa: E402

from pdfread import drawn  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent  # the repository
FIX = ROOT / "tests" / "fixtures"
TODAY = datetime.date(2026, 10, 10)  # the day every test chart is made
PAPERS = ["letter", "a4"]
PRINTS = [False, True]  # normal print, large print
approx = partial(pytest.approx, abs=0.01)  # the PDF rounds coordinates

# The per-user config file and language folder as the package finds them. The autouse
# fixture replaces both; the tests of where they are use these.
USER_CONFIG_FILE = kincade.cli._user_config_file
USER_LANG_DIR = kincade.lang._user_lang_dir


@pytest.fixture(autouse=True)
def isolated_from_the_machine(tmp_path, monkeypatch, request):
    """Tests never read a config file, language file or font of the machine they run on.
    The working folder is empty (no ./kincade.toml). The home folder is tmp_path/home,
    which holds nothing: HOME, and USERPROFILE for Windows, point there, and
    subprocesses inherit both, with RL_* overrides absent. The per-user config file
    and language folder are absent.
    Tests of those files put their own files in place. fonts="auto" gives the base-14
    fonts, silently, unless the test is marked system_fonts."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("KINCADE_DEBUG", raising=False)
    for key in list(os.environ):
        if key.startswith("RL_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        kincade.cli,
        "_user_config_file",
        lambda: tmp_path / "no-such-user-config.toml",
    )
    monkeypatch.setattr(
        kincade.lang, "_user_lang_dir", lambda: tmp_path / "no-such-user-lang"
    )
    if request.node.get_closest_marker("system_fonts") is None:
        choose = kincade.pdf.choose_fonts
        monkeypatch.setattr(
            kincade.pdf,
            "choose_fonts",
            lambda mode="auto": kincade.pdf.BASE14 if mode == "auto" else choose(mode),
        )


@pytest.fixture
def no_home_folder(monkeypatch):
    """No home folder can be found, as in some containers: Path.home() raises
    RuntimeError. The per-user config file and language folder are looked for as the
    package looks for them."""

    def no_home(cls):
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "home", classmethod(no_home))
    monkeypatch.setattr(kincade.cli, "_user_config_file", USER_CONFIG_FILE)
    monkeypatch.setattr(kincade.lang, "_user_lang_dir", USER_LANG_DIR)


def config_keys():
    """Every key a config file may use."""
    return list(kincade.cli._setting_keys(kincade.cli._parser()))


# ---------------------------------------------------------------- GEDCOM text and trees


def ged(*lines):
    """A GEDCOM file of these lines and the closing TRLR, as bytes."""
    return "\n".join((*lines, "0 TRLR")).encode("utf-8")


def seven(*lines):
    """A GEDCOM 7 file."""
    return ged("0 HEAD", "1 GEDC", "2 VERS 7.0", *lines)


HUGE = "9" * 4301  # more digits than Python's int() will convert


def short(value):
    """A readable pytest id for a long date text."""
    return (
        value
        if not isinstance(value, str) or len(value) < 40
        else f"{value[:10]}...({len(value)} characters)"
    )


def full_pedigree(generations):
    """Every box of a chart `generations` deep is a known person: I1 is the root and the
    father of I(k) is I(2k), the mother I(2k + 1), so the chart draws I1 to
    I(2**generations - 1) and nothing beyond it."""
    n = 2**generations - 1
    lines = []
    for k in range(1, n + 1):
        lines += [f"0 @I{k}@ INDI", f"1 NAME Person{k} /FULL/"]
        if k <= n // 2:
            lines.append(f"1 FAMC @F{k}@")
    for k in range(1, n // 2 + 1):
        lines += [
            f"0 @F{k}@ FAM",
            f"1 HUSB @I{2 * k}@",
            f"1 WIFE @I{2 * k + 1}@",
            f"1 CHIL @I{k}@",
        ]
    return read_gedcom(ged(*lines))


@pytest.fixture(scope="session")
def pedigree():
    """fixtures/pedigree.ged, the general-purpose tree: Jane ASHFORD (I1) and her
    ancestors, six charts and one index page. Tests only read it."""
    return read_gedcom(FIX / "pedigree.ged")


@pytest.fixture(scope="session")
def quirks():
    """fixtures/quirks.ged: GEDCOM written in odd ways. Tests only read it."""
    return read_gedcom(FIX / "quirks.ged")


@pytest.fixture(scope="session")
def long_index_tree():
    """Root (I1) and hundreds of ancestors, each in one box: an index of several pages.
    Tests only read it."""
    lines = ["0 HEAD", "0 @I1@ INDI", "1 NAME Root /ROOT/", "1 FAMC @F1@"]
    for pos in range(1, 400):
        lines += [
            f"0 @I{pos + 1}@ INDI",
            f"1 NAME Person{pos} /FAMILY{pos % 7}/",
            f"1 FAMC @F{pos + 1}@",
        ]
    for pos in range(1, 401):
        lines += [f"0 @F{pos}@ FAM", f"1 HUSB @I{2 * pos}@", f"1 WIFE @I{2 * pos + 1}@"]
    return read_gedcom(ged(*lines))


# ---------------------------------------------------------------- rendering


def render(tree, root="I1", generations=None, parents="birth", **opts):
    """kincade.pdf.render with the test defaults: made on TODAY, in the base-14 fonts
    and uncompressed, so that pdfread can read it. parents="adoptive" sets
    adoptive_parents."""
    opts.setdefault("today", TODAY)
    opts.setdefault("fonts", "base14")
    opts.setdefault("compress", False)
    opts.setdefault("adoptive_parents", parents == "adoptive")
    return kincade.pdf.render(tree, root, Options(generations=generations, **opts))


def render_charts(tree, root="I1", generations=None, parents="birth", **opts):
    """render without the index: the chart pages alone."""
    opts.setdefault("index", False)
    return render(tree, root, generations, parents, **opts)


@pytest.fixture
def frozen_today(monkeypatch):
    """Freeze datetime.date.today() at TODAY. Two renders that each default to
    "today" (Options(today=None)) would otherwise be compared across a real midnight
    boundary and could disagree; this makes both see the same fixed date."""

    class FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return TODAY

    monkeypatch.setattr(datetime, "date", FrozenDate)
    return TODAY


@pytest.fixture
def rendered_options(monkeypatch):
    """The Options of each render the command line makes, in order; the PDF is made as
    usual."""
    seen = []
    real = kincade.pdf.render_with_counts

    def spy(tree, root, opts):
        seen.append(opts)
        return real(tree, root, opts)

    monkeypatch.setattr(kincade.cli, "render_with_counts", spy)
    return seen


# ---------------------------------------------------------------- privacy

# a birth place to look for: drawn only if details are shown
SECRETVILLE = "Secretville"


def dad_and_kid(date, *dad, kid="1950", christening=None):
    """Dad (I2), born on `date` in SECRETVILLE, and his child Kid (I1), born `kid`.
    `dad` are more lines of Dad's record; `christening` dates his christening."""
    return read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Kid /Z/",
            "1 BIRT",
            f"2 DATE {kid}",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Dad /Z/",
            "1 BIRT",
            f"2 DATE {date}",
            f"2 PLAC {SECRETVILLE}",
            *(["1 CHR", f"2 DATE {christening}"] if christening else []),
            *dad,
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
        )
    )


def secret_shown(tree, root="I1", **opts):
    """Whether Dad's birth place is drawn when the details of people who may be living
    are hidden."""
    pdf = render_charts(tree, root, exclude_private=True, **opts)
    return f"bp. {SECRETVILLE}" in drawn(pdf)


# ---------------------------------------------------------------- Kid's families

KID, ADAM, ADA, BERT, BEA, CARL, CORA = "I1", "I2", "I3", "I4", "I5", "I6", "I7"


def indi(xref, name, famc=()):
    """The lines of an INDI record (born 1850, died 1920) with the FAMC list
    [(family, PEDI or "")]."""
    lines = [
        f"0 @{xref}@ INDI",
        f"1 NAME {name}",
        "1 BIRT",
        "2 DATE 1 JAN 1850",
        "1 DEAT",
        "2 DATE 1 JAN 1920",
    ]
    for fam, pedi in famc:
        lines += [f"1 FAMC @{fam}@"] + ([f"2 PEDI {pedi}"] if pedi else [])
    return lines


def kid_tree(famc, status=None, inline=False):
    """Kid (I1) with the FAMC list [(family, PEDI or "")], in a file with three families
    that each have Kid as a child: F1 (Adam and Ada, married 1950), F2 (Bert and Bea,
    1960) and F3 (Carl and Cora, 1970). `status` is {family: CSTA text} on Kid's CHIL
    line in that family, which Kincade ignores: a level-0 CSTA record placed after the
    families, as some programs write it, or with `inline` the text itself.
    """
    lines = ["0 HEAD"] + indi(KID, "Kid /KID/", famc)
    lines += indi(ADAM, "Adam /ONE/") + indi(ADA, "Ada /ONE/")
    lines += (
        indi(BERT, "Bert /TWO/") + indi(BEA, "Bea /TWO/") + indi(CARL, "Carl /THREE/")
    )
    lines += indi(CORA, "Cora /THREE/")
    csta_records = {}
    for fam, husb, wife, year in (
        ("F1", ADAM, ADA, 1950),
        ("F2", BERT, BEA, 1960),
        ("F3", CARL, CORA, 1970),
    ):
        lines += [
            f"0 @{fam}@ FAM",
            f"1 HUSB @{husb}@",
            f"1 WIFE @{wife}@",
            "1 MARR",
            f"2 DATE {year}",
            f"1 CHIL @{KID}@",
        ]
        text = (status or {}).get(fam)
        if text and inline:
            lines.append(f"2 CSTA {text}")
        elif text:
            pointer = csta_records.setdefault(text, f"@C{len(csta_records) + 1}@")
            lines.append(f"2 CSTA {pointer}")
    for text, pointer in csta_records.items():
        lines += [f"0 {pointer} CSTA", f"1 TEXT {text}"]
    return read_gedcom(ged(*lines))

"""The config file: --config PATH, else ./kincade.toml, else
~/.config/kincade/config.toml; --no-config skips the lookup; --show-config prints the
settings in use and where each came from. Keys are the long options without the dashes
and with underscores. Precedence: built-in defaults < config file < command line.

Synthetic fixtures only.
"""

import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import kincade.cli
import kincade.lang

from conftest import FIX, ROOT, config_keys


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def effective(capsys, *argv):
    """(values, sources) from --show-config: the TOML values and the 'where from'
    comment of each line."""
    capsys.readouterr()
    assert kincade.cli.main(["--show-config", *argv]) == 0
    out = capsys.readouterr().out
    set_ones = dict(re.findall(r"^(\w+) = .*  # (.*)$", out, re.MULTILINE))
    unset_ones = dict(re.findall(r"^# (\w+) is not set  # (.*)$", out, re.MULTILINE))
    return tomllib.loads(out), {**unset_ones, **set_ones}


def one_line_error(capsys):
    """The stderr text of a failed run: exactly one line, and never a traceback."""
    err = capsys.readouterr().err
    assert "Traceback" not in err and err.count("\n") == 1, err
    return err


# ---------------------------------------------------------------- 1. lookup order


def test_the_lookup_order(tmp_path, monkeypatch, capsys):
    user = write(tmp_path / "home" / "config.toml", "generations = 2\n")
    monkeypatch.setattr(kincade.cli, "_user_config_file", lambda: user)
    local = write(tmp_path / "kincade.toml", "generations = 3\n")
    values, sources = effective(capsys)
    assert values["generations"] == 3
    assert str(local.resolve()) in sources["generations"]  # local before the user file

    local.unlink()
    values, sources = effective(capsys)
    assert values["generations"] == 2
    assert str(user.resolve()) in sources["generations"]  # user file used alone

    other = write(tmp_path / "other.toml", "generations = 9\n")
    values, _ = effective(capsys, "--config", str(other))
    assert values["generations"] == 9  # --config replaces the lookup

    values, sources = effective(capsys, "--no-config")
    assert "generations" not in values and sources["generations"] == "default"

    # a later call with no --config redoes the lookup: it does not remember "other"
    values, sources = effective(capsys)
    assert values["generations"] == 2 and str(user.resolve()) in sources["generations"]
    cfg = write(tmp_path / "kincade.toml", "generations = 2\n")
    capsys.readouterr()
    kincade.cli.main(["--show-config"])
    assert str(cfg.resolve()) in capsys.readouterr().out


# ---------------------------------------------------------------- 2. precedence


def test_precedence_and_sources(tmp_path, capsys, rendered_options):
    cfg = write(tmp_path / "kincade.toml", "generations = 7\n")
    values, sources = effective(capsys)
    assert values["generations"] == 7 and str(cfg.resolve()) in sources["generations"]
    values, sources = effective(capsys, "--generations", "3")
    assert values["generations"] == 3 and sources["generations"] == "command line"

    write(tmp_path / "kincade.toml", 'root = "@I12@"\ngenerations = 7\n')
    capsys.readouterr()
    assert kincade.cli.main(["--show-config", "--generations", "4"]) == 0
    out = capsys.readouterr().out
    toml_values = tomllib.loads(out)  # the whole output, comments included, is TOML
    assert toml_values["root"] == "@I12@" and toml_values["generations"] == 4
    toml_sources = dict(re.findall(r"^(\w+) = .*  # (.*)$", out, re.MULTILINE))
    assert "config" in toml_sources["root"]
    assert toml_sources["generations"] == "command line"
    assert toml_sources["paper"] == "default"

    settings = tmp_path / "settings"
    write(settings / "data" / "family.ged", "0 TRLR\n")
    cfg = write(settings / "kincade.toml", 'gedcom = "data/family.ged"\n')
    values, sources = effective(capsys, "--config", str(cfg))
    gedcom_path = Path(values["gedcom"])
    assert gedcom_path.is_absolute() and str(cfg.resolve()) in sources["gedcom"]
    assert gedcom_path.resolve() == (settings / "data" / "family.ged").resolve()

    write(tmp_path / "kincade.toml", 'gedcom = "missing.ged"\n')
    out_pdf = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "-o",
                str(out_pdf),
                "--generations",
                "1",
            ]
        )
        == 0
    )
    assert out_pdf.read_bytes().startswith(b"%PDF")  # FILE on the command line wins

    write(tmp_path / "kincade.toml", "no_footer = true\n")
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "-o",
                str(tmp_path / "y.pdf"),
                "--footer",
                "Mine",
            ]
        )
        == 0
    )
    assert rendered_options[-1].footer == "Mine"  # --footer replaces no_footer

    rendered_options.clear()
    write(
        tmp_path / "kincade.toml",
        f"""
gedcom = "{(FIX / "pedigree.ged").as_posix()}"
root = "@I1@"
generations = 3
exclude_private = true
adoptive_parents = true
no_event_standins = true
no_empty = true
show_ids = true
no_shorten_places = true
no_index = true
no_page_numbers = true
footer = "F"
title = "T"
paper = "a4"
large_print = true
shadow = true
lang = "de"
preserve_case = true
root_family = "F101"
""",
    )
    assert kincade.cli.main([]) == 0
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


# ---------------------------------------------------------------- 3. paths in the file


def test_paths_in_the_file(tmp_path, monkeypatch, capsys):
    settings = tmp_path / "settings"
    (settings / "data").mkdir(parents=True)
    shutil.copy(FIX / "pedigree.ged", settings / "data" / "family.ged")
    cfg = write(
        settings / "kincade.toml", 'gedcom = "data/family.ged"\nroot = "@I1@"\n'
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # not the config's folder
    out = elsewhere / "x.pdf"
    assert kincade.cli.main(["--config", str(cfg), "-o", str(out)]) == 0
    assert out.read_bytes().startswith(b"%PDF")  # the relative path resolved from cfg

    home = tmp_path / "home"
    write(home / "family.ged", "0 TRLR\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    write(elsewhere / "kincade.toml", 'gedcom = "~/family.ged"\n')
    values, _ = effective(capsys)
    assert Path(values["gedcom"]).resolve() == (home / "family.ged").resolve()

    write(elsewhere / "kincade.toml", 'output = "~/jane.pdf"\n')
    values, _ = effective(capsys)
    assert Path(values["output"]) == home / "jane.pdf"


# ---------------------------------------------------------------- 4. bad settings


UNKNOWN_KEY = 'rot = "@I1@"\n'
WRONG_TYPE = 'generations = "seven"\n'
BAD_CHOICE = 'paper = "legal"\n'
DUPLICATE_KEY = "shadow = true\nshadow = false\n"
FOOTER_PAIR = 'footer = "X"\nno_footer = true\n'
INK_SEPIA = 'ink = "sepia"\n'

BAD_SETTING_CASES = [
    [(UNKNOWN_KEY, "rot")],
    [(WRONG_TYPE, "generations")],
    [(BAD_CHOICE, "paper")],
    [(DUPLICATE_KEY, "TOML")],
    [(FOOTER_PAIR, "footer"), (INK_SEPIA, "ink")],
]


@pytest.mark.parametrize(
    "rows",
    BAD_SETTING_CASES,
    ids=["unknown-key", "wrong-type", "bad-choice", "invalid-toml", "footer-and-ink"],
)
def test_bad_settings_exit_2_and_name_the_key(tmp_path, capsys, rows):
    for body, key in rows:
        write(tmp_path / "kincade.toml", body)
        assert kincade.cli.main(["--show-config"]) == 2, (body, key)
        err = capsys.readouterr().err
        assert key in err, (body, key, err)
        if key == "rot":
            for valid in (
                "root",
                "generations",
                "gedcom",
                "lang",
                "page_numbers",
                "no_footer",
            ):
                assert valid in err, valid
        if key == "paper":
            assert "letter" in err and "a4" in err


# ---------------------------------------------------------------- 5. file errors


@pytest.fixture
def missing_named_user(monkeypatch):
    """Record every ~user path os.path.expanduser is asked to expand, for a user that
    does not exist, and pretend it cannot be expanded (as the real function would)."""
    expanduser = os.path.expanduser
    attempted = []

    def expand(text):
        if text.startswith("~zz-no-such-user-kincade/"):
            attempted.append(text)
            return text
        return expanduser(text)

    monkeypatch.setattr(os.path, "expanduser", expand)
    return attempted


def test_file_errors_exit_cleanly(tmp_path, capsys, missing_named_user):
    # a missing --config file
    assert (
        kincade.cli.main(["--config", str(tmp_path / "missing.toml"), "--show-config"])
        == 1
    )
    assert "missing.toml" in one_line_error(capsys)

    # a lookup that fails (OSError while checking whether a config file exists)
    import errno

    def _raise(error):
        def fail(self):
            raise error

        return fail

    for error in (
        OSError(errno.ENAMETOOLONG, "File name too long"),
        PermissionError(13, "Permission denied"),
    ):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "is_file", _raise(error))
            assert kincade.cli.main(["--show-config"]) == 1
            err = one_line_error(capsys)
            assert error.strerror in err, error

    # a NUL character in a path given in the file
    for body, key in [
        ('gedcom = "a\\u0000b.ged"\n', "gedcom"),
        ('output = "a\\u0000b.pdf"\n', "output"),
        ('lang = "de\\u0000"\n', "lang"),
    ]:
        write(tmp_path / "kincade.toml", body)
        assert kincade.cli.main(["--show-config"]) == 2, key
        err = one_line_error(capsys)
        assert key in err and "NUL" in err, key

    # a NUL character given on the command line
    (tmp_path / "kincade.toml").unlink()
    for flags, key in [
        (["--output", "a\x00b.pdf"], "output"),
        (["--lang", "de\x00"], "lang"),
        (["--config", "a\x00b.toml"], "config"),
        (["a\x00b.ged"], "file"),
    ]:
        assert kincade.cli.main(["--show-config", *flags]) == 2, key
        err = one_line_error(capsys)
        assert key in err and "NUL" in err, key

    # a tilde user that does not exist, in the file
    for body, key in [
        ('gedcom = "~zz-no-such-user-kincade/x.ged"\n', "gedcom"),
        ('output = "~zz-no-such-user-kincade/x.pdf"\n', "output"),
        ('lang = "~zz-no-such-user-kincade/x.toml"\n', "lang"),
    ]:
        write(tmp_path / "kincade.toml", body)
        assert kincade.cli.main(["--show-config"]) == 2, key
        err = one_line_error(capsys)
        assert key in err and "zz-no-such-user-kincade" in err, key
    assert len(missing_named_user) == 3

    # a tilde user that does not exist, on the command line
    missing_named_user.clear()
    (tmp_path / "kincade.toml").unlink()
    assert (
        kincade.cli.main(
            ["--show-config", "--config", "~zz-no-such-user-kincade/x.toml"]
        )
        == 2
    )
    err = one_line_error(capsys)
    assert "config" in err
    assert len(missing_named_user) == 1

    # a whole number too long for tomllib
    write(tmp_path / "kincade.toml", "generations = " + "9" * 5000 + "\n")
    assert kincade.cli.main(["--show-config"]) == 2
    assert "TOML" in one_line_error(capsys)


# ---------------------------------------------------------------- 6. --show-config is TOML


def test_show_config_output_is_valid_toml(tmp_path, capsys):
    text = 'q"b\\\x01\x08\x0c\x1f\x7f\x85x\ny\rz\t'
    write(
        tmp_path / "kincade.toml",
        "title = "
        + '"'
        + "".join(
            {'"': '\\"', "\\": "\\\\"}.get(
                ch, ch if ord(ch) >= 32 and ch != "\x7f" else f"\\u{ord(ch):04x}"
            )
            for ch in text
        )
        + '"\n',
    )
    capsys.readouterr()
    assert kincade.cli.main(["--show-config"]) == 0
    out = capsys.readouterr().out
    assert tomllib.loads(out)["title"] == text
    assert "\x7f" not in out and all(
        ord(ch) >= 32 or ch == "\t" for ch in out if ch != "\n"
    )

    write(tmp_path / "kincade.toml", 'title = "\u65e5\u672c \\u007f"\n')
    env = {**os.environ, "PYTHONIOENCODING": "ascii", "PYTHONPATH": str(ROOT)}
    done = subprocess.run(
        [sys.executable, "-m", "kincade.cli", "--show-config"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr.decode("ascii", "replace")
    assert tomllib.loads(done.stdout.decode("ascii"))["title"] == "?? \x7f"


# ---------------------------------------------------------------- 7. defaults with no tree


def test_show_config_needs_no_tree_and_shows_mode_defaults(tmp_path, capsys):
    assert kincade.cli.main(["--show-config", "--no-config"]) == 0
    out = capsys.readouterr().out
    assert "gedcom is not set" in out and "root is not set" in out

    assert (
        kincade.cli.main(
            [str(tmp_path / "missing.ged"), "--root", "@I1@", "--show-config"]
        )
        == 0
    )  # it never reads the GEDCOM

    values, sources = effective(capsys, "--fan")
    assert (values["fan"], values["ink"], values["generations"]) == (True, "color", 6)
    assert sources["fan"] == "command line" and sources["ink"] == "default"


# ---------------------------------------------------------------- 8. mode settings


def test_mode_settings_from_the_file(tmp_path, capsys, rendered_options):
    write(
        tmp_path / "kincade.toml",
        """fan = true
generations = 8
no_index = true
large_print = true
shadow = true
show_ids = true
no_empty = true
no_shorten_places = true
no_page_numbers = true
ink = "grayscale"
paper = "a3"
""",
    )
    values, sources = effective(capsys)
    assert values["fan"] is True and values["ink"] == "grayscale"
    assert values["paper"] == "a3" and values["generations"] == 6
    assert sources["generations"] == "default"
    for key in (
        "no_index",
        "large_print",
        "shadow",
        "show_ids",
        "no_empty",
        "no_shorten_places",
        "no_page_numbers",
    ):
        assert values[key] is False and sources[key] == "default", key
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "I1"]) == 0
    assert (tmp_path / "Jane ASHFORD fan chart.pdf").exists()
    assert "fan chart, 6 generations, 23 people" in capsys.readouterr().err

    write(tmp_path / "kincade.toml", 'ink = "bw"\npaper = "tabloid"\n')
    values, sources = effective(capsys)
    assert (values["fan"], values["ink"], values["paper"]) == (False, "color", "letter")
    assert sources["ink"] == sources["paper"] == "default"
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "I1"]) == 0
    assert rendered_options[-1].paper == "letter"  # the fan-only keys are ignored

    for pdf in tmp_path.glob("*.pdf"):
        pdf.unlink()
    write(tmp_path / "kincade.toml", "fan = true\n")
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--find",
                "I1",
                "--ink",
                "bw",
                "--paper",
                "a3",
                "--no-index",
                "--generations",
                "10",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == (
        "I1\tJane ASHFORD\t1980-\n"
        "    F101\tTom BAKER\tm. 5 Jun 2005\tmp. Peoria, Illinois\t(default)\n"
    )
    assert not list(tmp_path.glob("*.pdf"))  # --find skipped the mode checks

    write(tmp_path / "kincade.toml", 'fan = true\nink = "bw"\npaper = "a3"\n')
    assert kincade.cli.main(["--blank", "--large-print"]) == 0
    assert "1 blank chart, 1 page" in capsys.readouterr().err
    assert (tmp_path / "Blank cascading pedigree.pdf").exists()
    replay = tmp_path / "Blank cascading pedigree.pdf"
    assert b"/MediaBox [ 0 0 612 792 ]" in replay.read_bytes()  # the pedigree's letter


# ---------------------------------------------------------------- 9. keys are long options


def test_every_key_is_a_long_option(tmp_path, capsys):
    keys = sorted(config_keys())
    assert "gedcom" in keys and "root" in keys and "no_footer" in keys
    assert all(re.fullmatch(r"[a-z][a-z_]*", key) for key in keys)
    assert "find" not in keys and "blank" not in keys and "fonts" not in keys

    switches = [
        "--fan",
        "--no-empty",
        "--no-index",
        "--no-page-numbers",
        "--no-shorten-places",
        "--no-event-standins",
        "--shadow",
        "--large-print",
        "--show-ids",
        "--exclude-private",
        "--adoptive-parents",
    ]

    def parse(key, *flags):
        return getattr(
            kincade.cli._parser().parse_args(["x.ged", "--root", "I1", *flags]),
            key,
        )

    for flag in switches:
        key = flag[2:].replace("-", "_")
        assert (
            parse(key) is False
            and parse(key, flag) is True
            and parse(key, flag, flag) is True
        ), flag
        write(tmp_path / "kincade.toml", f"{key} = true\n")
        values, _ = effective(capsys)
        assert values[key] is True, flag
        assert key in keys, flag

    write(tmp_path / "f.toml", 'find = "ashford"\n')
    out = tmp_path / "y.pdf"
    assert (
        kincade.cli.main(
            [
                "--config",
                str(tmp_path / "f.toml"),
                str(FIX / "pedigree.ged"),
                "--root",
                "I1",
                "-o",
                str(out),
            ]
        )
        == 2
    )
    assert "unknown key 'find'" in capsys.readouterr().err
    assert not out.exists()

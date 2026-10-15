"""The config file: --config PATH, else ./kincade.toml, else
~/.config/kincade/config.toml; --no-config skips the lookup; --show-config prints the
settings in use and where each came from. Keys are the long options without the dashes
and with underscores. Precedence: built-in defaults < config file < command line. Each
on/off option has one flag, the one the help shows, and one key of the same name; it has
no opposite flag and no opposite key.

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
import kincade.pdf

from conftest import FIX, ROOT, config_keys


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def effective(capsys, *argv):
    """(values, sources) from --show-config: the TOML values and the 'where from'
    comment of each line.
    """
    capsys.readouterr()
    assert kincade.cli.main(["--show-config", *argv]) == 0
    out = capsys.readouterr().out
    set_ones = dict(re.findall(r"^(\w+) = .*  # (.*)$", out, re.MULTILINE))
    unset_ones = dict(re.findall(r"^# (\w+) is not set  # (.*)$", out, re.MULTILINE))
    return tomllib.loads(out), {**unset_ones, **set_ones}


# ---------------------------------------------------------------- command lines


COMMAND_LINES = [
    ["--root", "@I1@"],
    ["--find", "jane"],
    ["--root", "@I1@", "-o", "x.pdf"],
    ["--root", "@I1@", "--output", "x.pdf"],
    ["--root", "@I1@", "--generations", "4"],
    ["--root", "@I1@", "--no-empty"],
    ["--root", "@I1@", "--shadow"],
    ["--root", "@I1@", "--no-index"],
    ["--root", "@I1@", "--exclude-private"],
    ["--root", "@I1@", "--no-footer"],
    ["--root", "@I1@", "--footer", "Mine"],
    ["--root", "@I1@", "--title", "T"],
    ["--root", "@I1@", "--lang", "de"],
    ["--root", "@I1@", "--paper", "a4"],
    ["--root", "@I1@", "--no-event-standins"],
    ["--root", "@I1@", "--no-page-numbers"],
    ["--root", "@I1@", "--adoptive-parents"],
    [
        "--root",
        "@I1@",
        "--no-empty",
        "--shadow",
        "--no-index",
        "--exclude-private",
        "--no-event-standins",
        "--no-page-numbers",
        "--no-footer",
        "--paper",
        "a4",
        "--generations",
        "3",
        "--adoptive-parents",
    ],
]


@pytest.mark.parametrize("flags", COMMAND_LINES, ids=" ".join)
def test_these_command_lines_parse(flags):
    # exits with status 2 if it does not
    kincade.cli._parser().parse_args(["x.ged", *flags])


def test_these_command_lines_render(tmp_path, rendered_options):
    out = tmp_path / "all.pdf"
    flags = [
        "--no-empty",
        "--shadow",
        "--no-index",
        "--exclude-private",
        "--no-event-standins",
        "--no-page-numbers",
        "--no-footer",
        "--paper",
        "a4",
        "--generations",
        "3",
        "--adoptive-parents",
    ]
    assert (
        kincade.cli.main(
            [str(FIX / "pedigree.ged"), "--root", "@I1@", "-o", str(out), *flags]
        )
        == 0
    )
    (opts,) = rendered_options
    assert (
        opts.empty_boxes,
        opts.shadow,
        opts.index,
        opts.exclude_private,
        opts.event_standins,
        opts.page_numbers,
        opts.footer,
        opts.paper,
        opts.adoptive_parents,
        opts.generations,
    ) == (False, True, False, True, False, False, False, "a4", True, 3)


def test_fonts_is_a_library_option_the_command_line_never_sets(
    tmp_path, rendered_options
):
    """The command line renders with Options.fonts "auto", the default, and has no flag
    for it."""
    assert kincade.pdf.Options().fonts == "auto"
    assert (
        kincade.cli.main(
            [str(FIX / "pedigree.ged"), "--root", "@I1@", "-o", str(tmp_path / "x.pdf")]
        )
        == 0
    )
    assert rendered_options[-1].fonts == "auto"
    assert not hasattr(
        kincade.cli._parser().parse_args(["x.ged", "--root", "I1"]), "fonts"
    )


# every on/off option: its one flag, which is also the setting's name (with
# underscores); all of them are off by default
SWITCHES = [
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


def key_of(flag):
    return flag[2:].replace("-", "_")


@pytest.mark.parametrize("flag", SWITCHES)
def test_boolean_settings_have_one_flag_and_are_off_by_default(flag):
    def parse(*flags):
        return getattr(
            kincade.cli._parser().parse_args(["x.ged", "--root", "I1", *flags]),
            key_of(flag),
        )

    assert parse() is False and parse(flag) is True and parse(flag, flag) is True


# ---------------------------------------------------------------- discovery


def test_a_kincade_toml_in_the_current_folder_comes_before_the_user_file(
    tmp_path, monkeypatch, capsys
):
    user = write(tmp_path / "home" / "config.toml", "generations = 2\n")
    monkeypatch.setattr(kincade.cli, "_user_config_file", lambda: user)
    # the test's folder is the working folder
    local = write(tmp_path / "kincade.toml", "generations = 3\n")
    values, sources = effective(capsys)
    assert values["generations"] == 3 and str(local.resolve()) in sources["generations"]


def test_the_user_file_is_used_when_there_is_no_local_file(
    tmp_path, monkeypatch, capsys
):
    user = write(tmp_path / "home" / "config.toml", "generations = 2\n")
    monkeypatch.setattr(kincade.cli, "_user_config_file", lambda: user)
    values, sources = effective(capsys)
    assert values["generations"] == 2 and str(user.resolve()) in sources["generations"]


def test_with_no_file_at_all_the_defaults_are_used(capsys):
    values, sources = effective(capsys)
    assert "generations" not in values and sources["generations"] == "default"
    assert values["paper"] == "letter" and values["no_empty"] is False


def test_no_config_skips_the_local_and_the_user_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        kincade.cli,
        "_user_config_file",
        lambda: write(tmp_path / "u.toml", "generations = 2\n"),
    )
    write(tmp_path / "kincade.toml", "generations = 3\n")
    values, sources = effective(capsys, "--no-config")
    assert "generations" not in values and sources["generations"] == "default"


def test_config_replaces_the_lookup(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        kincade.cli,
        "_user_config_file",
        lambda: write(tmp_path / "u.toml", "generations = 2\n"),
    )
    write(tmp_path / "kincade.toml", "generations = 3\n")
    other = write(tmp_path / "other.toml", "generations = 9\n")
    values, _ = effective(capsys, "--config", str(other))
    assert values["generations"] == 9


def test_config_and_no_config_together_are_a_usage_error(tmp_path):
    other = write(tmp_path / "other.toml", "generations = 9\n")
    with pytest.raises(SystemExit) as e:
        kincade.cli.main(["--config", str(other), "--no-config"])
    assert e.value.code == 2


def test_a_missing_config_file_given_on_the_command_line_exits_1(tmp_path, capsys):
    assert (
        kincade.cli.main(["--config", str(tmp_path / "missing.toml"), "--show-config"])
        == 1
    )
    assert "missing.toml" in capsys.readouterr().err


# ---------------------------------------------------------------- precedence


def test_the_config_file_sets_a_value_and_the_command_line_overrides_it(
    tmp_path, capsys
):
    cfg = write(tmp_path / "kincade.toml", "generations = 7\n")
    values, sources = effective(capsys)
    assert values["generations"] == 7 and str(cfg.resolve()) in sources["generations"]
    values, sources = effective(capsys, "--generations", "3")
    assert values["generations"] == 3 and sources["generations"] == "command line"


@pytest.mark.parametrize(
    "config,flags,key,expected",
    [
        ("no_index = true\n", [], "no_index", True),  # the file alone
        ("no_index = false\n", [], "no_index", False),
        (
            "no_index = false\n",
            ["--no-index"],
            "no_index",
            True,
        ),  # file says no, command line says yes
        ("exclude_private = true\n", [], "exclude_private", True),
        ("exclude_private = false\n", ["--exclude-private"], "exclude_private", True),
        ("shadow = true\n", [], "shadow", True),
        ("no_event_standins = true\n", [], "no_event_standins", True),
        ("adoptive_parents = true\n", [], "adoptive_parents", True),
        ("no_page_numbers = true\n", [], "no_page_numbers", True),
        ("no_empty = true\n", [], "no_empty", True),
    ],
)
def test_a_boolean_is_set_by_the_file_and_by_the_flag(
    tmp_path, capsys, config, flags, key, expected
):
    write(tmp_path / "kincade.toml", config)
    values, _ = effective(capsys, *flags)
    assert values[key] is expected


@pytest.mark.parametrize("flag", SWITCHES)
def test_every_switch_has_one_key_with_the_flags_own_name(tmp_path, capsys, flag):
    write(tmp_path / "kincade.toml", f"{key_of(flag)} = true\n")
    values, _ = effective(capsys)
    assert values[key_of(flag)] is True
    assert key_of(flag) in config_keys()


def test_show_config_prints_keys_that_a_config_file_accepts(tmp_path, capsys):
    """What --show-config prints can be saved as kincade.toml: every key in it is a key
    the file may use, and the file gives the same settings back.
    """
    flags = [
        "--no-index",
        "--no-empty",
        "--shadow",
        "--exclude-private",
        "--no-page-numbers",
        "--paper",
        "a4",
    ]
    assert kincade.cli.main(["--show-config", "--no-config", *flags]) == 0
    printed = capsys.readouterr().out
    assert set(tomllib.loads(printed)) <= set(config_keys())
    write(tmp_path / "kincade.toml", printed)
    values, _ = effective(capsys)
    assert values == tomllib.loads(printed)


def test_a_key_given_twice_in_one_file_is_a_toml_error(tmp_path, capsys):
    write(tmp_path / "kincade.toml", "shadow = true\nshadow = false\n")
    assert kincade.cli.main(["--show-config"]) == 2
    assert "not valid TOML" in capsys.readouterr().err


def test_footer_and_no_footer_cannot_both_be_in_one_file(tmp_path, capsys):
    write(tmp_path / "kincade.toml", 'footer = "X"\nno_footer = true\n')
    assert kincade.cli.main(["--show-config"]) == 2
    assert "footer" in capsys.readouterr().err


def test_a_footer_on_the_command_line_replaces_no_footer_from_the_file(
    tmp_path, rendered_options
):
    write(tmp_path / "kincade.toml", "no_footer = true\n")
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "-o",
                str(out),
                "--footer",
                "Mine",
            ]
        )
        == 0
    )
    assert rendered_options[-1].footer == "Mine"


def test_the_file_sets_options_that_reach_the_pdf(tmp_path, rendered_options):
    write(tmp_path / "kincade.toml", 'title = "From file"\npaper = "a4"\nlang = "de"\n')
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "-o",
                str(out),
                "--generations",
                "2",
            ]
        )
        == 0
    )
    assert (rendered_options[-1].title, rendered_options[-1].paper) == (
        "From file",
        "a4",
    )
    # lang = "de" from the file
    assert rendered_options[-1].lang["index"]["title"] == "Namensregister"


# ---------------------------------------------------------------- the GEDCOM path


def test_a_relative_gedcom_path_is_read_from_the_config_folder(tmp_path, monkeypatch):
    settings = tmp_path / "settings"
    (settings / "data").mkdir(parents=True)
    shutil.copy(FIX / "pedigree.ged", settings / "data" / "family.ged")
    cfg = write(
        settings / "kincade.toml", 'gedcom = "data/family.ged"\nroot = "@I1@"\n'
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # not the config's folder: the path resolves from the config's
    monkeypatch.chdir(elsewhere)
    out = elsewhere / "x.pdf"
    assert kincade.cli.main(["--config", str(cfg), "-o", str(out)]) == 0
    assert out.read_bytes().startswith(b"%PDF")


def test_the_gedcom_key_is_shown_as_an_absolute_path(tmp_path, capsys):
    settings = tmp_path / "settings"
    write(settings / "data" / "family.ged", "0 TRLR\n")
    cfg = write(settings / "kincade.toml", 'gedcom = "data/family.ged"\n')
    values, sources = effective(capsys, "--config", str(cfg))
    assert (
        Path(values["gedcom"]).resolve() == (settings / "data" / "family.ged").resolve()
    )
    assert (
        Path(values["gedcom"]).is_absolute() and str(cfg.resolve()) in sources["gedcom"]
    )


def test_a_tilde_in_the_gedcom_path_is_the_home_folder(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    write(home / "family.ged", "0 TRLR\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    write(tmp_path / "kincade.toml", 'gedcom = "~/family.ged"\n')
    values, _ = effective(capsys)
    assert Path(values["gedcom"]).resolve() == (home / "family.ged").resolve()


def test_a_file_on_the_command_line_overrides_the_gedcom_key(tmp_path):
    write(tmp_path / "kincade.toml", 'gedcom = "missing.ged"\n')
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "-o",
                str(out),
                "--generations",
                "1",
            ]
        )
        == 0
    )
    assert out.read_bytes().startswith(b"%PDF")


def test_without_a_file_anywhere_the_command_exits_2(tmp_path, capsys):
    # a usage error: no file on the command line or in a config file
    with pytest.raises(SystemExit) as e:
        kincade.cli.main(["--root", "@I1@", "-o", str(tmp_path / "x.pdf")])
    assert e.value.code == 2 and "gedcom" in capsys.readouterr().err


# ---------------------------------------------------------------- errors in the file


@pytest.mark.parametrize(
    "body,key",
    [
        ('rot = "@I1@"\n', "rot"),  # unknown key
        ('generations = "seven"\n', "generations"),  # wrong type
        ('exclude_private = "yes"\n', "exclude_private"),
        ("no_index = 1\n", "no_index"),
        ("title = 3\n", "title"),
        ("gedcom = 7\n", "gedcom"),
        ('paper = "legal"\n', "paper"),  # not one of the choices
        ("generations = 0\n", "generations"),
    ],
)
def test_a_bad_setting_exits_2_and_names_the_key(tmp_path, capsys, body, key):
    write(tmp_path / "kincade.toml", body)
    assert kincade.cli.main(["--show-config"]) == 2
    assert key in capsys.readouterr().err


def test_an_unknown_key_lists_the_valid_keys(tmp_path, capsys):
    write(tmp_path / "kincade.toml", 'rot = "@I1@"\n')
    assert kincade.cli.main(["--show-config"]) == 2
    err = capsys.readouterr().err
    assert "'rot'" in err
    for key in ("root", "generations", "gedcom", "lang", "page_numbers", "no_footer"):
        assert key in err, key


def test_a_paper_error_lists_the_choices(tmp_path, capsys):
    write(tmp_path / "kincade.toml", 'paper = "legal"\n')
    assert kincade.cli.main(["--show-config"]) == 2
    err = capsys.readouterr().err
    assert "letter" in err and "a4" in err


def test_invalid_toml_exits_2(tmp_path, capsys):
    write(tmp_path / "kincade.toml", 'root = "unclosed\n')
    assert kincade.cli.main(["--show-config"]) == 2
    assert "TOML" in capsys.readouterr().err


# ---------------------------------------------------------------- --show-config


def test_show_config_prints_toml_with_the_source_of_each_setting(tmp_path, capsys):
    write(tmp_path / "kincade.toml", 'root = "@I12@"\ngenerations = 7\n')
    capsys.readouterr()
    assert kincade.cli.main(["--show-config", "--generations", "4"]) == 0
    out = capsys.readouterr().out
    # the comments are TOML comments, so the whole output parses
    values = tomllib.loads(out)
    assert values["root"] == "@I12@" and values["generations"] == 4
    sources = dict(re.findall(r"^(\w+) = .*  # (.*)$", out, re.MULTILINE))
    assert "config" in sources["root"] and sources["generations"] == "command line"
    assert sources["paper"] == "default"


def test_show_config_needs_no_file_and_no_root(capsys):
    assert kincade.cli.main(["--show-config", "--no-config"]) == 0
    out = capsys.readouterr().out
    assert "gedcom is not set" in out and "root is not set" in out


def test_show_config_does_not_read_the_gedcom(tmp_path):
    assert (
        kincade.cli.main(
            [str(tmp_path / "missing.ged"), "--root", "@I1@", "--show-config"]
        )
        == 0
    )


def test_show_config_names_the_file_it_read(tmp_path, capsys):
    cfg = write(tmp_path / "kincade.toml", "generations = 2\n")
    capsys.readouterr()
    kincade.cli.main(["--show-config"])
    assert str(cfg.resolve()) in capsys.readouterr().out
    capsys.readouterr()
    kincade.cli.main(["--show-config", "--no-config"])
    assert "no config file" in capsys.readouterr().out


# ---------------------------------------------------------------- the example file


def test_every_key_is_a_long_option_name_without_dashes():
    keys = sorted(config_keys())
    assert "gedcom" in keys and "root" in keys and "no_footer" in keys
    assert all(re.fullmatch(r"[a-z][a-z_]*", key) for key in keys)


def test_find_is_not_a_config_key(tmp_path, capsys):
    """--find is a mode of one run, like --blank: in a config file it is an unknown key,
    so it can never turn a run with --root into a list."""
    assert "find" not in config_keys()
    write(tmp_path / "f.toml", 'find = "ashford"\n')
    out = tmp_path / "y.pdf"
    argv = ["--config", str(tmp_path / "f.toml"), str(FIX / "pedigree.ged")]
    assert kincade.cli.main([*argv, "--root", "I1", "-o", str(out)]) == 2
    assert "unknown key 'find'" in capsys.readouterr().err
    assert not out.exists()


# ----------------------------------------------------------------
# values that cannot be used: one line, exit 2


def one_line_error(capsys):
    """The stderr text of a failed run: exactly one line, and never a traceback."""
    err = capsys.readouterr().err
    assert "Traceback" not in err and err.count("\n") == 1, err
    return err


def test_a_whole_number_too_long_for_tomllib_is_a_clean_error(tmp_path, capsys):
    write(tmp_path / "kincade.toml", "generations = " + "9" * 5000 + "\n")
    assert kincade.cli.main(["--show-config"]) == 2
    assert "TOML" in one_line_error(capsys)


@pytest.mark.parametrize(
    "body,key",
    [
        ('gedcom = "a\\u0000b.ged"\n', "gedcom"),
        ('output = "a\\u0000b.pdf"\n', "output"),
        ('lang = "de\\u0000"\n', "lang"),
    ],
)
def test_a_nul_character_in_a_path_in_the_file_is_a_clean_error(
    tmp_path, capsys, body, key
):
    write(tmp_path / "kincade.toml", body)
    assert kincade.cli.main(["--show-config"]) == 2
    err = one_line_error(capsys)
    assert key in err and "NUL" in err


@pytest.mark.parametrize(
    "flags,key",
    [
        (["--output", "a\x00b.pdf"], "output"),
        (["--lang", "de\x00"], "lang"),
        (["--config", "a\x00b.toml"], "config"),
        (["a\x00b.ged"], "file"),
    ],
)
def test_a_nul_character_on_the_command_line_is_a_clean_error(capsys, flags, key):
    assert kincade.cli.main(["--show-config", *flags]) == 2
    err = one_line_error(capsys)
    assert key in err and "NUL" in err


@pytest.mark.parametrize(
    "body,key",
    [
        ('gedcom = "~zz-no-such-user-kincade/x.ged"\n', "gedcom"),
        ('output = "~zz-no-such-user-kincade/x.pdf"\n', "output"),
        ('lang = "~zz-no-such-user-kincade/x.toml"\n', "lang"),
    ],
)
def test_a_tilde_user_that_does_not_exist_is_a_clean_error_that_names_the_key(
    tmp_path, capsys, body, key, missing_named_user
):
    write(tmp_path / "kincade.toml", body)
    assert kincade.cli.main(["--show-config"]) == 2
    err = one_line_error(capsys)
    assert key in err and "zz-no-such-user-kincade" in err
    assert len(missing_named_user) == 1


@pytest.fixture
def missing_named_user(monkeypatch):
    expanduser = os.path.expanduser
    attempted = []

    def expand(text):
        if text.startswith("~zz-no-such-user-kincade/"):
            attempted.append(text)
            return text
        return expanduser(text)

    monkeypatch.setattr(os.path, "expanduser", expand)
    return attempted


def test_a_tilde_user_on_the_command_line_is_a_clean_error_naming_config(
    capsys, missing_named_user
):
    assert (
        kincade.cli.main(
            ["--show-config", "--config", "~zz-no-such-user-kincade/x.toml"]
        )
        == 2
    )
    assert "config" in one_line_error(capsys)
    assert len(missing_named_user) == 1


def test_a_tilde_in_the_output_key_is_the_home_folder(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    write(tmp_path / "kincade.toml", 'output = "~/jane.pdf"\n')
    values, _ = effective(capsys)
    assert Path(values["output"]) == home / "jane.pdf"


# ----------------------------------------------------------------
# --show-config is always valid TOML


def test_show_config_output_parses_when_a_value_has_a_delete_and_a_tab(
    tmp_path, capsys
):
    write(tmp_path / "kincade.toml", 'title = "a\\u007fb\\tc"\n')
    capsys.readouterr()
    assert kincade.cli.main(["--show-config"]) == 0
    assert tomllib.loads(capsys.readouterr().out)["title"] == "a\x7fb\tc"


def test_show_config_escapes_every_control_character_it_writes(tmp_path, capsys):
    text = 'q"b\\\x01\x08\x0c\x1f\x7f\x85x\ny\rz'
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


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="a Windows file name cannot hold a line feed",
)
def test_show_config_comments_survive_a_config_path_with_control_characters(
    tmp_path, capsys
):
    cfg = write(tmp_path / "we\x7fird\nname.toml", "generations = 2\n")
    capsys.readouterr()
    assert kincade.cli.main(["--config", str(cfg), "--show-config"]) == 0
    values = tomllib.loads(capsys.readouterr().out)
    assert values["generations"] == 2


def test_show_config_is_valid_toml_on_an_ascii_terminal(tmp_path):
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


def test_the_per_user_files_live_under_dot_config_kincade(tmp_path, user_files):
    config_file, lang_dir = user_files
    home = tmp_path / "home"  # HOME, as conftest sets it
    assert config_file() == home / ".config" / "kincade" / "config.toml"
    assert lang_dir() == home / ".config" / "kincade" / "lang"


# ---------------------------------------------------------------- mode settings


@pytest.mark.parametrize("generations", [1, 8, 10])
def test_fan_config_ignores_pedigree_keys_and_an_inapplicable_generation_limit(
    tmp_path, capsys, generations
):
    write(
        tmp_path / "kincade.toml",
        f"""fan = true
generations = {generations}
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
        assert values[key] is False and sources[key] == "default"
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "I1"]) == 0
    assert (tmp_path / "Jane ASHFORD fan chart.pdf").exists()
    assert "fan chart, 6 generations, 23 people" in capsys.readouterr().err


@pytest.mark.parametrize("paper", ["tabloid", "a3"])
def test_pedigree_ignores_fan_config_settings(
    tmp_path, capsys, rendered_options, paper
):
    write(tmp_path / "kincade.toml", f'ink = "bw"\npaper = "{paper}"\n')
    values, sources = effective(capsys)
    assert (values["fan"], values["ink"], values["paper"]) == (False, "color", "letter")
    assert sources["ink"] == sources["paper"] == "default"
    assert kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "I1"]) == 0
    assert rendered_options[-1].paper == "letter"


def test_find_takes_priority_over_fan_and_skips_mode_checks(tmp_path, capsys):
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
    assert not list(tmp_path.glob("*.pdf"))


def test_blank_takes_priority_over_config_fan_and_uses_pedigree_paper(
    tmp_path, monkeypatch, capsys
):
    write(tmp_path / "kincade.toml", 'fan = true\nink = "bw"\npaper = "a3"\n')
    seen = []
    real = kincade.cli.render_blank

    def render(opts):
        seen.append(opts)
        return real(opts)

    monkeypatch.setattr(kincade.cli, "render_blank", render)
    assert kincade.cli.main(["--blank", "--large-print"]) == 0
    assert (seen[-1].paper, seen[-1].large_print) == ("letter", True)
    assert (tmp_path / "Blank cascading pedigree.pdf").exists()
    assert "1 blank chart, 1 page" in capsys.readouterr().err


@pytest.mark.parametrize(
    "body,key",
    [
        ('fan = "yes"\n', "fan"),
        ('ink = "sepia"\n', "ink"),
        ("fan = true\ngenerations = 0\n", "generations"),
        ('fan = true\npaper = "legal"\n', "paper"),
    ],
)
def test_config_rejects_values_neither_mode_accepts(tmp_path, capsys, body, key):
    write(tmp_path / "kincade.toml", body)
    assert kincade.cli.main(["--show-config"]) == 2
    assert key in capsys.readouterr().err


def test_show_config_includes_fan_and_ink_and_the_fan_default_generations(capsys):
    values, sources = effective(capsys, "--fan")
    assert (values["fan"], values["ink"], values["generations"]) == (True, "color", 6)
    assert sources["fan"] == "command line" and sources["ink"] == "default"

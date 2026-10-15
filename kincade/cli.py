"""The command line: arguments, the config file, --find and --show-config. Reads the
GEDCOM, then calls the pedigree or fan library to make the PDF. The only module that uses
argparse.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import textwrap
import tomllib
import unicodedata
import warnings
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .charts import (
    birth_source,
    death_source,
    living_checker,
    nobody_living,
    plan_charts,
)
from .fan import Fan
from .fanpdf import FAN_PAPER, INKS, FanOptions, render_fan
from .fanplan import plan_fan
from .gedcom import read_gedcom
from .lang import (
    KincadeWarning,
    LangError,
    display_name,
    expand_home,
    format_date,
    load_strings,
    year_of,
)
from .model import Person, Tree, squash
from .pdf import Options, Rendered, render_blank, render_with_counts


def _fold(text: str) -> str:
    """Text as --find and --root compare it: single-spaced, casefolded and NFC, so
    that a name typed in one case or Unicode form (a composed ë) matches one stored in
    another (a decomposed ë, as macOS may write it)."""
    return unicodedata.normalize("NFC", squash(text).casefold())


def find_people(tree: Tree, text: str) -> list[Person]:
    """The people a record ID or a name matches. A record ID (I12, or @I12@ as GEDCOM
    writes it) matches exactly, else in any case and Unicode form; failing that, every
    person whose name contains the text, in any case and Unicode form."""
    key = text.strip()
    ids = (key, key.strip("@"))
    for cand in ids:
        if cand in tree.people:
            return [tree.people[cand]]
    folded = {_fold(cand) for cand in ids}
    if same := [p for pid, p in tree.people.items() if _fold(pid) in folded]:
        return same
    needle = _fold(key)
    return [p for p in tree.people.values() if needle in _fold(display_name(p))]


BLANK_OUTPUT_NAME = "Blank cascading pedigree.pdf"  # the default output of --blank


def default_output_name(root_name: str) -> str:
    """'<root name> cascading pedigree.pdf' with the name made file-system safe and at
    most 100 characters.
    """
    return f"{_output_stem(root_name) or 'pedigree'} cascading pedigree.pdf"


def default_fan_output_name(root_name: str) -> str:
    """The file-system-safe fan file name, or fan chart.pdf for an empty name."""
    stem = _output_stem(root_name)
    return f"{stem} fan chart.pdf" if stem else "fan chart.pdf"


def output_root_name(
    tree: Tree,
    root: str,
    *,
    exclude_private: bool = False,
    adoptive_parents: bool = False,
    large_print: bool = False,
    living_name: str = "Living",
) -> str:
    """The recorded-case root name for a filename, concealing a private person."""
    if exclude_private:
        parents = "adoptive" if adoptive_parents else "birth"
        charts = plan_charts(tree, root, None, parents, large_print)
        living = living_checker(tree, charts, datetime.date.today().year)
        if living(root):
            return living_name
    return display_name(tree.people[root], preserve_case=True)


def _output_stem(root_name: str) -> str:
    """A safe name, at most 100 characters and 200 UTF-8 bytes."""
    stem = re.sub(r"[\x00-\x1f\x7f]", "", root_name)
    stem = re.sub(r'[\\/:*?"<>|]', "_", stem).strip(". ")[:100].rstrip(". ")
    while len(stem.encode("utf-8")) > 200:  # most file systems limit names to 255 bytes
        stem = stem[:-1]
    return stem


class ConfigError(Exception):
    """A config file that cannot be used. `status` is the exit status: 1 when the file
    cannot be read, else 2.
    """

    def __init__(self, message: str, status: int = 2) -> None:
        super().__init__(message)
        self.status = status


# The dests that are not settings: the help option, the switches
# that choose and show the config file, and --blank and --find,
# which are modes of one run (they have no config key).
_NOT_SETTINGS = frozenset(
    {"help", "config", "no_config", "show_config", "blank", "find"}
)
# a setting of one replaces the other from an earlier layer
_EXCLUSIVE = (("footer", "no_footer"),)
_MINIMUM = {"generations": 1}
# settings that are paths: no NUL, and ~ is the home folder
_PATH_KEYS = ("gedcom", "output", "lang")


class _HelpFormatter(argparse.HelpFormatter):
    """The help, wrapped with textwrap so that an option name is never broken at its
    hyphens (argparse's own wrapping does, "--no-" then "page-numbers") and a long word
    is never cut. The help column starts at 23 on an 80-column terminal; longer
    option invocations put their help on the following line. In the description and the
    epilog each line of the source is wrapped on its own, and a blank line stays.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_help_position", 23)
        super().__init__(*args, **kwargs)

    @staticmethod
    def _wrap(
        text: str, width: int, indent: str = "", continuation: str | None = None
    ) -> list[str]:
        return textwrap.wrap(
            squash(text),
            width,
            initial_indent=indent,
            subsequent_indent=indent if continuation is None else continuation,
            break_on_hyphens=False,
            break_long_words=False,
        )

    def _format_action_invocation(self, action: argparse.Action) -> str:
        """`-o, --output FILE`: the metavar once, after the last name (argparse repeats
        it after each name).
        """
        if len(action.option_strings) < 2 or action.nargs == 0:
            return super()._format_action_invocation(action)
        metavar = self._format_args(
            action, self._get_default_metavar_for_optional(action)
        )
        return f"{', '.join(action.option_strings)} {metavar}"

    def _split_lines(self, text: str, width: int) -> list[str]:
        return self._wrap(text, width)

    def _fill_text(self, text: str, width: int, indent: str) -> str:
        lines = []
        for line in text.splitlines():
            content = line.lstrip()
            padding = indent + line[: len(line) - len(content)]
            code = re.match(r"\d+: ", content)
            # Indented examples are literal shell lines, including continuations.
            if line[:1].isspace() and not code:
                lines.append(indent + line)
                continue
            continuation = padding + (" " * len(code[0]) if code else "")
            lines.append("\n".join(self._wrap(content, width, padding, continuation)))
        return "\n".join(lines)


USAGE = (
    "kincade FILE.ged --root PERSON [options]\n"
    "       kincade FILE.ged --root PERSON --fan [options]\n"
    "       kincade FILE.ged --find TEXT [options]\n"
    "       kincade --blank [options]\n"
    "       kincade --show-config [options]"
)


def _parser(suppress_defaults: bool = False) -> argparse.ArgumentParser:
    """The command line. With suppress_defaults, an option that is not given is left out
    of the namespace, so that the command line alone shows what it sets (main merges
    that over the config file and the defaults).
    """
    ap = argparse.ArgumentParser(
        prog="kincade",
        usage=USAGE,
        formatter_class=_HelpFormatter,
        description="Make a cascading pedigree PDF from a GEDCOM file: chart 1 for the root person, a further chart "
        "wherever a line runs past the last column, and a name index at the end.\n"
        "With --fan, make a fan chart on one landscape page.",
        epilog="Example:\n"
        "  uv run kincade docs/examples/george-washington.ged \\\n"
        '    --root "George Washington"\n'
        "\nExit codes:\n"
        "  0: success (PDF, --find, --show-config or --help)\n"
        "  1: a file cannot be read or written, a GEDCOM file has no people, "
        "a language cannot be used, or no match for --root or --find\n"
        "  2: a usage error, an ambiguous --root or an invalid config file",
    )
    person = ap.add_argument_group("person")
    content = ap.add_argument_group("content")
    page = ap.add_argument_group("page")
    settings = ap.add_argument_group("config file")

    # argparse exposes its groups through the private _ActionsContainer API.
    def add(
        container: argparse._ActionsContainer, *names: str, **kw: Any
    ) -> argparse.Action:
        if suppress_defaults:
            kw["default"] = argparse.SUPPRESS
        return container.add_argument(*names, **kw)

    def toggle(container: argparse._ActionsContainer, flag: str, text: str) -> None:
        """An on/off option: the flag that changes the default (--no-index for an option
        that is on, --shadow for one that is off) and nothing else. Its dest, and its
        config file key, is the flag's name with underscores.
        """
        add(container, flag, action="store_true", help=text)

    add(person, "file", metavar="FILE.ged", nargs="?", help="GEDCOM file to read")
    add(
        person,
        "--root",
        metavar="PERSON",
        help="person at the head of chart 1: a record ID (I12) or part of a name",
    )
    add(
        person,
        "--root-family",
        metavar="FAMILY",
        help="family record ID for the root's spouse and marriage (default: first spouse family; pedigree only)",
    )
    add(
        person,
        "--find",
        metavar="TEXT",
        help="list matching people and their spouse families; (default) marks the first spouse family",
    )

    toggle(
        content,
        "--fan",
        "draw the fan chart (one page, up to 7 generations) instead of the pedigree",
    )
    add(
        content,
        "--generations",
        type=int,
        metavar="N",
        help="show N generations, counting the root as 1 (default: all; with --fan, 2 to 7, default 6)",
    )
    toggle(
        content,
        "--exclude-private",
        "hide the names and details of people who may be living",
    )
    toggle(
        content,
        "--preserve-case",
        "keep recorded surname case in charts and selection lists",
    )
    toggle(
        content,
        "--adoptive-parents",
        "where a person has adoptive or foster parents, draw those instead of birth parents; on the pedigree a note follows the name",
    )
    toggle(
        content,
        "--no-event-standins",
        "show only births and deaths; privacy still uses christenings, baptisms, burials and cremations",
    )
    toggle(
        content,
        "--no-empty",
        "leave out the boxes of unknown ancestors (pedigree only)",
    )
    toggle(
        content,
        "--show-ids",
        "show each person's record ID beside their name, on the charts and in the index (pedigree only)",
    )
    toggle(
        content,
        "--no-shorten-places",
        'cut a long place with "…" instead of first leaving out its country and middle parts (pedigree only)',
    )
    toggle(
        content,
        "--no-index",
        "leave out the name index page(s) at the end (pedigree only)",
    )

    add(
        page,
        "-o",
        "--output",
        metavar="FILE",
        help='PDF to write (default: "<root name> cascading pedigree.pdf"; with --fan: "<root name> fan chart.pdf"; with --blank: "Blank cascading pedigree.pdf")',
    )
    add(
        page,
        "--paper",
        choices=list(FAN_PAPER),
        default="letter",
        help="paper size (default: letter); tabloid and a3 are for the fan chart",
    )
    add(
        page,
        "--ink",
        choices=INKS,
        default="color",
        help="ink for the fan chart (default: color; fan chart only)",
    )
    toggle(
        page,
        "--large-print",
        "use larger print and three generations per page (pedigree only)",
    )
    toggle(page, "--shadow", "draw a drop shadow under each box (pedigree only)")
    add(
        page,
        "--lang",
        metavar="LANG",
        help="language name (such as de) or .toml path; user files: ~/.config/kincade/lang/ (default: English)",
    )
    add(
        page,
        "--title",
        metavar="TEXT",
        help="page title (default: chart title and root's name)",
    )
    footer_group = page.add_mutually_exclusive_group()
    add(
        footer_group,
        "--footer",
        metavar="TEXT",
        help="footer text (default: the language's footer)",
    )
    toggle(footer_group, "--no-footer", "leave out the footer")
    toggle(page, "--no-page-numbers", "leave out the page numbers (pedigree only)")
    add(
        page,
        "--blank",
        action="store_true",
        help="make one blank chart to fill in by hand (no GEDCOM file) (pedigree only)",
    )

    source = settings.add_mutually_exclusive_group()
    add(
        source,
        "--config",
        metavar="FILE",
        help="read config file FILE instead of ./kincade.toml or ~/.config/kincade/config.toml",
    )
    add(source, "--no-config", action="store_true", help="don't read a config file")
    add(
        settings,
        "--show-config",
        action="store_true",
        help="print the config in use and where each value came from",
    )
    return ap


def _setting_keys(ap: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    """Every config file key -> its option. A key is the option's dest, which is its
    long name without the dashes, with underscores: --no-index is no_index (set it true
    to leave the index out). The positional FILE.ged is the key gedcom.
    """
    return {
        "gedcom" if not action.option_strings else action.dest: action
        for action in ap._actions
        if action.dest not in _NOT_SETTINGS
    }


def _user_config_file() -> Path | None:
    """The per-user config file, or None where no home folder can be found."""
    try:
        return Path.home() / ".config" / "kincade" / "config.toml"
    except RuntimeError:  # Path.home() with no HOME and no account entry
        return None


def _no_nul(where: str, key: str, value: str) -> None:
    if "\x00" in value:
        raise ConfigError(f"{where}: {key} cannot contain a NUL character")


def _path_text(where: str, key: str, value: str) -> str:
    """A path setting as text: no NUL character, and a leading ~ is the home folder. A
    failure is a ConfigError that names the key.
    """
    _no_nul(where, key, value)
    try:
        return expand_home(value)
    except ValueError as e:
        raise ConfigError(f"{where}: {key} = {value!r}: {e}") from None


def _settings_file(given: Mapping[str, Any]) -> Path | None:
    """The config file in use: --config PATH; none with --no-config; else
    ./kincade.toml, then the per-user file.
    """
    if given.get("no_config"):
        return None
    if given.get("config") is not None:
        try:
            return Path(
                _path_text("command line", "config", given["config"])
            ).absolute()
        except OSError as e:
            raise ConfigError(
                f"command line: config = {given['config']!r}: cannot resolve the path ({e})"
            ) from None
    try:
        for candidate in (Path.cwd() / "kincade.toml", _user_config_file()):
            if candidate is not None and candidate.is_file():
                return candidate.absolute()
    # e.g. a home folder name too long, a folder that cannot be searched
    except (OSError, ValueError) as e:
        raise ConfigError(
            f"cannot look for a config file: {getattr(e, 'strerror', None) or e}", 1
        ) from None
    return None


def _gedcom_path(where: str, settings_file: Path, value: str) -> str:
    """A gedcom path from a config file: ~ is the home folder; a relative path is
    relative to the file's folder.
    """
    path = Path(_path_text(where, "gedcom", value))
    if path.is_absolute():
        return str(path)
    try:
        return str(settings_file.resolve().parent / path)
    except (OSError, RuntimeError) as e:  # e.g. a symlink loop
        raise ConfigError(
            f"{where}: gedcom = {value!r}: cannot resolve the path ({e})"
        ) from None


def _check_setting(where: str, key: str, action: argparse.Action, value: Any) -> None:
    if action.nargs == 0:  # a switch
        ok, want = isinstance(value, bool), "true or false"
    elif action.type is int:
        ok, want = type(value) is int, "a whole number"
    elif action.choices is not None:
        ok, want = (
            value in action.choices,
            "one of " + ", ".join(f'"{choice}"' for choice in action.choices),
        )
    else:
        ok, want = isinstance(value, str), "text in quotes"
    if not ok:
        raise ConfigError(f"{where}: {key} must be {want}, not {value!r}")
    if key in _MINIMUM and value < _MINIMUM[key]:
        raise ConfigError(f"{where}: {key} must be at least {_MINIMUM[key]}")


def _read_settings(path: Path, keys: Mapping[str, argparse.Action]) -> dict[str, Any]:
    """The settings a file gives, as {dest: value}, each value as the command line would
    store it.
    """
    where = f"config file {path}"
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise ConfigError(
            f"cannot read config file {path}: {e.strerror or e}", 1
        ) from None
    # TOML errors, bad UTF-8, and a number too long for tomllib (all ValueErrors)
    except ValueError as e:
        raise ConfigError(
            f"config file {path} is not valid TOML: {squash(str(e))}"
        ) from None
    settings: dict[str, Any] = {}
    for key, value in data.items():
        if key not in keys:
            raise ConfigError(
                f"{where}: unknown key {key!r}; the valid keys are: {', '.join(sorted(keys))}"
            )
        _check_setting(where, key, keys[key], value)
        if key == "gedcom":
            settings[keys[key].dest] = _gedcom_path(where, path, value)
        elif key in _PATH_KEYS:
            settings[keys[key].dest] = _path_text(where, key, value)
        else:
            settings[keys[key].dest] = value
    if "footer" in settings and settings.get("no_footer") is True:
        raise ConfigError(f"{where}: footer and no_footer cannot both be set")
    return settings


def _merge(
    defaults: Mapping[str, Any], layers: list[tuple[str, Mapping[str, Any]]]
) -> tuple[dict[str, Any], dict[str, str]]:
    """The settings: the defaults, with each layer laid over the one before it (later
    layers win). Returns the values and, for each, the source it came from: "default",
    the config file, or "command line".
    """
    settings, sources = dict(defaults), dict.fromkeys(defaults, "default")
    for source, layer in layers:
        for dest, value in layer.items():
            settings[dest], sources[dest] = value, source
            for pair in _EXCLUSIVE:
                if dest in pair:
                    other = pair[1] if dest == pair[0] else pair[0]
                    # set by an earlier layer: that one gives way
                    if sources[other] not in ("default", source):
                        settings[other], sources[other] = defaults[other], "default"
    return settings, sources


_PEDIGREE_ONLY = (
    "root_family",
    "no_index",
    "large_print",
    "shadow",
    "show_ids",
    "no_empty",
    "no_shorten_places",
    "no_page_numbers",
)


def _mode_settings(
    ap: argparse.ArgumentParser,
    given: Mapping[str, Any],
    settings: dict[str, Any],
    sources: dict[str, str],
) -> str:
    """Choose the run's mode, reject inapplicable flags and ignore config values.
    Ignored settings use the current mode's defaults, with default as their source.
    """
    mode = (
        "blank"
        if given.get("blank")
        else "find"
        if given.get("find") is not None
        else "fan"
        if settings["fan"]
        else "pedigree"
    )
    if given.get("fan") and given.get("blank"):
        ap.error("--fan cannot be used with --blank")
    if mode == "find":
        return mode
    ignored: list[str] = []
    if mode == "fan":
        for key in _PEDIGREE_ONLY:
            if key in given:
                ap.error(f"--{key.replace('_', '-')} is for the pedigree only")
        ignored.extend(_PEDIGREE_ONLY)
        generations = settings["generations"]
        if generations is not None and not 2 <= generations <= 7:
            if "generations" in given:
                ap.error("--generations must be from 2 to 7 with --fan")
            ignored.append("generations")
    else:
        if "ink" in given:
            ap.error("--ink is for the fan chart only")
        ignored.append("ink")
        if settings["paper"] in ("tabloid", "a3"):
            if "paper" in given:
                ap.error("--paper tabloid and --paper a3 are for the fan chart only")
            ignored.append("paper")
    defaults = vars(ap.parse_args([]))
    for key in ignored:
        settings[key], sources[key] = defaults[key], "default"
    if mode == "fan" and settings["generations"] is None:
        settings["generations"], sources["generations"] = 6, "default"
    return mode


_TOML_SHORT = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _toml_string(text: str) -> str:
    """A TOML basic string for text. Quotes, backslashes and control characters are
    escaped (\\uXXXX where there is no short escape), so the result always parses. A
    lone surrogate, which no TOML text can hold, is written as U+FFFD.
    """
    out = []
    for ch in text:
        category = unicodedata.category(ch)
        if ch in _TOML_SHORT:
            out.append(_TOML_SHORT[ch])
        elif category == "Cc":
            out.append(f"\\u{ord(ch):04x}")
        elif category == "Cs":
            out.append("\ufffd")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return _toml_string(str(value))


def _comment(text: str) -> str:
    """Text for a TOML comment. Control characters other than tab, and lone surrogates,
    are written as escapes, so a line break in a file name cannot end the comment early.
    """
    return "".join(
        ch.encode("unicode_escape").decode("ascii")
        if ch != "\t" and unicodedata.category(ch) in ("Cc", "Cs")
        else ch
        for ch in text
    )


def _show_config(
    settings: Mapping[str, Any], sources: Mapping[str, str], path: Path | None
) -> str:
    lines = [
        "# kincade config in use; the comment after each value says where it came from.",
        f"# config file: {_comment(str(path))}" if path else "# no config file is read",
    ]
    for dest, value in settings.items():
        key = "gedcom" if dest == "file" else dest
        source = _comment(sources[dest])
        if value is None:
            lines.append(f"# {key} is not set  # {source}")
        else:
            lines.append(f"{key} = {_toml_value(value)}  # {source}")
    return "\n".join(lines) + "\n"


def _check_command_line_paths(
    settings: dict[str, Any], sources: Mapping[str, str]
) -> None:
    """The path settings given on the command line: no NUL character. A --lang value may
    start with ~ (as one in a config file may), so it is expanded here too; the file and
    output names are used as the shell gave them.
    """
    for dest in ("file", "output", "lang"):
        value = settings.get(dest)
        if isinstance(value, str) and sources[dest] == "command line":
            if dest == "lang":
                settings[dest] = _path_text("command line", dest, value)
            else:
                _no_nul("command line", dest, value)


def _fail(message: object, status: int = 1) -> int:
    """Print `kincade: message` on stderr; the exit status comes back."""
    print(f"kincade: {message}", file=sys.stderr)
    return status


def _count(n: int, noun: str) -> str:
    """'1 page', '2 pages', '0 pages'."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def pedigree_summary(rendered: Rendered) -> str:
    """The chart, index and total page counts for a rendered pedigree."""
    return (
        f"{_count(rendered.chart_pages, 'chart')}, {_count(rendered.index_pages, 'index page')}, "
        f"{_count(rendered.pages, 'page')}"
    )


def fan_summary(fan: Fan) -> str:
    """The generations and distinct people in a fan chart."""
    people = round(sum(1 / cell.copies for cell in fan.cells if not cell.empty))
    return (
        f"fan chart, {_count(fan.generations, 'generation')}, "
        f"{people} {'person' if people == 1 else 'people'}"
    )


def _write_pdf(out: Path, pdf: bytes, summary: str) -> int:
    """Write the PDF, making its folder if need be, and say so on stderr. 0 when it is
    written, else 1.
    """
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(pdf)
    except OSError as e:
        return _fail(f"cannot write {out}: {e.strerror or 'I/O error'}")
    print(f"wrote {out} ({summary})", file=sys.stderr)
    return 0


def _options(
    args: argparse.Namespace, strings: Mapping[str, Any], **more: Any
) -> Options:
    """The Options for a run: the page settings and the language (already loaded, so a
    bad one failed early), then `more`.
    """
    return Options(
        title=args.title,
        footer=False if args.no_footer else args.footer,
        shadow=args.shadow,
        large_print=args.large_print,
        preserve_case=args.preserve_case,
        paper=args.paper,
        lang=strings,
        **more,
    )


def _settings(
    ap: argparse.ArgumentParser, given: Mapping[str, Any]
) -> tuple[Path | None, dict[str, Any], dict[str, str]]:
    """The settings of a run: the defaults, then the config file in use, then the
    command line (`given`). Returns the config file's path (None if none is read), the
    values and the source of each. A bad file is a ConfigError.
    """
    keys = _setting_keys(ap)
    defaults = {
        dest: value
        for dest, value in vars(ap.parse_args([])).items()
        if dest not in _NOT_SETTINGS
    }
    from_cli = {
        dest: value for dest, value in given.items() if dest not in _NOT_SETTINGS
    }
    path = _settings_file(given)
    from_file = _read_settings(path, keys) if path else {}
    settings, sources = _merge(
        defaults, [(f"config file {path}", from_file), ("command line", from_cli)]
    )
    _check_command_line_paths(settings, sources)
    return path, settings, sources


def person_line(
    p: Person,
    living: Callable[[str | None], bool],
    standins: bool,
    *,
    living_name: str | None = "Living",
    preserve_case: bool = False,
) -> str:
    """Record ID, name and years of a person, tab-separated. Living people's names
    use the localized placeholder and their years are omitted. IDs remain for root
    selection. living_name=None keeps names visible in the browser's local picker. With
    `standins`, a christening, burial or cremation gives a missing birth or death year,
    as in the boxes (birth_source, death_source)."""
    born, died = (
        year_of(birth_source(p, standins)[0].date),
        year_of(death_source(p, standins)[0].date),
    )
    hide = living(p.id)
    years = f"{born or '?'}-{died or ''}" if (born or died) and not hide else ""
    name = (
        living_name
        if hide and living_name is not None
        else display_name(p, preserve_case)
    )
    return f"{p.id}\t{name}\t{years}"


def _family_lines(
    tree: Tree,
    p: Person,
    living: Callable[[str | None], bool],
    strings: Mapping[str, Any],
    preserve_case: bool,
) -> list[str]:
    """Indented spouse-family rows for --find, in FAMS then file order. Only actual
    partners are listed; a missing first FAMS never promotes a later default.
    """
    default = p.families[0] if p.families else None
    family_ids = dict.fromkeys(p.families + list(tree.families))
    rows = []
    for family_id in family_ids:
        family = tree.families.get(family_id)
        if family is None or p.id not in (family.father, family.mother):
            continue
        spouse_id = family.mother if family.father == p.id else family.father
        spouse = tree.people.get(spouse_id)
        name = (
            strings["living_name"]
            if living(spouse_id)
            else display_name(spouse, preserve_case)
            if spouse
            else ""
        )
        parts = [family_id, name or "Unknown spouse"]
        if family.marriage and not (living(p.id) or living(spouse_id)):
            for key, value in (
                ("marriage", format_date(family.marriage.date, strings)),
                ("marriage_place", family.marriage.place),
            ):
                if value := squash(value):
                    parts.append(squash(f"{strings['labels'][key]} {value}"))
        if family_id == default:
            parts.append("(default)")
        rows.append("    " + "\t".join(parts))
    return rows


def _make_blank(args: argparse.Namespace) -> int:
    """--blank: one blank chart from the page options alone. No GEDCOM file is read, so
    a file, a root and the options that need a tree (generations, content) have nothing
    to apply to and are ignored.
    """
    try:
        strings = load_strings(args.lang)
    except LangError as e:
        return _fail(e)
    pdf = render_blank(_options(args, strings))
    return _write_pdf(
        Path(args.output or BLANK_OUTPUT_NAME), pdf, "1 blank chart, 1 page"
    )


_CANDIDATES_SHOWN = 50  # the most people an ambiguous --root lists


def _make_pedigree(args: argparse.Namespace, find: str | None) -> int:
    """List the people `find` (--find) matches, or make the --root person's PDF."""
    try:
        # a bad language fails here, before the GEDCOM is read
        strings = load_strings(args.lang)
    except LangError as e:
        return _fail(e)
    try:
        tree = read_gedcom(args.file)
    # unreadable or malformed input: one clean line, traceback only on request
    except Exception as e:
        if os.environ.get("KINCADE_DEBUG"):
            raise
        reason = (e.strerror or "I/O error") if isinstance(e, OSError) else str(e)
        return _fail(f"cannot read {args.file}: {reason}")
    if not tree.people:
        return _fail(f"no people found in {args.file}")
    # Candidate lists retain record IDs for selection while redacting living people.
    standins = not args.no_event_standins
    living = (
        living_checker(tree, [], datetime.date.today().year)
        if args.exclude_private
        else nobody_living
    )

    # --find searches the entire tree; it does not choose a pedigree root.
    if find is not None:
        found = find_people(tree, find)
        if not found:
            return _fail(f"no person matches {find!r}")
        for p in found:
            print(
                person_line(
                    p,
                    living,
                    standins,
                    living_name=strings["living_name"],
                    preserve_case=args.preserve_case,
                )
            )
            for line in _family_lines(tree, p, living, strings, args.preserve_case):
                print(line)
        return 0

    matches = find_people(tree, args.root)
    exact = [p for p in matches if _fold(display_name(p)) == _fold(args.root)]
    if len(exact) == 1:
        matches = exact
    if not matches:
        return _fail(f"no person matches {args.root!r}")
    if len(matches) > 1:
        _fail(f"{len(matches)} people match {args.root!r}; use a record ID:")
        for p in matches[:_CANDIDATES_SHOWN]:
            line = person_line(
                p,
                living,
                standins,
                living_name=strings["living_name"],
                preserve_case=args.preserve_case,
            )
            print(f"  {line}", file=sys.stderr)
        if len(matches) > _CANDIDATES_SHOWN:
            print(f"  … and {len(matches) - _CANDIDATES_SHOWN} more", file=sys.stderr)
        return 2
    root = matches[0]
    if args.mode == "fan":
        return _make_fan(args, tree, root, strings)

    opts = _options(
        args,
        strings,
        generations=args.generations,
        root_family=args.root_family,
        page_numbers=not args.no_page_numbers,
        shorten_places=not args.no_shorten_places,
        show_ids=args.show_ids,
        empty_boxes=not args.no_empty,
        adoptive_parents=args.adoptive_parents,
        index=not args.no_index,
        exclude_private=args.exclude_private,
        event_standins=standins,
    )
    try:
        rendered = render_with_counts(tree, root.id, opts)
    except ValueError as e:
        return _fail(e, 2)
    out = Path(
        args.output
        or default_output_name(
            output_root_name(
                tree,
                root.id,
                exclude_private=args.exclude_private,
                adoptive_parents=args.adoptive_parents,
                large_print=args.large_print,
                living_name=strings["living_name"],
            )
        )
    )
    summary = pedigree_summary(rendered)
    return _write_pdf(out, rendered.pdf, summary)


def _make_fan(
    args: argparse.Namespace, tree: Tree, root: Person, strings: Mapping[str, Any]
) -> int:
    """Plan and draw a fan using the resolved tree, root and language."""
    fan = plan_fan(
        tree,
        root.id,
        generations=args.generations or 6,
        exclude_private=args.exclude_private,
        adoptive_parents=args.adoptive_parents,
        event_standins=not args.no_event_standins,
        preserve_case=args.preserve_case,
        ink=args.ink,
        lang=strings,
    )
    pdf = render_fan(
        fan,
        FanOptions(
            ink=args.ink,
            paper=args.paper,
            lang=strings,
            title=args.title,
            footer=False if args.no_footer else args.footer,
        ),
    )
    summary = fan_summary(fan)
    return _write_pdf(
        Path(
            args.output
            or default_fan_output_name(
                output_root_name(
                    tree,
                    root.id,
                    exclude_private=args.exclude_private,
                    adoptive_parents=args.adoptive_parents,
                    living_name=strings["living_name"],
                )
            )
        ),
        pdf,
        summary,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the command, showing library notices as plain Kincade warning lines."""
    with warnings.catch_warnings():
        original_showwarning = warnings.showwarning

        def show_warning(
            message: Warning | str,
            category: type[Warning],
            filename: str,
            lineno: int,
            file: Any = None,
            line: str | None = None,
        ) -> None:
            if issubclass(category, KincadeWarning):
                print(f"kincade: warning: {message}", file=sys.stderr)
            else:
                original_showwarning(message, category, filename, lineno, file, line)

        warnings.simplefilter("always", KincadeWarning)
        warnings.showwarning = show_warning
        return _main(argv)


def _main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    # a character the terminal cannot show becomes '?', never a traceback
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    # usage errors exit 2 here
    given = vars(_parser(suppress_defaults=True).parse_args(argv))
    ap = _parser()
    find = given.get("find")
    if given.get("blank") and find is not None:
        ap.error("--blank cannot be used with --find")
    try:
        path, settings, sources = _settings(ap, given)
    except ConfigError as e:
        return _fail(e, e.status)
    mode = _mode_settings(ap, given, settings, sources)
    if given.get("show_config"):
        print(_show_config(settings, sources, path), end="")
        return 0
    args = argparse.Namespace(**settings, mode=mode)
    if mode == "blank":
        return _make_blank(args)
    if args.file is None:
        ap.error(
            "FILE.ged is required (or set gedcom in a config file; see --show-config)"
        )
    if find is None and not args.root:
        ap.error("--root is required (or use --find TEXT)")
    if args.generations is not None and args.generations < 1:
        ap.error("--generations must be at least 1")
    return _make_pedigree(args, find)


if __name__ == "__main__":
    sys.exit(main())

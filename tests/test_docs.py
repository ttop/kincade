"""The library guide and package Python examples and README commands run; the example
config file is valid and names every key."""

import re
import shlex
import tomllib

import pytest

import kincade
import kincade.cli

from conftest import FIX, ROOT, config_keys
from pdfread import count_pages

README = ROOT / "README.md"
LIBRARY = ROOT / "docs" / "library.md"
EXAMPLE = ROOT / "kincade.example.toml"


def python_blocks(path):
    return re.findall(
        r"```python\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL
    )


def test_the_library_guide_contains_python_examples():
    assert python_blocks(LIBRARY), "The library guide must contain executable examples"


def test_the_library_example_of_the_package_docstring_runs():
    block = re.search(
        r"    from kincade import .*?\n\n(.*?)\n\nThe model", kincade.__doc__, re.DOTALL
    )[0]
    code = "\n".join(line[4:] for line in block.splitlines() if line.startswith("    "))
    code = code.replace('"family.ged"', repr(str(FIX / "pedigree.ged"))).replace(
        '"I12"', '"I1"'
    )
    namespace = {}
    exec(code, namespace)  # noqa: S102
    assert namespace["pdf"].startswith(b"%PDF") and namespace["blank"].startswith(
        b"%PDF"
    )


@pytest.mark.parametrize(
    "block",
    [
        pytest.param(block, id=f"block{n}")
        for n, block in enumerate(python_blocks(LIBRARY), 1)
    ],
)
def test_each_python_example_of_the_library_guide_runs(block, tmp_path):
    code = block.replace(
        '"docs/examples/george-washington.ged"',
        repr(str(ROOT / "docs/examples/george-washington.ged")),
    )
    namespace = {}
    exec(code, namespace)  # noqa: S102
    made = [v for v in namespace.values() if isinstance(v, bytes)]
    made += [path.read_bytes() for path in tmp_path.rglob("*.pdf")]
    assert made and all(
        pdf.startswith(b"%PDF") and count_pages(pdf) > 0 for pdf in made
    )


def example_commands(path):
    """The `uv run kincade` lines of the shell examples that read the example, as
    argument lists without `uv run kincade`."""
    blocks = re.findall(
        r"```(?:sh|console)\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL
    )
    return [
        shlex.split(line, comments=True)[3:]
        for block in blocks
        for raw in block.splitlines()
        if (line := raw.removeprefix("$ ")).startswith("uv run kincade docs/examples/")
    ]


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(args, id=f"command{n}")
        for n, args in enumerate(example_commands(README), 1)
    ],
)
def test_each_quick_start_command_of_the_readme_runs(args, capsys):
    args = [
        str(ROOT / arg) if arg.startswith("docs/examples/") else arg for arg in args
    ]
    assert kincade.cli.main(args) == 0, capsys.readouterr().err


# ---------------------------------------------------------------- the example file


def test_the_example_file_is_a_valid_config_file(capsys):
    data = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert set(data) <= set(config_keys())
    assert kincade.cli.main(["--config", str(EXAMPLE), "--show-config"]) == 0
    assert "unknown key" not in capsys.readouterr().err


def test_the_example_file_documents_every_key():
    text = EXAMPLE.read_text(encoding="utf-8")
    for key in sorted(config_keys()):
        assert re.search(rf"^#?\s*{re.escape(key)}\s*=", text, re.MULTILINE), (
            f"{key} is not in kincade.example.toml"
        )

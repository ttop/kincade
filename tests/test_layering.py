"""The package's layers (docs/design.md, "Module layering"): which module may import
which, and the packaging facts the command `kincade` and `uv run pytest` rely on.

    model   imports nothing of ours (and only the standard library)
    fan     imports nothing of ours
    gedcom, charts, lang   import model; never reportlab
    fanplan imports model, charts, lang, fan; never reportlab
    pdf     imports model, charts, lang, reportlab
    fanpdf  imports lang, fan, pdf, reportlab
    cli     imports everything; the only module that uses argparse
    the library (every module but cli) never imports argparse or cli
"""

import ast
import sys
import tomllib

import pytest

from conftest import ROOT

PKG = ROOT / "kincade"

OURS = {"model", "charts", "lang", "pdf", "gedcom", "cli", "fan", "fanplan", "fanpdf"}
MAY_IMPORT = {
    "model": set(),
    "fan": set(),
    "fanplan": {"model", "charts", "lang", "fan"},
    "fanpdf": {"lang", "fan", "pdf"},
    "gedcom": {"model"},
    "charts": {"model"},
    "lang": {"model"},
    "pdf": {"model", "charts", "lang"},
    "cli": {"model", "charts", "lang", "pdf", "gedcom", "fan", "fanplan", "fanpdf"},
    "__init__": {"model", "gedcom", "lang", "pdf", "fan", "fanplan", "fanpdf"},
}


def imports(module):
    """(our modules, other top-level packages) that kincade/<module>.py imports, at any
    depth.
    """
    ours, other = set(), set()
    for node in ast.walk(ast.parse((PKG / f"{module}.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            other.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # from .model import X, or from . import model
                ours.update(
                    [node.module.split(".")[0]]
                    if node.module
                    else [a.name for a in node.names]
                )
            elif node.module and node.module.split(".")[0] == "kincade":
                ours.update(
                    [node.module.split(".")[1]]
                    if "." in node.module
                    else [a.name for a in node.names]
                )
            elif node.module:
                other.add(node.module.split(".")[0])
    return ours, other


@pytest.mark.parametrize("module", sorted(MAY_IMPORT))
def test_each_module_imports_only_the_layers_below_it(module):
    ours, _ = imports(module)
    assert ours <= MAY_IMPORT[module], (
        f"{module} imports {sorted(ours - MAY_IMPORT[module])}"
    )


def test_the_model_is_standard_library_only():
    _, other = imports("model")
    assert other <= set(sys.stdlib_module_names), sorted(
        other - set(sys.stdlib_module_names)
    )


@pytest.mark.parametrize("module", ["gedcom", "charts", "lang", "fan", "fanplan"])
def test_reading_planning_and_language_never_touch_reportlab(module):
    _, other = imports(module)
    assert "reportlab" not in other


def test_the_library_never_imports_argparse_or_the_cli():
    for module in sorted(OURS - {"cli"}):
        ours, other = imports(module)
        assert "argparse" not in other and "cli" not in ours, module
    init_ours, init_other = imports("__init__")
    assert "cli" not in init_ours and "argparse" not in init_other


def test_every_module_of_the_table_exists_and_nothing_else_is_missing():
    assert {p.stem for p in PKG.glob("*.py")} == OURS | {"__init__"}


def test_the_package_folder_holds_the_language_files():
    assert sorted(p.name for p in (PKG / "lang").glob("*.toml")) == [
        "de.toml",
        "en.toml",
    ]


def test_pyproject_declares_the_package_the_command_and_the_dev_tools():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["name"] == "kincade"
    assert project["project"]["requires-python"] == ">=3.11"
    assert any(
        d.replace(" ", "").startswith("reportlab>=4")
        for d in project["project"]["dependencies"]
    )
    assert project["project"]["scripts"] == {"kincade": "kincade.cli:main"}
    assert any(d.startswith("pytest") for d in project["dependency-groups"]["dev"])

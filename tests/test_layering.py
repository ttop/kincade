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
NEVER_REPORTLAB = {"gedcom", "charts", "lang", "fan", "fanplan"}


def imports(module):
    """(our modules, other top-level packages) that kincade/<module>.py imports, at any
    depth.
    """
    ours, other = set(), set()
    for node in ast.walk(ast.parse((PKG / f"{module}.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top, _, rest = alias.name.partition(".")
                # import kincade.pdf names the module pdf, just as from kincade
                # import pdf does; any other package is named by its own top level.
                if top == "kincade" and rest:
                    ours.add(rest.split(".")[0])
                else:
                    other.add(top)
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


def test_each_module_imports_only_the_layers_below_it():
    """Every module's imports stay within the MAY_IMPORT table, the model is standard
    library only, the reading/planning/language modules never touch reportlab, the
    library never imports argparse or cli, and the module set matches the table.
    """
    assert {p.stem for p in PKG.glob("*.py")} == OURS | {"__init__"}
    for module in sorted(MAY_IMPORT):
        ours, other = imports(module)
        assert ours <= MAY_IMPORT[module], (
            f"{module} imports {sorted(ours - MAY_IMPORT[module])}"
        )
        if module == "model":
            assert other <= set(sys.stdlib_module_names), (
                f"model imports {sorted(other - set(sys.stdlib_module_names))}"
            )
        if module in NEVER_REPORTLAB:
            assert "reportlab" not in other, module
        if module != "cli" and module != "__init__":
            assert "argparse" not in other and "cli" not in ours, module
    init_ours, init_other = imports("__init__")
    assert "cli" not in init_ours and "argparse" not in init_other


def test_the_packaging():
    """pyproject declares the package name, python floor, reportlab floor and the
    kincade script; the bundled language files sit in the package, under LANG_DIR.
    """
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["name"] == "kincade"
    assert project["project"]["requires-python"] == ">=3.11"
    assert any(
        d.replace(" ", "").startswith("reportlab>=4")
        for d in project["project"]["dependencies"]
    )
    assert project["project"]["scripts"] == {"kincade": "kincade.cli:main"}

    from kincade.lang import LANG_DIR

    assert LANG_DIR.parent == PKG
    assert sorted(p.name for p in LANG_DIR.glob("*.toml")) == [
        "de.toml",
        "en.toml",
        "es.toml",
        "fr.toml",
        "it.toml",
    ]

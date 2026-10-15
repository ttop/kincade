"""Kincade: turn a family tree into a cascading pedigree or fan PDF.

    kincade FILE.ged --root "Jane Doe" -o out.pdf
    kincade FILE.ged --root "Jane Doe" --fan -o fan.pdf
    kincade FILE.ged --find doe
    kincade --blank -o blank.pdf

As a library (see README.md): build a Tree from your own data, or read one
from GEDCOM, and make the PDF in one call:

    from kincade import Options, read_gedcom, render, render_blank

    tree = read_gedcom("family.ged")  # read a file path or the file's bytes
    pdf = render(tree, "I12", Options(generations=7, exclude_private=True))
    blank = render_blank(Options(large_print=True))  # no tree needed

The model (Tree, Person, Family, Event, Date, Day, ParentLink) is plain dataclasses
and knows nothing of GEDCOM. LangError reports a bad language; __version__ is the
installed package version. Rendering returns PDF bytes and may read font and
language files. load_fontset finds and registers the embeddable fonts once, silently,
for Options(fonts=...) or FanOptions(fonts=...).

Fan, FanCell and LegendEntry hold a supplied fan. plan_fan seats ancestors from a
Tree; render_fan draws the fan as PDF bytes with FanOptions:

    from kincade import FanOptions, plan_fan, render_fan

    fan = plan_fan(tree, "I12", generations=6, ink="grayscale")
    fan_pdf = render_fan(fan, FanOptions(ink="grayscale", paper="a3"))

Chart planning (kincade.charts), the language files (kincade.lang) and the drawing
(kincade.pdf and kincade.fanpdf) can be used on their own, but only the names above
are promised.
"""

from importlib.metadata import PackageNotFoundError, version

from .fan import Fan, FanCell, LegendEntry
from .fanpdf import FanOptions, render_fan
from .fanplan import plan_fan
from .gedcom import read_gedcom
from .lang import LangError
from .model import Date, Day, Event, Family, ParentLink, Person, Tree
from .pdf import Options, load_fontset, render, render_blank

try:
    __version__ = version("kincade")
# a source tree that is not installed has no package metadata
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = [
    "Date",
    "Day",
    "Event",
    "Family",
    "Fan",
    "FanCell",
    "FanOptions",
    "LangError",
    "LegendEntry",
    "Options",
    "ParentLink",
    "Person",
    "Tree",
    "__version__",
    "load_fontset",
    "plan_fan",
    "read_gedcom",
    "render",
    "render_blank",
    "render_fan",
]

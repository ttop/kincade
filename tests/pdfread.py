"""Reading what a PDF draws, for the tests. The PDFs come uncompressed and in the
base-14 fonts (conftest.render makes them so), so each page's content stream is plain
text: the font, size, horizontal scale, position and string of every run of text, and
one path for every box and line."""

import re
from typing import NamedTuple

from reportlab.pdfbase import pdfmetrics

import kincade.pdf

NUMBER = rb"(-?[\d.]+)"
# What a content stream says about text, in order: a font and size, a horizontal scale,
# and a run of text at a position. One text object can hold several runs (kerned text is
# drawn in pieces), each in the font and scale last set.
TEXT = re.compile(
    rb"/(?P<font>F\d+) (?P<size>[\d.]+) Tf"
    rb"|(?P<scale>-?[\d.]+) Tz"
    rb"|1 0 0 1 (?P<x>-?[\d.]+) (?P<y>-?[\d.]+) Tm \((?P<text>.*?)\) Tj",
    re.DOTALL,
)
# An overlap this thin is rounding in the PDF's coordinates, not a collision.
TOUCH = 0.02


class Run(NamedTuple):
    font: str  # the font's name, such as "Times-Roman"
    size: float
    x: float
    y: float  # the baseline, measured down from the page top
    scale: float  # the horizontal scale: 1, or less where the text is squeezed
    text: str

    def right(self):
        """Where the run ends: its x plus its scaled width."""
        return (
            self.x
            + kincade.pdf.text_width(self.text, self.font, self.size) * self.scale
        )


class MatrixRun(NamedTuple):
    """One Tj run's page matrix, with font size and horizontal scale kept separate."""

    matrix: tuple[float, float, float, float, float, float]
    size: float
    scale: float
    text: str


def _concat_matrices(left, right):
    """Apply right's local coordinates through left's affine transform."""
    a, b, c, d, e, f = left
    a2, b2, c2, d2, e2, f2 = right
    return (
        a * a2 + c * b2,
        b * a2 + d * b2,
        a * c2 + c * d2,
        b * c2 + d * d2,
        a * e2 + c * f2 + e,
        b * e2 + d * f2 + f,
    )


def _text(raw):
    """A PDF string's text: its escapes undone (\\ddd octal, \\( and \\) and \\\\) and
    the bytes decoded as cp1252, the base-14 fonts' encoding (the ellipsis is \\205)."""
    unescaped = re.sub(
        rb"\\(\d{3}|.)",
        lambda m: bytes([int(m[1], 8)]) if len(m[1]) == 3 else m[1],
        raw,
        flags=re.DOTALL,
    )
    return unescaped.decode("cp1252", "replace")


def streams(pdf):
    """The content stream of each page, in page order."""
    return re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.DOTALL)


def count_pages(pdf):
    """The number of page objects, in compressed or uncompressed PDFs."""
    return len(re.findall(rb"/Type\s*/Page\b", pdf))


def first_page(pdf):
    """The first page's content stream."""
    return streams(pdf)[0]


def text_matrix_objects(pdf, page=0):
    """Each nonempty BT … ET object's Tj runs with matrices in page coordinates.

    Read the uncompressed base-14 subset these tests draw: each Tj follows a Tm;
    Tf and Tz give its size and scale. Compose Tm with the cm transforms from
    canvas translate/rotate, following nested q/Q graphics states. Coordinates
    start at the page's bottom left; (a, b) is the baseline and (c, d) points up.
    """
    six = rb"(?:-?[\d.]+\s+){5}-?[\d.]+"
    token = re.compile(
        rb"\((?P<text>(?:\\.|[^\\)])*)\)\s*Tj"
        rb"|(?P<tm>" + six + rb")\s+Tm\b"
        rb"|(?P<cm>" + six + rb")\s+cm\b"
        rb"|/F\d+\s+(?P<size>[\d.]+)\s+Tf\b"
        rb"|(?P<scale>-?[\d.]+)\s+Tz\b"
        rb"|(?<!\S)(?P<op>q|Q|BT|ET)(?!\S)",
        re.DOTALL,
    )
    identity = (1, 0, 0, 1, 0, 0)
    ctm, tm, size, scale = identity, identity, 0.0, 1.0
    stack, joined, out = [], [], []
    for match in token.finditer(streams(pdf)[page]):
        if match["text"] is not None:
            joined.append(
                MatrixRun(_concat_matrices(ctm, tm), size, scale, _text(match["text"]))
            )
        elif match["tm"]:
            tm = tuple(map(float, match["tm"].split()))
        elif match["cm"]:
            ctm = _concat_matrices(ctm, tuple(map(float, match["cm"].split())))
        elif match["size"]:
            size = float(match["size"])
        elif match["scale"]:
            scale = float(match["scale"]) / 100
        elif match["op"] == b"q":
            stack.append((ctm, size, scale))
        elif match["op"] == b"Q":
            ctm, size, scale = stack.pop()
        elif match["op"] == b"BT":
            tm, joined = identity, []
        elif match["op"] == b"ET" and joined:
            out.append(joined)
    return out


def page_height(pdf):
    return float(re.search(rb"/MediaBox \[ 0 0 [\d.]+ ([\d.]+) \]", pdf)[1])


def pages(pdf):
    """The text runs of each page, in drawing order: one list of Run per page."""
    fonts = {
        name.decode(): base.decode()
        for base, name in re.findall(
            rb"/BaseFont /([\w-]+) /Encoding /WinAnsiEncoding /Name /(F\d+)", pdf
        )
    }
    height = page_height(pdf)
    out = []
    for stream in streams(pdf):
        page, font, size, scale = [], "", 0.0, 1.0
        for m in TEXT.finditer(stream):
            if m["font"]:
                font, size = (
                    fonts.get(m["font"].decode(), m["font"].decode()),
                    float(m["size"]),
                )
            elif m["scale"]:
                scale = float(m["scale"]) / 100
            else:
                x, y = float(m["x"]), height - float(m["y"])
                page.append(Run(font, size, x, y, scale, _text(m["text"])))
        out.append(page)
    return out


def runs(pdf):
    """Every text run of the PDF, page after page, in drawing order."""
    return [run for page in pages(pdf) for run in page]


def drawn(pdf):
    """The strings the PDF draws, in order."""
    return [run.text for run in runs(pdf)]


def rectangles(pdf, paint="", page=0):
    """[(x, top, width, height)] of the rectangles on page `page` (the first by default;
    None for every page), top measured down from the page top. `paint` keeps those
    painted with that operator: "B*" for the box outlines, "f*" for the shadow layers;
    "" keeps all."""
    height = page_height(pdf)
    pattern = rb"n " + b" ".join([NUMBER] * 4) + b" re " + re.escape(paint.encode())
    chosen = streams(pdf) if page is None else [streams(pdf)[page]]
    return [
        (float(x), height - float(y) - float(h), float(w), float(h))
        for stream in chosen
        for x, y, w, h in re.findall(pattern, stream)
    ]


def lines(pdf):
    """[(x1, y1, x2, y2)] of the straight lines on the first page (the header rule
    included), y measured down from the page top."""
    height = page_height(pdf)
    return [
        (float(a), height - float(b), float(c), height - float(d))
        for a, b, c, d in re.findall(
            rb"n " + NUMBER + b" " + NUMBER + b" m " + NUMBER + b" " + NUMBER + b" l S",
            first_page(pdf),
        )
    ]


def ink_box(run):
    """The rectangle (x, top, width, height) a text run covers: its advance width, from
    its ascent to its descent."""
    asc = pdfmetrics.getAscent(run.font, run.size)
    desc = -pdfmetrics.getDescent(run.font, run.size)
    return (run.x, run.y - asc, run.right() - run.x, asc + desc)


def overlaps(a, b):
    """Whether two (x, top, width, height) rectangles overlap by more than TOUCH."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return (
        min(ax + aw, bx + bw) - max(ax, bx) > TOUCH
        and min(ay + ah, by + bh) - max(ay, by) > TOUCH
    )

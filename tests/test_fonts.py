"""Fonts: finding, embedding and kerning TrueType faces, and the base-14 fallback."""

import errno
import struct
from pathlib import Path

import pytest

import kincade.pdf
from kincade.pdf import load_fontset

from conftest import render
from pdfread import count_pages, drawn


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def _fake_load(loaded):
    """A TrueType loader: .ttc files in a 'ttc-broken' directory fail, everything else
    loads, each load recorded in `loaded`.
    """

    def load(path, psname):
        if path.suffix == ".ttc" and "ttc-broken" in str(path.parent):
            raise ValueError("cannot read")
        loaded.append((path.name, psname))
        return kincade.pdf._Face(
            f"F-{len(loaded)}-{path.stem}", lambda ch: ord(ch) < 0x250
        )

    return load


@pytest.fixture
def fake_loader(monkeypatch):
    """Replace the TrueType loader for the whole test with _fake_load."""
    loaded = []
    monkeypatch.setattr(kincade.pdf, "_load_ttf", _fake_load(loaded))
    return loaded


def sfnt_face(fs_type, base=0):
    """A minimal sfnt face whose table offsets start at byte `base` of its file; its
    OS/2 table holds fs_type.
    """
    os2 = struct.pack(">HhHHH", 4, 0, 400, 5, fs_type)
    offset = base + 12 + 16  # the offset table, then one table record
    return (
        b"\x00\x01\x00\x00"
        + struct.pack(">HHHH", 1, 16, 0, 0)
        + struct.pack(">4sIII", b"OS/2", 0, offset, len(os2))
        + os2
    )


def ms_subtable(pairs, coverage=1, declared_pairs=None, length=None):
    body = b"".join(struct.pack(">HHh", a, b, v) for (a, b), v in sorted(pairs.items()))
    n = len(pairs) if declared_pairs is None else declared_pairs
    sub = struct.pack(">HHH", 0, 0, coverage) + struct.pack(">HHHH", n, 0, 0, 0) + body
    return (
        struct.pack(">HHH", 0, length if length is not None else len(sub), coverage)
        + sub[6:]
    )


def ms_table(*subtables, version=0):
    return struct.pack(">HH", version, len(subtables)) + b"".join(subtables)


@pytest.mark.system_fonts
def test_system_fonts_are_found_and_embedded(pedigree, monkeypatch, tmp_path):
    """fonts="auto" finds Helvetica, Times New Roman and nested Liberation faces,
    registers each face once, embeds four subsets in a real render and narrows a
    kerned pair's width; the whole test skips when the machine has no system
    TrueType fonts.
    """
    loaded = []
    with monkeypatch.context() as mp:
        mp.setattr(kincade.pdf, "_load_ttf", _fake_load(loaded))

        # Helvetica and Times New Roman are preferred over Arial when both are
        # present.
        mac_root = tmp_path / "mac-like"
        for name in (
            "Helvetica.ttc",
            "Arial.ttf",
            "Arial Bold.ttf",
            "Times New Roman.ttf",
            "Times New Roman Italic.ttf",
        ):
            touch(mac_root / name)
        fonts, missing = load_fontset([mac_root])
        assert missing == [] and fonts is not None
        assert [Path(f).name for f in fonts.files] == [
            "Helvetica.ttc",
            "Helvetica.ttc",
            "Times New Roman.ttf",
            "Times New Roman Italic.ttf",
        ]
        assert loaded[:2] == [
            ("Helvetica.ttc", "Helvetica"),
            ("Helvetica.ttc", "Helvetica-Bold"),
        ]

        # Liberation fonts are found in nested folders, case-insensitively.
        names = [
            "LiberationSans-Regular.ttf",
            "LIBERATIONSANS-BOLD.TTF",
            "LiberationSerif-Regular.ttf",
            "LiberationSerif-Italic.ttf",
        ]
        liberation_root = tmp_path / "liberation-root"
        for i, name in enumerate(names):
            touch(liberation_root / "truetype" / f"liberation{i}" / name)
        fonts, missing = load_fontset([liberation_root])
        assert missing == [] and [Path(f).name for f in fonts.files] == names

    # Each face is registered once; registration, coverage and kerning share one
    # object.
    made, registered = [], []

    class FakeFace:
        unitsPerEm = 1000

        def __init__(self):
            self.charToGlyph = {65: 1, 86: 2, 105: 3}
            # (advance, lsb) per glyph, as a real face has them
            self.hmetrics = [(1000, 0)] * 4

        def get_table(self, tag):
            return ms_table(ms_subtable({(2, 3): -100}))

    class FakeTTFont:
        def __init__(self, name, filename, validate=0, subfontIndex=0):
            self.face, self.name = FakeFace(), name
            made.append((name, filename, subfontIndex))

    face_dir = tmp_path / "face-dir"
    for name in ("A.ttf", "B.ttf"):
        touch(face_dir / name)
        (face_dir / name).write_bytes(sfnt_face(0))
    with monkeypatch.context() as mp:
        mp.setattr(kincade.pdf, "TTFont", FakeTTFont)
        mp.setattr(kincade.pdf, "registerFont", registered.append)
        mp.setattr(kincade.pdf, "_FACES", {})
        mp.setattr(kincade.pdf, "_KERNING", {})
        first = kincade.pdf._load_ttf(face_dir / "A.ttf", None)
        again = kincade.pdf._load_ttf(face_dir / "A.ttf", None)
        other = kincade.pdf._load_ttf(face_dir / "B.ttf", None)
        assert first is again and len(made) == 2 and len(registered) == 2
        assert (
            first.name == kincade.pdf._face_name(face_dir / "A.ttf", 0)
            and first.name != other.name
        )
        assert first.covers("A") and not first.covers("Z")
        assert kincade.pdf._KERNING[first.name]("V", "i") == pytest.approx(-0.1)
        assert kincade.pdf._KERNING[other.name]("V", "i") == pytest.approx(-0.1)

    # Real system fonts: fonts="auto" embeds four subsets, draws the text and kerns
    # a known pair narrower than the unkerned measurement.
    fonts, _ = load_fontset()
    if fonts is None:
        pytest.skip("no system TrueType fonts")
    pdf = render(pedigree, fonts="auto")
    assert pdf.count(b"/FontFile2") == 4  # sans, bold, serif, italic subsets
    assert count_pages(pdf) == 7
    # Vi is a kerned pair in Times New Roman and Liberation Serif: kerning splits
    # "Virginia" into more than one text run (exactly where depends on the font's own
    # kern pairs, which differ by platform).
    texts = drawn(pdf)
    split = None
    for i in range(len(texts)):
        joined = ""
        j = i
        while j < len(texts) and "Virginia".startswith(joined + texts[j]):
            joined += texts[j]
            j += 1
            if joined == "Virginia":
                break
        if joined == "Virginia":
            split = j - i
            break
    assert split is not None, "Virginia not drawn"
    assert split > 1  # kerning split it into more than one run
    assert fonts.supports("é") and kincade.pdf.text_width(
        "Virginia", fonts.serif, 9
    ) < kincade.pdf.stringWidth("Virginia", fonts.serif, 9)


def test_font_folders(tmp_path, capsys, monkeypatch, request):
    """load_fontset prints nothing and names the roles it cannot fill; find_font_files
    ignores files it does not want and a folder the file system rejects is skipped;
    with no home folder only the system font folders are searched.
    """
    assert load_fontset([tmp_path]) == (None, ["sans", "bold", "serif", "italic"])
    assert capsys.readouterr() == ("", "")

    touch(tmp_path / "a" / "Arial.ttf")
    touch(tmp_path / "a" / "Verdana.ttf")
    assert list(kincade.pdf.find_font_files([tmp_path])) == ["arial.ttf"]

    for error in (
        OSError(errno.ENAMETOOLONG, "File name too long"),
        PermissionError(13, "Permission denied"),
        ValueError("embedded null byte"),
    ):
        home = tmp_path / f"home-{type(error).__name__}"
        good, bad = home / "Library" / "Fonts", home / ".fonts"
        good.mkdir(parents=True)
        bad.mkdir()
        real = Path.is_dir

        def is_dir(self, *args, bad=bad, error=error, real=real, **kw):
            if self == bad:
                raise error
            return real(self, *args, **kw)

        with monkeypatch.context() as mp:
            mp.setenv("HOME", str(home))
            mp.setenv("USERPROFILE", str(home))
            mp.setattr(Path, "is_dir", is_dir)
            found = kincade.pdf.font_dirs()
        assert good in found and bad not in found, type(error).__name__

    expected = kincade.pdf.font_dirs()  # this test's home folder holds no fonts
    request.getfixturevalue("no_home_folder")
    assert kincade.pdf.font_dirs() == expected


@pytest.mark.system_fonts
def test_a_face_that_may_not_be_embedded(tmp_path, fake_loader, monkeypatch, capsys):
    """A restricted face makes the whole document fall back to the base-14 fonts with
    one warning; a face with no OS/2 table is read as fsType 0; subset_embeddable
    follows the OS/2 fsType license bits.
    """
    load_ok = kincade.pdf._load_ttf  # the fixture's fake loader

    def refuse_times(path, psname):
        if path.name == "Times New Roman.ttf":
            raise kincade.pdf.NotEmbeddable(path.name)
        return load_ok(path, psname)

    monkeypatch.setattr(kincade.pdf, "_load_ttf", refuse_times)
    monkeypatch.setattr(kincade.pdf, "font_dirs", lambda: [tmp_path])
    for name in (
        "Helvetica.ttc",
        "Arial.ttf",
        "Arial Bold.ttf",
        "Times New Roman.ttf",
        "Times New Roman Italic.ttf",
    ):
        touch(tmp_path / name)
    fonts, missing = load_fontset([tmp_path])
    assert fonts is None and missing == ["serif"]  # the refused role counts as unusable
    # never a mixed set, even though sans and bold load
    with pytest.warns(UserWarning, match="Times New Roman.ttf.*subset") as notices:
        assert kincade.pdf.choose_fonts("auto") is kincade.pdf.BASE14
    assert len(notices) == 1
    assert capsys.readouterr() == ("", "")

    # A face with no OS/2 table is read as fsType 0, and so may be embedded.
    head = b"\x00" * 54  # a table that is not OS/2
    ttf = touch(tmp_path / "plain.ttf")
    ttf.write_bytes(
        b"\x00\x01\x00\x00"
        + struct.pack(">HHHH", 1, 16, 0, 0)
        + struct.pack(">4sIII", b"head", 0, 12 + 16, len(head))
        + head
    )
    assert kincade.pdf._os2_fs_type(ttf, 0) == 0
    assert kincade.pdf.subset_embeddable(0)

    # subset_embeddable follows the OS/2 fsType license bits.
    rows = [
        (0x0000, True),  # installable: Helvetica and most free fonts
        (0x0008, True),  # editable: Times New Roman and Arial
        (0x0004, True),  # preview and print only is not the restricted bit
        (0x0002 | 0x0004, True),  # restricted, but preview and print allowed
        (0x0002 | 0x0008, True),  # restricted, but editable allowed
        (0x0002, False),  # restricted license
        (0x0002 | 0x0100, False),
        (0x0100, False),  # no subsetting, and we always subset
        (0x0008 | 0x0100, False),
        (0x0200, False),  # bitmap embedding only
        (0x0008 | 0x0200, False),
    ]
    for fs_type, embeddable in rows:
        assert kincade.pdf.subset_embeddable(fs_type) is embeddable, hex(fs_type)


def test_malformed_kern_tables_never_raise():
    """Five representative corruptions of a kern table give no kerning, or drop only
    the bad pair, and never raise.
    """
    rows = [
        ("a truncated table", ms_table(ms_subtable({(1, 2): -5}))[:-3], {}),
        ("a wrong version", ms_table(ms_subtable({(1, 2): -5}), version=3), {}),
        (
            "a subtable that is not horizontal format 0",
            ms_table(
                ms_subtable({(1, 2): -100}, coverage=1 | 4),  # cross-stream
                ms_subtable({(7, 8): -30}),
            ),
            {(7, 8): -30},
        ),
        (
            "a pair reaching past its subtable",
            ms_table(
                # claims a third pair: the next header's bytes
                ms_subtable({(1, 2): -5, (3, 4): -6}, declared_pairs=3),
                ms_subtable({(9, 9): 1}),
            ),
            {},
        ),
        (
            "a value beyond half an em",
            ms_table(
                ms_subtable({(1, 2): -1025, (3, 4): -1024, (5, 6): 1025, (7, 8): 40})
            ),
            {(3, 4): -1024, (7, 8): 40},
        ),
    ]
    for label, table, expected in rows:
        assert kincade.pdf._kern_pairs(table, 2048) == expected, label


@pytest.mark.system_fonts
def test_base14_fallback(tmp_path, fake_loader, monkeypatch, capsys):
    """choose_fonts("auto") falls back to the base-14 fonts with one warning when a
    role is missing, and also when no font folder can be read. Both checks call the
    real choose_fonts, so the test is marked system_fonts to bypass the fixture that
    otherwise forces "auto" straight to base-14.
    """
    # no italic anywhere
    for name in ("Arial.ttf", "Arial Bold.ttf", "Times New Roman.ttf"):
        touch(tmp_path / name)
    with monkeypatch.context() as mp:
        mp.setattr(kincade.pdf, "font_dirs", lambda: [tmp_path])
        with pytest.warns(UserWarning, match="italic") as notices:
            chosen = kincade.pdf.choose_fonts("auto")
    assert chosen is kincade.pdf.BASE14
    assert len(notices) == 1
    assert capsys.readouterr() == ("", "")

    def fail(self, *args, **kw):
        raise OSError(errno.ENAMETOOLONG, "File name too long")

    monkeypatch.setattr(Path, "is_dir", fail)
    assert kincade.pdf.font_dirs() == [] and kincade.pdf.find_font_files() == {}
    with pytest.warns(UserWarning, match="using the built-in PDF fonts"):
        assert kincade.pdf.choose_fonts("auto") is kincade.pdf.BASE14
    assert capsys.readouterr() == ("", "")

"""Fonts: finding, embedding and kerning TrueType faces, and the base-14 fallback."""

import errno
import struct
from pathlib import Path

import pytest

import kincade.pdf
from kincade.pdf import load_fontset

from conftest import render
from pdfread import count_pages

# ---------------------------------------------------------------- fonts


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


@pytest.fixture
def fake_loader(monkeypatch):
    """Replace the TrueType loader: .ttc files in a 'ttc-broken' directory fail,
    everything else loads.
    """
    loaded = []

    def load(path, psname):
        if path.suffix == ".ttc" and "ttc-broken" in str(path.parent):
            raise ValueError("cannot read")
        loaded.append((path.name, psname))
        return kincade.pdf._Face(
            f"F-{len(loaded)}-{path.stem}", lambda ch: ord(ch) < 0x250
        )

    monkeypatch.setattr(kincade.pdf, "_load_ttf", load)
    return loaded


def mac_like(root):
    for name in (
        "Helvetica.ttc",
        "Arial.ttf",
        "Arial Bold.ttf",
        "Times New Roman.ttf",
        "Times New Roman Italic.ttf",
    ):
        touch(root / name)
    return [root]


def test_resolver_prefers_helvetica_and_times_new_roman(tmp_path, fake_loader):
    fonts, missing = load_fontset(mac_like(tmp_path))
    assert missing == [] and fonts is not None
    assert [Path(f).name for f in fonts.files] == [
        "Helvetica.ttc",
        "Helvetica.ttc",
        "Times New Roman.ttf",
        "Times New Roman Italic.ttf",
    ]
    assert fake_loader[:2] == [
        ("Helvetica.ttc", "Helvetica"),
        ("Helvetica.ttc", "Helvetica-Bold"),
    ]
    assert (fonts.sans, fonts.bold, fonts.serif, fonts.italic) == (
        "F-1-Helvetica",
        "F-2-Helvetica",
        "F-3-Times New Roman",
        "F-4-Times New Roman Italic",
    )
    assert fonts.supports("e") and not fonts.supports("\u4e2d")


def test_resolver_falls_back_to_arial_when_the_ttc_will_not_load(tmp_path, fake_loader):
    root = tmp_path / "ttc-broken"
    fonts, missing = load_fontset(mac_like(root))
    assert missing == []
    assert [Path(f).name for f in fonts.files] == [
        "Arial.ttf",
        "Arial Bold.ttf",
        "Times New Roman.ttf",
        "Times New Roman Italic.ttf",
    ]


def test_resolver_finds_liberation_fonts_in_nested_directories_case_insensitively(
    tmp_path, fake_loader
):
    names = [
        "LiberationSans-Regular.ttf",
        "LIBERATIONSANS-BOLD.TTF",
        "LiberationSerif-Regular.ttf",
        "LiberationSerif-Italic.ttf",
    ]
    for i, name in enumerate(names):
        touch(tmp_path / "truetype" / f"liberation{i}" / name)
    fonts, missing = load_fontset([tmp_path])
    assert missing == [] and [Path(f).name for f in fonts.files] == names


@pytest.mark.system_fonts
def test_resolver_reports_missing_roles_and_auto_falls_back_to_base14(
    tmp_path, fake_loader, monkeypatch, capsys
):
    # no italic anywhere
    for name in ("Arial.ttf", "Arial Bold.ttf", "Times New Roman.ttf"):
        touch(tmp_path / name)
    fonts, missing = load_fontset([tmp_path])
    assert fonts is None and missing == ["italic"]
    monkeypatch.setattr(kincade.pdf, "font_dirs", lambda: [tmp_path])
    with pytest.warns(UserWarning, match="italic") as notices:
        chosen = kincade.pdf.choose_fonts("auto")
    assert chosen is kincade.pdf.BASE14  # never a mixed set
    assert len(notices) == 1
    assert capsys.readouterr() == ("", "")


def test_load_fontset_prints_nothing_and_names_the_roles_it_cannot_fill(
    tmp_path, capsys
):
    assert load_fontset([tmp_path]) == (None, ["sans", "bold", "serif", "italic"])
    assert capsys.readouterr() == ("", "")


def test_choose_fonts_modes():
    assert kincade.pdf.choose_fonts("base14") is kincade.pdf.BASE14
    custom = kincade.pdf.FontSet(sans="X")
    assert kincade.pdf.choose_fonts(custom) is custom
    with pytest.raises(ValueError):
        kincade.pdf.choose_fonts("comic-sans")


def test_find_font_files_ignores_other_files(tmp_path):
    touch(tmp_path / "a" / "Arial.ttf")
    touch(tmp_path / "a" / "Verdana.ttf")
    assert list(kincade.pdf.find_font_files([tmp_path])) == ["arial.ttf"]


def sfnt_face(fs_type, base=0):
    """A minimal sfnt face whose table offsets start at byte `base` of its file; its
    OS/2 table holds fs_type.
    """
    # version, avg width, weight, width class, fsType (at 8)
    os2 = struct.pack(">HhHHH", 4, 0, 400, 5, fs_type)
    offset = base + 12 + 16  # the offset table, then one table record
    return (
        b"\x00\x01\x00\x00"
        + struct.pack(">HHHH", 1, 16, 0, 0)
        + struct.pack(">4sIII", b"OS/2", 0, offset, len(os2))
        + os2
    )


def ttc_file(fs_types):
    """A TrueType collection with one face per fs_type (table offsets are absolute, as
    in real collections).
    """
    base = 12 + 4 * len(fs_types)
    offsets, faces = [], []
    for fs_type in fs_types:
        offsets.append(base)
        faces.append(sfnt_face(fs_type, base))
        base += len(faces[-1])
    return (
        b"ttcf"
        + struct.pack(">II", 0x00010000, len(fs_types))
        + b"".join(struct.pack(">I", off) for off in offsets)
        + b"".join(faces)
    )


@pytest.mark.parametrize(
    "fs_type,embeddable",
    [
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
    ],
)
def test_subset_embedding_follows_the_os2_license_bits(fs_type, embeddable):
    assert kincade.pdf.subset_embeddable(fs_type) is embeddable


def test_a_face_with_no_os2_table_has_fstype_0_and_may_be_embedded(tmp_path):
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


def test_os2_fstype_is_read_from_a_ttf_and_from_each_face_of_a_ttc(tmp_path):
    ttf = touch(tmp_path / "one.ttf")
    ttf.write_bytes(sfnt_face(0x0100))
    assert kincade.pdf._os2_fs_type(ttf, 0) == 0x0100
    ttc = touch(tmp_path / "pair.ttc")
    ttc.write_bytes(ttc_file([0x0000, 0x0008]))
    assert [kincade.pdf._os2_fs_type(ttc, i) for i in (0, 1)] == [0x0000, 0x0008]


@pytest.mark.parametrize("fs_type", [0x0002, 0x0100, 0x0200])
def test_a_refused_face_is_never_handed_to_reportlab(tmp_path, monkeypatch, fs_type):
    path = touch(tmp_path / "Restricted.ttf")
    path.write_bytes(sfnt_face(fs_type))

    def reportlab_must_not_see_it(*_args, **_kwargs):
        raise AssertionError("TTFont was built for a face that may not be embedded")

    monkeypatch.setattr(kincade.pdf, "TTFont", reportlab_must_not_see_it)
    with pytest.raises(kincade.pdf.NotEmbeddable, match=r"Restricted\.ttf"):
        kincade.pdf._load_ttf(path, None)


@pytest.mark.system_fonts
def test_a_face_that_may_not_be_embedded_falls_back_to_base14_for_the_whole_document(
    tmp_path, fake_loader, monkeypatch, capsys
):
    load_ok = kincade.pdf._load_ttf  # the fixture's fake loader

    def refuse_times(path, psname):
        if path.name == "Times New Roman.ttf":
            raise kincade.pdf.NotEmbeddable(path.name)
        return load_ok(path, psname)

    monkeypatch.setattr(kincade.pdf, "_load_ttf", refuse_times)
    monkeypatch.setattr(kincade.pdf, "font_dirs", lambda: [tmp_path])
    mac_like(tmp_path)
    fonts, missing = load_fontset([tmp_path])
    assert fonts is None and missing == ["serif"]  # the refused role counts as unusable
    # never a mixed set, even though sans and bold load
    with pytest.warns(UserWarning, match="Times New Roman.ttf.*subset") as notices:
        assert kincade.pdf.choose_fonts("auto") is kincade.pdf.BASE14
    assert len(notices) == 1
    assert capsys.readouterr() == ("", "")


def test_clean_with_a_custom_glyph_set():
    ascii_only = lambda ch: ord(ch) < 128
    assert kincade.pdf.clean("Zoë Łódź", ascii_only) == "Zoe ?odz"
    assert kincade.pdf.clean("plain", ascii_only) == "plain"
    assert kincade.pdf.clean("Zoë “q” …") == "Zoë “q” …"  # default: cp1252 keeps these


def test_base14_text_is_cp1252_sanitized():
    assert kincade.pdf.BASE14.clean("Łódź") == "?ódz"


# ---------------------------------------------------------------- kerning


def kern_table_ms(pairs):
    body = b"".join(struct.pack(">HHh", a, b, v) for (a, b), v in sorted(pairs.items()))
    head = struct.pack(">HHH", 0, 14 + len(body), 1) + struct.pack(
        ">HHHH", len(pairs), 0, 0, 0
    )
    return struct.pack(">HH", 0, 1) + head + body


def kern_table_apple(pairs):
    body = b"".join(struct.pack(">HHh", a, b, v) for (a, b), v in sorted(pairs.items()))
    head = struct.pack(">IHH", 16 + len(body), 0, 0) + struct.pack(
        ">HHHH", len(pairs), 0, 0, 0
    )
    return struct.pack(">II", 0x00010000, 1) + head + body


@pytest.mark.parametrize("build", [kern_table_ms, kern_table_apple])
def test_kern_table_parsing(build):
    pairs = {(36, 77): -123, (50, 51): 40}
    assert kincade.pdf._kern_pairs(build(pairs), 2048) == pairs


@pytest.mark.system_fonts
def test_embedded_fonts_end_to_end(pedigree):
    fonts, _ = load_fontset()
    if fonts is None:
        pytest.skip("no system TrueType fonts")
    pdf = render(pedigree, fonts="auto")
    assert pdf.count(b"/FontFile2") == 4  # sans, bold, serif, italic subsets
    assert count_pages(pdf) == 7
    # Vi is a kerned pair in Times New Roman and Liberation Serif
    assert fonts.supports("é") and kincade.pdf.text_width(
        "Virginia", fonts.serif, 9
    ) < kincade.pdf.stringWidth("Virginia", fonts.serif, 9)


# ---- kern table reader -------------------------------------------------------


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


def test_a_pair_that_would_leave_its_left_glyph_negative_is_dropped_on_load():
    # 1000 units/em, 250-unit glyphs
    table = ms_table(ms_subtable({(1, 2): -500, (1, 4): -250, (3, 4): -100}))
    assert kincade.pdf._kern_pairs(table, 1000, lambda glyph: 250) == {
        (1, 4): -250,
        (3, 4): -100,
    }


def apple_subtable(pairs, coverage=0, declared_pairs=None, length=None):
    body = b"".join(struct.pack(">HHh", a, b, v) for (a, b), v in sorted(pairs.items()))
    n = len(pairs) if declared_pairs is None else declared_pairs
    sub = struct.pack(">HHHH", n, 0, 0, 0) + body
    return (
        struct.pack(">IHH", length if length is not None else 8 + len(sub), coverage, 0)
        + sub
    )


def apple_table(*subtables, version=0x00010000):
    return struct.pack(">II", version, len(subtables)) + b"".join(subtables)


def test_kern_values_accumulate_across_ordinary_subtables_and_override_replaces():
    one, two = {(1, 2): -100, (3, 4): 50}, {(1, 2): -20, (5, 6): 10}
    assert kincade.pdf._kern_pairs(
        ms_table(ms_subtable(one), ms_subtable(two)), 2048
    ) == {(1, 2): -120, (3, 4): 50, (5, 6): 10}
    # bit 3: override
    assert kincade.pdf._kern_pairs(
        ms_table(ms_subtable(one), ms_subtable(two, coverage=1 | 8)), 2048
    ) == {(1, 2): -20, (3, 4): 50, (5, 6): 10}
    assert kincade.pdf._kern_pairs(
        apple_table(apple_subtable(one), apple_subtable(two)), 2048
    ) == {(1, 2): -120, (3, 4): 50, (5, 6): 10}


@pytest.mark.parametrize(
    "coverage_ms,coverage_apple",
    [
        (1 | 2, 0x0001),  # minimum values / (apple: not format 0)
        (1 | 4, 0x4000),  # cross-stream
        (0, 0x8000),  # vertical
        (1 | 0x100, 0x2000),  # format 1 / variation
    ],
)
def test_only_plain_horizontal_format_0_subtables_are_used(coverage_ms, coverage_apple):
    skipped, wanted = {(1, 2): -100}, {(7, 8): -30}
    assert (
        kincade.pdf._kern_pairs(
            ms_table(ms_subtable(skipped, coverage_ms), ms_subtable(wanted)), 2048
        )
        == wanted
    )
    assert (
        kincade.pdf._kern_pairs(
            apple_table(
                apple_subtable(skipped, coverage_apple), apple_subtable(wanted)
            ),
            2048,
        )
        == wanted
    )


def test_kern_values_beyond_half_an_em_are_discarded():
    pairs = {(1, 2): -1025, (3, 4): -1024, (5, 6): 1025, (7, 8): 40}
    assert kincade.pdf._kern_pairs(ms_table(ms_subtable(pairs)), 2048) == {
        (3, 4): -1024,
        (7, 8): 40,
    }


@pytest.mark.parametrize(
    "table",
    [
        b"",
        b"\x00",
        ms_table(version=1)[:3],
        ms_table(ms_subtable({(1, 2): -5}), version=3),
        ms_table(ms_subtable({(1, 2): -5}))[:-3],  # truncated pair array
        ms_table(
            ms_subtable({(1, 2): -5}, declared_pairs=9)
        ),  # more pairs than the subtable holds
        ms_table(
            ms_subtable({(1, 2): -5}, length=7)
        ),  # length too short for its header
        ms_table(ms_subtable({(1, 2): -5}, length=900)),  # length beyond the table
        ms_table(ms_subtable({(1, 2): -5}), ms_subtable({(1, 2): -5}))[
            :-5
        ],  # second subtable cut short
        ms_table(ms_subtable({(1, 2): -5}, length=0)),
        apple_table(apple_subtable({(1, 2): -5}), version=2),
        apple_table(apple_subtable({(1, 2): -5}))[:-1],
        apple_table(apple_subtable({(1, 2): -5}, declared_pairs=50)),
        apple_table(apple_subtable({(1, 2): -5}, length=3)),
        bytes(range(256)) * 4,
        b"\xff" * 64,
    ],
)
def test_a_malformed_kern_table_gives_no_kerning_and_never_raises(table):
    assert kincade.pdf._kern_pairs(table, 2048) == {}


def test_pairs_cannot_reach_beyond_their_own_subtable_into_the_next_one():
    # claims a third pair: the next header's bytes
    first = ms_subtable({(1, 2): -5, (3, 4): -6}, declared_pairs=3)
    assert (
        kincade.pdf._kern_pairs(ms_table(first, ms_subtable({(9, 9): 1})), 2048) == {}
    )


# ---- font identity -------------------------------------------------------------


def test_face_names_come_from_file_and_subfont_and_are_stable(tmp_path):
    a0, a1 = (
        kincade.pdf._face_name(tmp_path / "A.ttc", 0),
        kincade.pdf._face_name(tmp_path / "A.ttc", 1),
    )
    assert a0 == kincade.pdf._face_name(tmp_path / "A.ttc", 0) and a0 != a1
    assert a0 != kincade.pdf._face_name(tmp_path / "B.ttc", 0)
    assert a0.startswith("CP-")


def test_a_face_is_registered_once_and_registration_coverage_and_kerning_share_one_object(
    monkeypatch, tmp_path
):
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

    monkeypatch.setattr(kincade.pdf, "TTFont", FakeTTFont)
    monkeypatch.setattr(kincade.pdf, "registerFont", registered.append)
    monkeypatch.setattr(kincade.pdf, "_FACES", {})
    monkeypatch.setattr(kincade.pdf, "_KERNING", {})
    # the license flags are read from the file before reportlab is called
    for name in ("A.ttf", "B.ttf"):
        (tmp_path / name).write_bytes(sfnt_face(0))
    first = kincade.pdf._load_ttf(tmp_path / "A.ttf", None)
    again = kincade.pdf._load_ttf(tmp_path / "A.ttf", None)
    other = kincade.pdf._load_ttf(tmp_path / "B.ttf", None)
    # no second registration
    assert first is again and len(made) == 2 and len(registered) == 2
    assert (
        first.name == kincade.pdf._face_name(tmp_path / "A.ttf", 0)
        and first.name != other.name
    )
    assert first.covers("A") and not first.covers("Z")
    # kerning lives under the same name
    assert kincade.pdf._KERNING[first.name]("V", "i") == pytest.approx(-0.1)
    assert kincade.pdf._KERNING[other.name]("V", "i") == pytest.approx(-0.1)


@pytest.mark.parametrize(
    "error",
    [
        OSError(errno.ENAMETOOLONG, "File name too long"),
        PermissionError(13, "Permission denied"),
        ValueError("embedded null byte"),
    ],
)
def test_a_font_folder_the_file_system_rejects_is_skipped(tmp_path, monkeypatch, error):
    """font_dirs probes the system and user font folders. One the file system cannot
    look at is left out; the others count, and nothing is raised.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    good, bad = tmp_path / "Library" / "Fonts", tmp_path / ".fonts"
    good.mkdir(parents=True)
    bad.mkdir()
    real = Path.is_dir

    def is_dir(self, *args, **kw):
        if self == bad:
            raise error
        return real(self, *args, **kw)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    found = kincade.pdf.font_dirs()
    assert good in found and bad not in found


def test_with_no_home_folder_only_the_system_font_folders_are_looked_at(request):
    expected = kincade.pdf.font_dirs()  # the test's home folder holds no fonts
    request.getfixturevalue("no_home_folder")
    assert kincade.pdf.font_dirs() == expected


@pytest.mark.system_fonts
@pytest.mark.parametrize(
    "error",
    [OSError(errno.ENAMETOOLONG, "File name too long"), ValueError("embedded null")],
)
def test_when_no_font_folder_can_be_looked_at_the_fonts_fall_back_to_the_base_14(
    monkeypatch, capsys, error
):
    def fail(self, *args, **kw):
        raise error

    monkeypatch.setattr(Path, "is_dir", fail)
    assert kincade.pdf.font_dirs() == [] and kincade.pdf.find_font_files() == {}
    with pytest.warns(UserWarning, match="using the built-in PDF fonts"):
        assert kincade.pdf.choose_fonts("auto") is kincade.pdf.BASE14
    assert capsys.readouterr() == ("", "")

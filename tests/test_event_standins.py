"""Christening and burial stand-ins: when a person has no BIRT (or DEAT) with a date or
place, the first christening or baptism (or burial, else cremation) gives the birth (or
death) lines, with their own labels. Options.event_standins (--no-event-standins) turns
this off. A christening year is an upper bound on the birth for the privacy estimate,
and cremation means not living, as burial does.

Synthetic GEDCOM only.
"""

import pytest

import kincade.charts
import kincade.cli
import kincade.gedcom
import kincade.lang
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom

from conftest import ged, render
from pdfread import drawn


def index_lines(tree, lang=None):
    strings = kincade.lang.load_strings(lang)
    charts = plan_charts(tree, "I1")
    return kincade.pdf.build_index(
        tree, charts, lambda pid: False, exclude_private=False, strings=strings
    )


# ---------------------------------------------------------------- the box lines


def test_a_christening_stands_in_for_a_missing_birth():
    text = drawn(
        render(
            read_gedcom(
                ged(
                    "0 @I1@ INDI",
                    "1 NAME Ann /Doe/",
                    "1 CHR",
                    "2 DATE 1750",
                    "2 PLAC Little Hall",
                )
            ),
            generations=1,
            index=False,
        )
    )
    assert "chr. 1750" in text and "chrp. Little Hall" in text
    # the birth labels are not drawn for the christening
    assert "b." not in text and "bp." not in text


def test_a_baptism_stands_in_when_there_is_no_christening():
    tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Ann /Doe/", "1 BAPM", "2 DATE 1751", "2 PLAC Chapel")
    )
    text = drawn(render(tree, index=False))
    assert "chr. 1751" in text and "chrp. Chapel" in text


def test_a_christening_is_preferred_to_a_baptism():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 BAPM",
            "2 DATE 1749",
            "1 CHR",
            "2 DATE 1750",
        )
    )
    text = drawn(render(tree, index=False))
    assert "chr. 1750" in text and "chr. 1749" not in text


def test_a_burial_stands_in_for_a_missing_death():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 BIRT",
            "2 DATE 1700",
            "1 BURI",
            "2 DATE 1800",
            "2 PLAC Churchyard",
        )
    )
    # one box: the other boxes have their own labels
    text = drawn(render(tree, generations=1, index=False))
    assert "bur. 1800" in text and "burp. Churchyard" in text
    assert "d." not in text and "dp." not in text


def test_a_cremation_stands_in_when_there_is_no_burial():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 BIRT",
            "2 DATE 1700",
            "1 CREM",
            "2 DATE 1900",
            "2 PLAC Crematorium",
        )
    )
    text = drawn(render(tree, index=False))
    assert "crem. 1900" in text and "cremp. Crematorium" in text


def test_a_burial_is_preferred_to_a_cremation():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 CREM",
            "2 DATE 1900",
            "1 BURI",
            "2 DATE 1800",
        )
    )
    text = drawn(render(tree, index=False))
    assert "bur. 1800" in text and "crem. 1900" not in text


def test_an_empty_record_does_not_block_the_stand_in():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 BIRT Y",
            "1 CHR",
            "2 DATE 1750",
            "1 DEAT Y",
            "1 BURI",
            "2 DATE 1800",
        )
    )
    text = drawn(render(tree, index=False))
    assert "chr. 1750" in text and "bur. 1800" in text


def test_a_birth_place_alone_blocks_the_christening():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 BIRT",
            "2 PLAC Boston",
            "1 CHR",
            "2 DATE 1750",
        )
    )
    text = drawn(render(tree, index=False))
    assert "bp. Boston" in text and "chr. 1750" not in text and "chrp." not in text


def test_a_death_place_alone_blocks_the_burial():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 DEAT",
            "2 PLAC Dayton",
            "1 BURI",
            "2 DATE 1800",
        )
    )
    text = drawn(render(tree, index=False))
    assert "dp. Dayton" in text and "bur. 1800" not in text


def test_a_person_with_no_christening_or_burial_keeps_the_usual_labels():
    text = drawn(
        render(read_gedcom(ged("0 @I1@ INDI", "1 NAME Ann /Doe/")), index=False)
    )
    assert "b." in text and "d." in text and "chr." not in text and "bur." not in text


# ---------------------------------------------------------------- the index years


def test_index_years_use_the_stand_in_pieces():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 CHR",
            "2 DATE 1750",
            "1 BURI",
            "2 DATE 1800",
        )
    )
    assert index_lines(tree) == ["DOE, Ann (chr. 1750 – bur. 1800), 1-1"]


def test_index_cremation_piece():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 BAPM",
            "2 DATE 1750",
            "1 CREM",
            "2 DATE 1900",
        )
    )
    assert index_lines(tree) == ["DOE, Ann (chr. 1750 – crem. 1900), 1-1"]


def test_index_sorts_by_the_stand_in_birth_year():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 BIRT",
            "2 DATE 1800",
            "0 @I2@ INDI",
            "1 NAME Ann /Doe/",
            "1 CHR",
            "2 DATE 1750",
        )
    )
    charts = [
        kincade.charts.Chart(1, {**dict.fromkeys(range(1, 16)), 1: "I1", 2: "I2"})
    ]
    entries = kincade.pdf.build_index(
        tree, charts, lambda pid: False, exclude_private=False
    )
    assert entries[0].startswith("DOE, Ann (chr. 1750)")


# ---------------------------------------------------------------- German


def test_german_labels_and_index_pieces():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 CHR",
            "2 DATE 1750",
            "2 PLAC Little Hall",
            "1 BURI",
            "2 DATE 1800",
            "2 PLAC Churchyard",
        )
    )
    text = drawn(render(tree, index=False, lang="de"))
    assert "get. 1750" in text and "in Little Hall" in text
    assert "begr. 1800" in text and "in Churchyard" in text
    assert index_lines(tree, "de") == ["DOE, Ann (~ 1750, begr. 1800), 1/1"]


def test_german_cremation_label_is_written_out():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 CREM",
            "2 DATE 1900",
            "2 PLAC Crematorium",
        )
    )
    text = drawn(render(tree, index=False, lang="de"))
    assert "eingeäschert 1900" in text and "in Crematorium" in text


# ---------------------------------------------------------------- privacy


def living_of(tree, pid="I1"):
    return kincade.charts.living_checker(tree, plan_charts(tree, "I1"), 2026)(pid)


def test_a_christening_only_person_born_recently_may_be_living():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Kid /Doe/",
            "1 CHR",
            "2 DATE 2000",
            "2 PLAC Springfield",
        )
    )
    assert living_of(tree) is True
    text = drawn(render(tree, exclude_private=True, index=False))
    assert "chr. 2000" not in text and "Springfield" not in text
    assert "Kid DOE" not in text and "Living" in text


def test_a_christening_long_ago_is_not_living():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Old /Doe/",
            "1 CHR",
            "2 DATE 1900",
            "2 PLAC Springfield",
        )
    )
    assert living_of(tree) is False
    assert "chr. 1900" in drawn(render(tree, exclude_private=True, index=False))


def test_the_christening_year_is_the_latest_possible_birth_when_there_is_no_birth_date():
    # the father's descendant (born 1990) would put his birth at 1965, but his
    # christening in 1900 bounds it
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Kid /Doe/",
            "1 BIRT",
            "2 DATE 1990",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Dad /Doe/",
            "1 CHR",
            "2 DATE 1900",
            "1 FAMS @F1@",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
        )
    )
    assert living_of(tree, "I2") is False


def test_a_descendants_christening_gives_an_ancestor_a_privacy_estimate():
    # the father has no dates of his own; his child's christening (1800) puts his
    # estimate at 1775, not living.
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Kid /Doe/",
            "1 CHR",
            "2 DATE 1800",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Dad /Doe/",
            "1 BIRT",
            "2 PLAC Ohio",
            "1 FAMS @F1@",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
        )
    )
    assert "bp. Ohio" in drawn(render(tree, exclude_private=True, index=False))
    assert "bp. Ohio" in drawn(
        render(tree, exclude_private=True, index=False, event_standins=False)
    )


@pytest.mark.parametrize("standins", [True, False])
@pytest.mark.parametrize("record", ["CHR", "BAPM"])
@pytest.mark.parametrize("birth", [[], ["1 BIRT Y"], ["1 BIRT", "2 PLAC Secretville"]])
def test_a_christening_bounds_a_missing_birth_date_regardless_of_display(
    standins, record, birth
):
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Jane /Doe/",
            *birth,
            f"1 {record}",
            "2 DATE 1900",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME John /Doe/",
            "1 BIRT",
            "2 PLAC Secretville",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
        )
    )
    text = drawn(render(tree, exclude_private=True, event_standins=standins))
    assert "bp. Secretville" in text
    assert living_of(tree) is False
    assert living_of(tree, "I2") is False
    if not standins:
        assert "chr. 1900" not in text


@pytest.mark.parametrize("standins", [True, False])
@pytest.mark.parametrize("birth", ["unknown", "12 MAY", "@#DHEBREW@ 1 TSH 5650"])
def test_a_recorded_yearless_birth_takes_precedence_over_a_christening(standins, birth):
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Jane /Doe/",
            "1 BIRT",
            f"2 DATE {birth}",
            "2 PLAC Secretville",
            "1 CHR",
            "2 DATE 1900",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME John /Doe/",
            "1 BIRT",
            "2 PLAC Secretville",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
        )
    )
    assert "Secretville" not in drawn(
        render(tree, exclude_private=True, event_standins=standins)
    )
    assert kincade.charts._birth_estimates(tree, plan_charts(tree, "I1"), 2026) == {
        "I1": 2026,
        "I2": 2001,
    }


@pytest.mark.parametrize("record", ["BURI", "CREM"])
def test_a_burial_or_cremation_means_not_living_with_or_without_the_standins(record):
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Old /Doe/",
            "1 BIRT",
            "2 DATE 1990",
            f"1 {record}",
            "2 DATE 2010",
            "2 PLAC Crematorium",
        )
    )
    charts = plan_charts(tree, "I1")
    for standins in (True, False):
        assert kincade.charts.living_checker(tree, charts, 2026)("I1") is False
        text = drawn(
            render(tree, exclude_private=True, index=False, event_standins=standins)
        )
        assert "b. 1990" in text
    label = {"BURI": "bur.", "CREM": "crem."}[record]
    assert f"{label} 2010" in drawn(render(tree, exclude_private=True, index=False))


# ---------------------------------------------------------------- --no-event-standins


def test_no_event_standins_draws_births_and_deaths_only():
    extras = ["1 CHR", "2 DATE 1690", "1 BURI", "2 DATE 1800", "1 CREM", "2 DATE 1801"]
    bare = ["0 @I1@ INDI", "1 NAME Ann /Doe/"]
    plain = read_gedcom(ged(*bare))
    with_extras = read_gedcom(ged(*bare, *extras))
    # births and deaths only
    assert drawn(render(with_extras, event_standins=False)) == drawn(render(plain))
    # and with stand-ins they show
    assert drawn(render(with_extras)) != drawn(render(plain))
    dated = [
        "0 @I1@ INDI",
        "1 NAME Ann /Doe/",
        "1 BIRT",
        "2 DATE 1700",
        "1 DEAT",
        "2 DATE 1780",
    ]
    # BIRT/DEAT win
    assert drawn(render(read_gedcom(ged(*dated, *extras)))) == drawn(
        render(read_gedcom(ged(*dated)))
    )


def test_no_event_standins_on_the_command_line(tmp_path, rendered_options):
    path = tmp_path / "f.ged"
    path.write_bytes(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 CHR",
            "2 DATE 1750",
            "1 BURI",
            "2 DATE 1800",
        )
    )
    base = [str(path), "--root", "@I1@", "-o", str(tmp_path / "x.pdf")]
    assert kincade.cli.main(base + ["--no-event-standins"]) == 0
    assert kincade.cli.main(base) == 0
    assert [o.event_standins for o in rendered_options] == [False, True]


def test_find_lists_the_years_of_the_standins_unless_they_are_off(tmp_path, capsys):
    path = tmp_path / "f.ged"
    path.write_bytes(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Doe/",
            "1 CHR",
            "2 DATE 1750",
            "1 BURI",
            "2 DATE 1800",
            "0 @I2@ INDI",
            "1 NAME Bea /Doe/",
            "1 CREM",
            "2 DATE 1900",
        )
    )
    assert kincade.cli.main([str(path), "--find", "doe"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "I1\tAnn DOE\t1750-1800",
        "I2\tBea DOE\t?-1900",
    ]
    assert kincade.cli.main([str(path), "--find", "doe", "--no-event-standins"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "I1\tAnn DOE\t",
        "I2\tBea DOE\t",
    ]

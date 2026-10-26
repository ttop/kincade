"""Privacy: who counts as possibly living, and what Options.exclude_private hides.
All checks are on the drawn PDF, or on the estimate functions that decide it
(charts.py:201-418, pdf.py:1915-1934).
"""

import pytest

import kincade.charts
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom
from kincade.pdf import Options, render_pdf

from conftest import (
    FIX,
    TODAY,
    dad_and_kid,
    ged,
    render,
    render_charts,
    secret_shown,
)
from pdfread import drawn

# ---------------------------------------------------------------- who counts as living


def test_who_counts_as_possibly_living():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Kid /K/",
            "1 BIRT",
            "2 DATE 2000",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Dad /K/",
            "1 FAMC @F2@",  # est 1975
            "0 @I3@ INDI",
            "1 NAME Mum /K/",
            "1 BIRT",
            "2 DATE 1976",
            "1 DEAT Y",  # dead
            "0 @I4@ INDI",
            "1 NAME Gramps /K/",
            "1 FAMC @F4@",  # est 1950
            "0 @I5@ INDI",
            "1 NAME Gran /K/",
            "0 @I6@ INDI",
            "1 NAME Great /K/",
            "1 BURI",
            "2 PLAC Churchyard",  # buried
            "0 @I8@ INDI",
            "1 NAME Old /K/",
            "1 FAMC @F8@",  # est 1925
            "0 @I9@ INDI",
            "1 NAME Unknown /K/",
            "0 @I10@ INDI",
            "1 NAME Edge1926 /K/",
            "1 BIRT",
            "2 DATE 1926",  # exactly LIVING_YEARS (100) before 2026: not living
            "0 @I11@ INDI",
            "1 NAME Edge1927 /K/",
            "1 BIRT",
            "2 DATE 1927",  # one year later: still within LIVING_YEARS
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 WIFE @I3@",
            "0 @F2@ FAM",
            "1 HUSB @I4@",
            "1 WIFE @I5@",
            "0 @F4@ FAM",
            "1 HUSB @I8@",
            "1 WIFE @I9@",
            "0 @F8@ FAM",
            "1 HUSB @I6@",
        )
    )
    charts = plan_charts(tree, "I1")
    living = kincade.charts.living_checker(tree, charts, 2026)
    expected = {
        "I1": True,  # born 2000
        "I2": True,  # no data: 2000 - 25 = 1975
        "I3": False,  # DEAT present
        "I4": True,  # 1975 - 25 = 1950
        "I5": True,  # as the mother of I2: 1950
        "I6": False,  # BURI present
        "I8": False,  # 1925: one year past the 100-year line
        "I9": False,
        "I10": False,  # born exactly 2026 - LIVING_YEARS: not living
        "I11": True,  # born one year later: living
    }
    for pid, want in expected.items():
        assert living(pid) is want, pid
    text = " ".join(drawn(render_charts(tree, exclude_private=True)))
    for pid, given in (("I1", "Kid"), ("I2", "Dad"), ("I4", "Gramps"), ("I5", "Gran")):
        assert given not in text, pid
    for pid, given in (
        ("I3", "Mum"),
        ("I6", "Great"),
        ("I8", "Old"),
        ("I9", "Unknown"),
    ):
        assert given in text, pid
    assert text.count("Living") >= 4
    # a person with no dates at all counts as living unless dead, buried or cremated
    nodates = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Nobody /Known/",
            "0 @I2@ INDI",
            "1 NAME Dead /Known/",
            "1 DEAT",
            "0 @I3@ INDI",
            "1 NAME Buried /Known/",
            "1 BURI",
            "0 @I4@ INDI",
            "1 NAME Old /Known/",
            "1 BIRT",
            "2 DATE 1800",
            "0 @I5@ INDI",
            "1 NAME Cremated /Known/",
            "1 CREM",
        )
    )
    chart = dict.fromkeys(range(1, 16))
    nodates_charts = [
        kincade.charts.Chart(1, {**chart, 1: "I1", 2: "I2", 3: "I3", 4: "I4", 5: "I5"})
    ]
    nodates_living = kincade.charts.living_checker(nodates, nodates_charts, 2026)
    assert [nodates_living(f"I{n}") for n in (1, 2, 3, 4, 5)] == [
        True,
        False,
        False,
        False,
        False,
    ]
    assert nodates_living("I99") is False  # not in the file at all: nothing to hide


# ---------------------------------------------------------------- the private PDF


def test_private_pdfs_hide_the_living(pedigree):
    pdf = render(pedigree, exclude_private=True)
    assert b"Jane ASHFORD" not in pdf and b"Mary McCLURE" not in pdf
    assert b"Tom BAKER" not in pdf  # the root's living spouse (box 1's spouse line)
    assert b"(Living)" in pdf
    for hidden in (
        b"14 Feb 1980",
        b"Springfield",
        b"12 Jun 1975",
        b"9 Sep 1952",
        b"5 Jun 2005",
        b"Peoria",
    ):
        # living people, and marriages with a living spouse
        assert hidden not in pdf, hidden
    # only William's (dead) birth and death places remain
    assert pdf.count(b"Akron, Ohio") == 2
    assert b"(b.)" in pdf and b"(m.)" in pdf and b"(mp.)" in pdf  # labels stay
    assert b"(b. 3 Mar 1950)" in pdf  # John is dead: shown
    assert b"(b. 1 Jun 1900)" in pdf
    assert b"ASHFORD, Jane" not in pdf  # living people are omitted from the index
    # en dash: cp1252 0x96, octal-escaped
    assert b"ASHFORD, John \\(b. 1950 \\226 d. 2020\\), 1-2" in pdf
    without = render(pedigree)
    assert b"(b. 14 Feb 1980)" in without and b"(m. 12 Jun 1975)" in without

    # the record ID is hidden too
    young = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Young /ROOT/", "1 BIRT", "2 DATE 1 JAN 2000")
    )
    hidden_id = render_charts(young, generations=1, show_ids=True, exclude_private=True)
    assert "[I1]" not in drawn(hidden_id)
    assert "Living" in drawn(hidden_id)

    # metadata and text never contain the name of someone who may be living
    secret = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Jane /Secret/",
            "1 BIRT",
            "2 DATE 1990",
            "2 PLAC Hidden birthplace",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME John /Public/",
            "1 DEAT Y",
            "1 FAMS @F1@",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
        )
    )
    private_pdf = render(secret, root="I1", exclude_private=True)
    text = drawn(private_pdf)
    assert "Living" in text
    for word in ("Jane", "Secret", "Hidden birthplace", "1990"):
        assert word.casefold() not in " ".join(text).casefold()
        assert word.casefold() not in private_pdf.decode("latin-1").casefold()
    assert "John" in " ".join(text)
    # an explicit title or footer is kept under privacy
    with_title = render(
        secret, root="I1", exclude_private=True, title="Jane's title", footer="F"
    )
    assert "Jane's title" in drawn(with_title) and "F" in drawn(with_title)

    # a marriage is hidden when either partner may be living, not only the one in the
    # box's own name line: here the root (Mom, dead) married a living Dad
    mixed_marriage = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Mom /T6/",
            "1 SEX F",
            "1 BIRT",
            "2 DATE 1900",
            "1 DEAT Y",
            "1 FAMS @F1@",
            "0 @I2@ INDI",
            "1 NAME Dad /T6/",
            "1 SEX M",
            "1 BIRT",
            "2 DATE 2000",
            "1 FAMS @F1@",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 WIFE @I1@",
            "1 MARR",
            "2 DATE 1925",
            "2 PLAC Testville",
        )
    )
    mixed_pdf = render_charts(mixed_marriage, root="I1", exclude_private=True)
    mixed_text = " ".join(drawn(mixed_pdf))
    assert "1925" not in mixed_text and "Testville" not in mixed_text


# ---------------------------------------------------------------- generations and large print


def test_privacy_does_not_depend_on_the_page():
    """Father is drawn at position 2 and again at generation 6 (father of Young, born
    1990). Young is drawn from N=5 and Father's generation-6 box from N=6, so for N=2 to
    6 a limited run that estimated from the drawn boxes alone would take Father's
    estimate from Root (born 1950): 1925, not living. The unlimited run gives 1965
    (Young), which is living, so his birthplace must stay hidden at every limit, in
    normal and large print alike, because the estimate always uses the unlimited plan.
    """
    tree = read_gedcom(FIX / "deep_collapse.ged")
    for generations in [1, 2, 3, 4, 5, 6, None]:
        for large_print in (False, True):
            pdf = render(
                tree,
                generations=generations,
                large_print=large_print,
                exclude_private=True,
            )
            label = (generations, large_print)
            assert b"Father DEEP" not in pdf, label
            assert b"(Living)" in pdf, label  # the occupied boxes remain
            assert b"Akron, Ohio" not in pdf, label


# ---------------------------------------------------------------- birth links only

SECRET = "Secret living birthplace"


def adoption(pedi="adopted", status=None, birth_family=True):
    """Kid (I1, born 1950) belongs to an adopted family F2: Adam I4 and Ada I5, who have
    no dates and no death record, only a birthplace. `pedi` is the PEDI under the kid's
    FAMC of F2 (none if empty). With `birth_family` the kid belongs to a birth family
    F1 first (Bob I2 and Beth I3, both dated), so that `--adoptive-parents` has a
    choice; without it F2 is the kid's only family.
    """
    csta = [] if status is None else ["2 CSTA @C1@"]
    lines = ["0 @I1@ INDI", "1 NAME Kid /KID/", "1 BIRT", "2 DATE 1950"] + (
        ["1 FAMC @F1@"] if birth_family else []
    )
    lines += ["1 FAMC @F2@"] + ([f"2 PEDI {pedi}"] if pedi else [])
    lines += [
        "0 @I2@ INDI",
        "1 NAME Bob /BIRTH/",
        "1 BIRT",
        "2 DATE 1920",
        "1 DEAT",
        "0 @I3@ INDI",
        "1 NAME Beth /BIRTH/",
        "1 BIRT",
        "2 DATE 1922",
        "1 DEAT",
        "0 @I4@ INDI",
        "1 NAME Adam /ADOPT/",
        "1 BIRT",
        f"2 PLAC {SECRET}",
        "0 @I5@ INDI",
        "1 NAME Ada /ADOPT/",
        "1 BIRT",
        "2 PLAC Secret wife birthplace",
        "0 @F1@ FAM",
        "1 HUSB @I2@",
        "1 WIFE @I3@",
        "1 CHIL @I1@",
        "0 @F2@ FAM",
        "1 HUSB @I4@",
        "1 WIFE @I5@",
        "1 CHIL @I1@",
    ] + csta
    if status is not None:
        lines += ["0 @C1@ CSTA", f"1 TEXT {status}"]
    return read_gedcom(ged(*lines))


def estimates(tree, root="I1", parents="birth"):
    """The privacy estimates of the whole pedigree, as render_pdf makes them (every
    generation, same parents).
    """
    return kincade.charts._birth_estimates(
        tree, plan_charts(tree, root, None, parents), 2026
    )


def secrets(tree, **opts):
    """The drawn places that are not for the public: every PLAC of the fixtures in this
    section holds 'ecret'.
    """
    return [
        t
        for t in drawn(render_charts(tree, exclude_private=True, **opts))
        if "ecret" in t
    ]


def chain(upper, lower):
    """Kid (I1, born 1950) - lower - Pat (I2, no dates) - upper - Gus (I3, no dates):
    `lower` is the PEDI of the kid's FAMC under F1 (Pat's family), `upper` that of Pat's
    FAMC under F2 (Gus's family); "" for none. Pat and Gus each have a birthplace.
    """

    def famc(fam, pedi):
        return [f"1 FAMC {fam}"] + ([f"2 PEDI {pedi}"] if pedi else [])

    return read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Kid /KID/",
            "1 BIRT",
            "2 DATE 1950",
            *famc("F1", lower),
            "0 @I2@ INDI",
            "1 NAME Pat /PARENT/",
            "1 BIRT",
            "2 PLAC Pat secret place",
            *famc("F2", upper),
            "0 @I3@ INDI",
            "1 NAME Gus /GRAND/",
            "1 BIRT",
            f"2 PLAC {SECRET}",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
            "0 @F2@ FAM",
            "1 HUSB @I3@",
            "1 CHIL @I2@",
        )
    )


def test_the_estimate_walks_birth_links_only():
    """The privacy estimate ages a birth parent from a dated descendant; an adopted,
    foster, step or other parent, and anyone reached only above such a link, gets no
    age from below it.
    """
    for parents in ("birth", "adoptive"):
        tree = adoption()
        charts = plan_charts(tree, "I1", None, parents)
        father = charts[0].slots[2]
        assert father == {"birth": "I2", "adoptive": "I4"}[parents], parents
        est = estimates(tree, parents=parents)
        if parents == "adoptive":
            assert "I4" not in est and "I5" not in est, parents  # not aged
            assert kincade.charts.living_checker(tree, charts, 2026)("I4") is True
            # without --exclude-private the place is drawn: this is about privacy,
            # not a missing line
            assert f"bp. {SECRET}" in drawn(render_charts(tree, parents="adoptive"))
        else:
            # Bob and Beth are drawn; both have their own recorded birth year
            assert est["I2"] == 1920 and est["I3"] == 1922, parents
        # no non-birth pedi lets a parent be aged, whatever the mode
        for pedi in ("adopted", "foster", "other"):
            non_birth_tree = adoption(pedi, birth_family=False)
            label = (parents, pedi)
            assert plan_charts(non_birth_tree, "I1", None, parents)[0].slots[2] == "I4"
            assert "I4" not in estimates(non_birth_tree, parents=parents), label
            assert secrets(non_birth_tree, parents=parents) == [], label
        # a step-parent is never drawn, so it is never aged either
        step_tree = adoption("step", birth_family=False)
        step_charts = plan_charts(step_tree, "I1", None, parents)
        assert step_charts[0].slots[2] is None, parents
        assert "I4" not in estimates(step_tree, parents=parents), parents
    # nothing above a non-birth link is aged from below it
    adopted_above = chain(upper="", lower="adopted")
    assert not {"I2", "I3"} & set(estimates(adopted_above))
    assert secrets(adopted_above) == []
    # a birth link below a non-birth link ages the parent but not the one above it
    fostered_above = chain(upper="foster", lower="")
    est = estimates(fostered_above)
    assert est["I2"] == 1925 and "I3" not in est


# ---------------------------------------------------------------- collapse and loops


def test_collapsed_pedigrees_and_loops():
    # a person reached twice in a collapsed pedigree keeps one consistent estimate
    collapse = read_gedcom(FIX / "collapse.ged")
    charts = plan_charts(collapse, "I1")
    assert charts[0].slots[4] == charts[0].slots[6] == "I4"
    assert charts[0].slots[8] == charts[0].slots[12] == "I8"
    est = kincade.charts._birth_estimates(collapse, charts, 2026)
    assert est["I4"] == 1930 and est["I8"] == 1900  # each person's own birth year

    # the estimate is the most conservative (latest) of every dated descendant path
    forked = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Cora /D/",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Ed /D/",
            "1 BIRT",
            "2 DATE 1960",
            "1 FAMC @F2@",
            "0 @I3@ INDI",
            "1 NAME Fay /D/",
            "1 BIRT",
            "2 DATE 1990",
            "1 FAMC @F3@",
            "0 @I4@ INDI",
            "1 NAME Lou /D/",  # undated, sits at positions 4 and 6
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 WIFE @I3@",
            "0 @F2@ FAM",
            "1 HUSB @I4@",
            "0 @F3@ FAM",
            "1 HUSB @I4@",
        )
    )
    forked_charts = plan_charts(forked, "I1")
    assert forked_charts[0].slots[4] == forked_charts[0].slots[6] == "I4"
    forked_est = kincade.charts._birth_estimates(forked, forked_charts, 2026)
    assert forked_est["I4"] == 1990 - 25  # the younger dated child wins

    tied = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME B /Z/",
            "1 BIRT",
            "2 DATE 1990",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME A /Z/",
            "1 BIRT",
            "2 DATE 1900",
            "1 FAMC @F2@",
            "0 @I4@ INDI",
            "1 NAME X /Z/",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "0 @F2@ FAM",
            "1 HUSB @I4@",
        )
    )
    tied_est = kincade.charts._birth_estimates(tied, plan_charts(tied, "I1"), 2026)
    assert tied_est["I2"] == 1900  # own birth year wins
    assert tied_est["I4"] == max(1900 - 25, 1990 - 2 * 25)

    # it survives a data loop
    cycle = read_gedcom(FIX / "cycle.ged")
    cycle_est = kincade.charts._birth_estimates(cycle, plan_charts(cycle, "I1"), 2026)
    assert cycle_est == {"I1": 1900, "I2": 1870}

    # no generation is added at a continuation boundary
    boundary = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME R /X/",
            "1 BIRT",
            "2 DATE 2000",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME F2 /X/",
            "1 FAMC @F2@",
            "0 @I4@ INDI",
            "1 NAME F4 /X/",
            "1 FAMC @F4@",
            "0 @I8@ INDI",
            "1 NAME F8 /X/",
            "1 FAMC @F8@",  # chart 1 position 8: roots chart 2
            "0 @I16@ INDI",
            "1 NAME F16 /X/",
            "1 FAMC @F16@",  # chart 2 position 2
            "0 @I32@ INDI",
            "1 NAME F32 /X/",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "0 @F2@ FAM",
            "1 HUSB @I4@",
            "0 @F4@ FAM",
            "1 HUSB @I8@",
            "0 @F8@ FAM",
            "1 HUSB @I16@",
            "0 @F16@ FAM",
            "1 HUSB @I32@",
        )
    )
    boundary_charts = plan_charts(boundary, "I1")
    assert boundary_charts[1].slots[1] == "I8" and boundary_charts[1].slots[2] == "I16"
    boundary_est = kincade.charts._birth_estimates(boundary, boundary_charts, 2026)
    assert boundary_est["I8"] == 2000 - 3 * 25
    # the continuation root IS the person at chart 1 position 8: no extra generation
    assert boundary_est["I16"] == 2000 - 4 * 25
    assert boundary_est["I32"] == 2000 - 5 * 25


# ---------------------------------------------------------------- dates and events


@pytest.mark.parametrize(
    "label,dad_date,kid_date,dad_extra,christening,hidden",
    [
        ("open AFT bounded by a later child", "AFT 1735", "1800", (), None, False),
        ("open AFT within the last century", "AFT 1900", "2000", (), None, True),
        (
            "an unreadable calendar, whatever the child says",
            "@#DHEBREW@ 5650",
            "1800",
            (),
            None,
            True,
        ),
        ("a christening alone bounds a missing birth", "", "1950", (), "1800", False),
        (
            "a recorded unreadable birth outranks a christening",
            "HEBREW 5650",
            "1950",
            (),
            "1800",
            True,
        ),
        ("a burial alone means not living", "", "1950", ("1 BURI",), None, False),
        (
            "no dates, with a kid on an unreadable date",
            "",
            "@#DHEBREW@ 5650",
            (),
            None,
            True,
        ),
        (
            "a death record wins over a recent birth",
            "1990",
            "1950",
            ("1 DEAT Y",),
            None,
            False,
        ),
    ],
    ids=lambda v: v if isinstance(v, str) and len(v) < 40 else None,
)
def test_the_estimate_from_dates_and_events(
    label, dad_date, kid_date, dad_extra, christening, hidden
):
    tree = dad_and_kid(dad_date, *dad_extra, kid=kid_date, christening=christening)
    assert secret_shown(tree) == (not hidden), label


# ---------------------------------------------------------------- Person.living overrides


def with_living(tree, **verdicts):
    """The tree with Person.living set: with_living(tree, I1=True, I2=None) for I1 and
    I2.
    """
    for name, verdict in verdicts.items():
        tree.people[name].living = verdict
    return tree


PREDICATE_GED = ged(
    "0 @I1@ INDI",
    "1 NAME Ann /Pell/",
    "1 BIRT",
    "2 DATE 1990",
    "1 FAMC @F1@",  # young: the heuristic says living
    "0 @I2@ INDI",
    "1 NAME Bob /Pell/",
    "1 BIRT",
    "2 DATE 1800",
    "1 DEAT",
    "2 DATE 1870",
    "1 FAMS @F1@",
    "0 @F1@ FAM",
    "1 HUSB @I2@",
    "1 MARR",
    "2 DATE 1820",
    "2 PLAC Dayton",
)


def test_person_living_overrides_the_estimate():
    # the caller marks the deceased-looking Bob as living and the young Ann as not
    # living: the opposite of what the built-in heuristic would say
    tree = with_living(read_gedcom(PREDICATE_GED), I1=False, I2=True)
    pdf = render_pdf(
        plan_charts(tree, "I1"),
        tree,
        Options(today=TODAY, fonts="base14", compress=False, exclude_private=True),
    )
    text = drawn(pdf)
    # Bob's birth, death, and marriage (a living spouse) must not be drawn.
    for value in ("1800", "1870", "1820", "Dayton"):
        assert all(value not in line for line in text), value
    assert "b. 1990" in text and "PELL, Ann (b. 1990), 1-1" in text
    assert "Ann PELL" in text and "Bob PELL" not in text
    assert "Living" in text
    assert not any("PELL, Bob" in line for line in text)  # omitted from the index
    assert "b." in text and "m." in text  # labels stay

    # it also decides the index order and index years
    order_tree = with_living(
        read_gedcom(
            ged(
                "0 @I1@ INDI",
                "1 NAME Root /Zed/",
                "1 FAMC @F1@",
                "0 @I2@ INDI",
                "1 NAME Al /Smith/",
                "1 BIRT",
                "2 DATE 1800",  # heuristic: not living, sorts first
                "0 @I3@ INDI",
                "1 NAME Al /Smith/",
                "1 BIRT",
                "2 DATE 1990",  # heuristic: living, years hidden
                "0 @F1@ FAM",
                "1 HUSB @I2@",
                "1 WIFE @I3@",
            )
        ),
        I1=False,
        I2=True,
        I3=False,
    )
    order_pdf = render_pdf(
        plan_charts(order_tree, "I1"),
        order_tree,
        Options(today=TODAY, fonts="base14", compress=False, exclude_private=True),
    )
    # the caller's verdict omits the 1800 man and includes the 1990 man
    assert b"(SMITH, Al \\(b. 1990\\), 1-3)" in order_pdf
    assert b"1800" not in order_pdf  # the living man's birth year never appears
    assert b"1-2" not in order_pdf  # the living man's own box has no index entry

    # it is ignored when not private
    public_tree = with_living(read_gedcom(PREDICATE_GED), I1=True, I2=True)
    public_pdf = render_pdf(
        plan_charts(public_tree, "I1"),
        public_tree,
        Options(today=TODAY, fonts="base14", compress=False, exclude_private=False),
    )
    assert b"(b. 1800)" in public_pdf and b"(m. 1820)" in public_pdf
    assert b"(b. 1990)" in public_pdf

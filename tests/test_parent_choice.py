"""Parent choice. A child's relationship to each parent family it belongs to is read
from the PEDI under the INDI's FAMC (GEDCOM 5.5.1/7: birth, adopted, foster, sealing,
other, any case; step and stepchild too, which Gramps writes and no standard defines).
It is one of birth, adopted, foster, step, other, kept per parent (ParentLink.father and
.mother; a PEDI gives the same to both), and unmarked or unknown is birth.
tests/test_parent_tags.py covers the other tags (_FREL, _MREL, the ADOP event). A
non-standard CSTA child status (`2 CSTA @C1@` under a CHIL, `0 @C1@ CSTA` / `1 TEXT
Adopted`) is not read: a file that records adoption that way shows the child as a birth
child. Without a flag (adoptive_parents=False in the library) the first birth family is
drawn, else the first family; `--adoptive-parents` (adoptive_parents=True) draws an
adopted family first, then a foster one, then a birth family, else the first. When a
parent drawn is adopted or foster, the child's name line ends with a short note from the
language's [relationship] table; birth and other parents get none. Planning, privacy
estimates, marriage lines and the index all follow the same choice.

Synthetic fixtures only.
"""

import pytest

import kincade.charts
import kincade.cli
import kincade.gedcom
import kincade.lang
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom
from kincade.model import ParentLink
from kincade.pdf import Options

from conftest import (
    ADA,
    ADAM,
    BEA,
    BERT,
    KID,
    ged,
    indi,
    kid_tree,
    parents_of,
    render_charts,
)
from pdfread import drawn, runs

# Adam+Ada (married 1950), Bert+Bea (1960), Carl+Cora (1970)
F1, F2, F3 = "F1", "F2", "F3"


# ---------------------------------------------------------------- choosing the parents


def test_birth_is_the_default_and_beats_an_adopted_family_listed_first():
    tree = kid_tree([(F1, "adopted"), (F2, "")])
    assert parents_of(tree) == (BERT, BEA)
    assert tree.parent_family(KID).id == F2


def test_adoptive_prefers_the_adopted_family_whatever_the_order():
    for famc in ([(F1, "adopted"), (F2, "")], [(F2, ""), (F1, "adopted")]):
        assert parents_of(kid_tree(famc), prefer="adoptive") == (ADAM, ADA)


def test_adoptive_prefers_adopted_then_foster_then_birth_then_the_first():
    both = kid_tree([(F2, ""), (F3, "foster"), (F1, "adopted")])
    assert both.parent_family(KID, "adoptive").id == F1
    no_adopted = kid_tree([(F2, ""), (F3, "foster")])
    assert no_adopted.parent_family(KID, "adoptive").id == F3
    only_birth = kid_tree([(F1, "other"), (F2, "")])
    assert only_birth.parent_family(KID, "adoptive").id == F2
    neither = kid_tree([(F1, "other"), (F3, "sealing")])
    assert neither.parent_family(KID, "adoptive").id == F1  # the first family


def test_with_no_birth_family_the_first_family_is_used():
    tree = kid_tree([(F1, "adopted"), (F3, "foster")])
    assert tree.parent_family(KID).id == F1
    assert kid_tree([(F3, "foster"), (F1, "adopted")]).parent_family(KID).id == F3


def test_unmarked_families_choose_the_first_in_both_modes():
    tree = kid_tree([(F2, ""), (F1, "")])
    assert (
        tree.parent_family(KID).id == F2
        and tree.parent_family(KID, "adoptive").id == F2
    )


def test_a_family_missing_from_the_file_is_skipped():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 FAMC @F404@",
            "1 FAMC @F1@",
            "2 PEDI adopted",
            "0 @F1@ FAM",
            "1 CHIL @I1@",
        )
    )
    assert tree.parent_family("I1").id == "F1"


def test_the_relationship_of_the_chosen_family():
    tree = kid_tree([(F1, "adopted"), (F2, "")])
    assert tree.parent_relationship(KID) == "birth"
    assert tree.parent_relationship(KID, "adoptive") == "adopted"
    assert tree.parent_relationship(BERT) == "birth"  # no parents at all


# ---------------------------------------------------------------- planning


def test_plan_charts_follows_the_chosen_parents():
    tree = kid_tree([(F1, "adopted"), (F2, "")], parents_of=[("F9", "")])
    birth = plan_charts(tree, KID)
    adoptive = plan_charts(tree, KID, parents="adoptive")
    assert (birth[0].slots[2], birth[0].slots[3]) == (BERT, BEA)
    assert (adoptive[0].slots[2], adoptive[0].slots[3]) == (ADAM, ADA)
    # Adam's own parents, through the adoptive father
    assert (adoptive[0].slots[4], adoptive[0].slots[5]) == ("I8", "I9")
    assert birth[0].slots[4] is None


def test_charts_and_options_must_agree_on_the_parents():
    tree = kid_tree([(F1, "adopted"), (F2, "")])
    adoptive, birth = plan_charts(tree, KID, parents="adoptive"), plan_charts(tree, KID)
    with pytest.raises(ValueError, match="adoptive_parents"):
        kincade.pdf.render_pdf(adoptive, tree, Options())
    with pytest.raises(ValueError, match="adoptive_parents"):
        kincade.pdf.render_pdf(birth, tree, Options(adoptive_parents=True))
    assert kincade.pdf.render_pdf(adoptive, tree, Options(adoptive_parents=True))


def test_a_continuation_chart_uses_the_mode_too():
    # R <- A <- B <- C (box 8, adopted by FC2 = E+F; born to FC1 = G+H)
    lines = []
    for xref, name, famc in (
        ("R", "Root", [("FR", "")]),
        ("A", "Aa", [("FA", "")]),
        ("B", "Bb", [("FB", "")]),
        ("C", "Cc", [("FC1", ""), ("FC2", "adopted")]),
        ("G", "Gg", []),
        ("H", "Hh", []),
        ("E", "Ee", []),
        ("F", "Ff", []),
    ):
        lines += indi(xref, f"{name} /X/", famc)
    for fam, husb, wife, child in (
        ("FR", "A", None, "R"),
        ("FA", "B", None, "A"),
        ("FB", "C", None, "B"),
        ("FC1", "G", "H", "C"),
        ("FC2", "E", "F", "C"),
    ):
        lines += (
            [f"0 @{fam}@ FAM", f"1 HUSB @{husb}@"]
            + ([f"1 WIFE @{wife}@"] if wife else [])
            + [f"1 CHIL @{child}@"]
        )
    tree = read_gedcom(ged(*lines))
    birth, adoptive = plan_charts(tree, "R"), plan_charts(tree, "R", parents="adoptive")
    assert len(birth) == len(adoptive) == 2
    assert (
        birth[0].slots[8] == "C"
        and birth[1].slots[2] == "G"
        and birth[1].slots[3] == "H"
    )
    assert adoptive[1].slots[2] == "E" and adoptive[1].slots[3] == "F"


def test_an_unknown_mode_is_a_value_error():
    tree = kid_tree([(F1, "")])
    with pytest.raises(ValueError):
        plan_charts(tree, KID, parents="stepwise")
    with pytest.raises(ValueError):
        tree.parent_family(KID, "stepwise")


# ----------------------------------------------------------------
# the note on the child's name line


def test_an_adopted_child_gets_the_note_after_the_name():
    tree = kid_tree([(F1, "adopted")])  # the only family: the default mode uses it
    assert "Kid KID (adopted)" in drawn(render_charts(tree))


def test_no_note_when_the_chosen_family_is_a_birth_family():
    tree = kid_tree([(F1, "adopted"), (F2, "")])
    text = drawn(render_charts(tree))
    assert "Kid KID" in text and not any("(" in t and "KID" in t for t in text)


def test_the_note_follows_the_chosen_family():
    tree = kid_tree([(F1, "adopted"), (F2, "")])
    assert "Kid KID (adopted)" in drawn(render_charts(tree, parents="adoptive"))
    assert "Kid KID (adopted)" not in drawn(render_charts(tree))


@pytest.mark.parametrize(
    "pedi,note", [("adopted", "(adopted)"), ("foster", "(foster)")]
)
def test_each_relationship_has_its_own_note(pedi, note):
    assert f"Kid KID {note}" in drawn(render_charts(kid_tree([(F1, pedi)])))


def test_a_drawn_other_parent_gets_no_note_in_the_pdf_like_a_birth_parent():
    for pedi in ("other", "sealing"):  # sealing reads as other
        text = drawn(render_charts(kid_tree([(F1, pedi)])))
        assert "Kid KID" in text and not any("(" in t and "KID" in t for t in text)


def stepchild():
    """Kid as a stepchild of both parents of F1, which no PEDI can say: a tree edited
    in code.
    """
    tree = kid_tree([(F1, "")])
    tree.people[KID].parents = [ParentLink(F1, "step", "step")]
    return tree


def test_a_step_child_gets_no_note_and_no_step_parents_in_the_boxes():
    text = drawn(render_charts(stepchild()))
    assert "Kid KID" in text  # no note
    # Adam and Ada are not drawn
    assert not [t for t in text if "(" in t] and not [t for t in text if "ONE" in t]


def test_an_ancestor_whose_own_parents_are_not_birth_parents_gets_the_note():
    # Adam is not a birth child of Zed and Zoe
    tree = kid_tree([(F1, "")], parents_of=[("F9", "foster")])
    text = drawn(render_charts(tree, generations=3))
    assert "Adam ONE (foster)" in text and "Kid KID" in text and "Ada ONE" in text


def test_the_note_is_in_the_languages_relationship_table():
    # other and step give no note, so they are not in the table
    assert kincade.lang.DEFAULT_STRINGS["relationship"] == {
        "adopted": "(adopted)",
        "foster": "(foster)",
    }
    assert kincade.lang.load_strings("de")["relationship"] == {
        "adopted": "(adoptiert)",
        "foster": "(Pflegekind)",
    }
    for key in ("adopted", "foster"):
        assert kincade.lang.PLACEHOLDERS[f"relationship.{key}"] == ()
    assert "relationship.step" not in kincade.lang.PLACEHOLDERS
    assert "relationship.other" not in kincade.lang.PLACEHOLDERS


def test_the_german_notes_are_drawn_for_a_german_pdf():
    assert "Kid KID (adoptiert)" in drawn(
        render_charts(kid_tree([(F1, "adopted")]), lang="de")
    )
    assert "Kid KID (Pflegekind)" in drawn(
        render_charts(kid_tree([(F1, "foster")]), lang="de")
    )


def test_a_note_can_be_reworded_through_the_strings():
    strings = {"relationship": {"adopted": "[adopt.]"}}
    assert "Kid KID [adopt.]" in drawn(
        render_charts(kid_tree([(F1, "adopted")]), lang=strings)
    )


def test_a_note_with_a_placeholder_is_a_langerror(tmp_path):
    path = tmp_path / "x.toml"
    path.write_text('[relationship]\nadopted = "({n})"\n', encoding="utf-8")
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(str(path))
    assert "relationship.adopted" in str(e.value)


def test_a_living_childs_note_is_hidden_under_private():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Young /KID/",
            "1 BIRT",
            "2 DATE 1 JAN 2005",
            "1 FAMC @F1@",
            "2 PEDI adopted",
            "0 @I2@ INDI",
            "1 NAME Dad /KID/",
            "1 BIRT",
            "2 DATE 1 JAN 1850",
            "1 DEAT",
            "2 DATE 1 JAN 1900",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
        )
    )
    shown = drawn(render_charts(tree, root="I1"))
    hidden = drawn(render_charts(tree, root="I1", exclude_private=True))
    assert "Young KID (adopted)" in shown
    # Living people keep their position with no name or relationship note.
    assert "Living" in hidden and "Young KID" not in hidden
    assert not any("(adopted)" in line for line in hidden)


# ----------------------------------------------------------------
# the note, the ID and the name fit together


def long_named_adoptee():
    long_name = (
        "Alexandrina Wilhelmina Fredericka Charlotte Josephine Maximiliana Christabella"
    )
    return read_gedcom(
        ged(
            "0 @I1@ INDI",
            f"1 NAME {long_name} /VANDERBILT/",
            "1 FAMC @F1@",
            "2 PEDI adopted",
            "0 @F1@ FAM",
            "1 CHIL @I1@",
        )
    )


def test_a_long_name_is_cut_before_the_note_and_the_whole_line_fits():
    pdf = render_charts(long_named_adoptee(), generations=1)
    name = next(r for r in runs(pdf) if r.text.startswith("Alexandrina"))
    # the name gives way; the note stays
    assert name.text.endswith("(adopted)") and "…" in name.text
    assert (
        name.right()
        <= kincade.pdf.BOX_X0[1]
        + kincade.pdf.TEXT_INSET_LEFT
        + kincade.pdf.TEXT_WIDTH
        + 0.01
    )
    assert name.scale >= 0.5


def test_the_name_fit_includes_the_note_and_the_id():
    pdf = render_charts(long_named_adoptee(), generations=1, show_ids=True)
    name = next(r for r in runs(pdf) if r.text.startswith("Alexandrina"))
    x_id = next(r for r in runs(pdf) if r.text == "[I1]").x
    assert name.text.endswith("(adopted)")
    assert name.right() <= x_id - 6 + 0.01  # at least 6 pt clear of the ID
    assert name.y == pytest.approx(
        kincade.pdf.LETTER.box_top[1] - 5 + kincade.pdf.NAME_BASE
    )


def test_a_short_name_with_a_note_is_drawn_whole_at_full_width():
    pdf = render_charts(kid_tree([(F1, "adopted")]), generations=1)
    name = next(r for r in runs(pdf) if r.text.startswith("Kid"))
    assert name.text == "Kid KID (adopted)" and name.scale == pytest.approx(1.0)


def test_fitting_a_name_without_a_note_is_the_plain_squeeze():
    assert kincade.pdf.fit_squeezed_noted(
        "Anna SMITH", "", "Helvetica", 9, 40
    ) == kincade.pdf.fit_squeezed("Anna SMITH", "Helvetica", 9, 40)
    assert kincade.pdf.fit_squeezed_noted("Anna SMITH", "", "Helvetica", 9, 100) == (
        "Anna SMITH",
        1.0,
    )


def test_a_name_and_note_that_fit_are_drawn_whole_and_a_tight_fit_is_squeezed():
    text, scale = kincade.pdf.fit_squeezed_noted(
        "Anna SMITH", "(adopted)", "Helvetica", 9, 200
    )
    assert text == "Anna SMITH (adopted)" and scale == 1.0
    wide = kincade.pdf.text_width("Anna SMITH (adopted)", "Helvetica", 9)
    text, scale = kincade.pdf.fit_squeezed_noted(
        "Anna SMITH", "(adopted)", "Helvetica", 9, wide * 0.96
    )
    # condensed, nothing cut
    assert text == "Anna SMITH (adopted)" and 0.93 <= scale < 1.0


def test_a_name_that_must_be_cut_is_cut_before_the_note():
    text, scale = kincade.pdf.fit_squeezed_noted(
        "A" * 60, "(adopted)", "Helvetica", 9, 100
    )
    assert text.endswith("… (adopted)") and text.startswith("AAA")
    assert (
        kincade.pdf.text_width(text, "Helvetica", 9) * scale <= 100 + 1e-6
        and scale >= 0.5
    )


def test_when_the_note_leaves_no_room_for_the_name_the_whole_line_is_cut():
    text, scale = kincade.pdf.fit_squeezed_noted("Anna", "x" * 100, "Helvetica", 9, 50)
    assert kincade.pdf.text_width(
        text, "Helvetica", 9
    ) * scale <= 50 + 1e-6 and text.endswith("…")


# ----------------------------------------------------------------
# everything follows the choice


def test_the_fathers_marriage_line_is_the_chosen_familys():
    tree = kid_tree([(F1, "adopted"), (F2, "")])
    birth, adoptive = (
        drawn(render_charts(tree, generations=2)),
        drawn(render_charts(tree, generations=2, parents="adoptive")),
    )
    assert "m. 1960" in birth and "m. 1950" not in birth  # Bert and Bea married in 1960
    assert "m. 1950" in adoptive and "m. 1960" not in adoptive


def test_the_index_lists_the_chosen_parents():
    tree = kid_tree([(F1, "adopted"), (F2, "")])

    def lines(prefer):
        return kincade.pdf.build_index(
            tree,
            plan_charts(tree, KID, 2, prefer),
            lambda pid: False,
            exclude_private=False,
        )

    assert [line.split(",")[0] for line in lines("birth")] == ["KID", "TWO", "TWO"]
    assert [line.split(",")[0] for line in lines("adoptive")] == ["KID", "ONE", "ONE"]


def test_the_privacy_estimate_walks_the_chosen_pedigree():
    # Kid (adopted by Adam, born to Bert). Adam's father Zed has a place but
    # no dates: only through Adam (b. 1850) can his birth be estimated (1825,
    # not living). Under the wrong pedigree he would count as possibly living.
    lines = [
        "0 @I1@ INDI",
        "1 NAME Kid /KID/",
        "1 FAMC @F1@",
        "2 PEDI adopted",
        "1 FAMC @F2@",
        "0 @I2@ INDI",
        "1 NAME Adam /ONE/",
        "1 BIRT",
        "2 DATE 1 JAN 1850",
        "1 FAMC @F9@",
        "0 @I4@ INDI",
        "1 NAME Bert /TWO/",
        "1 BIRT",
        "2 DATE 1 JAN 1840",
        "0 @I8@ INDI",
        "1 NAME Zed /NINE/",
        "1 BIRT",
        "2 PLAC Oslo, Norway",
        "0 @F1@ FAM",
        "1 HUSB @I2@",
        "1 CHIL @I1@",
        "0 @F2@ FAM",
        "1 HUSB @I4@",
        "1 CHIL @I1@",
        "0 @F9@ FAM",
        "1 HUSB @I8@",
        "1 CHIL @I2@",
    ]
    tree = read_gedcom(ged(*lines))
    text = drawn(render_charts(tree, exclude_private=True, parents="adoptive"))
    # Zed: estimated from Adam, so not living, so shown
    assert "bp. Oslo, Norway" in text
    only_birth = drawn(render_charts(tree, exclude_private=True))
    assert "Zed NINE" not in only_birth  # not in the pedigree at all


# ----------------------------------------------------------------
# command line and config


def test_the_cli_draws_the_adoptive_parents(tmp_path, drawn_charts):
    gedfile = tmp_path / "t.ged"
    tree_lines = (
        ["0 HEAD"]
        + indi(KID, "Kid /KID/", [(F1, "adopted"), (F2, "")])
        + indi(ADAM, "Adam /ONE/")
    )
    tree_lines += indi(BERT, "Bert /TWO/") + [
        f"0 @{F1}@ FAM",
        f"1 HUSB @{ADAM}@",
        f"1 CHIL @{KID}@",
        f"0 @{F2}@ FAM",
        f"1 HUSB @{BERT}@",
        f"1 CHIL @{KID}@",
    ]
    gedfile.write_bytes(ged(*tree_lines))
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [str(gedfile), "--root", KID, "--adoptive-parents", "-o", str(out)]
        )
        == 0
    )
    charts, opts = drawn_charts[-1]
    assert opts.parents == "adoptive" and charts[0].slots[2] == ADAM
    assert kincade.cli.main([str(gedfile), "--root", KID, "-o", str(out)]) == 0
    charts, opts = drawn_charts[-1]
    assert opts.parents == "birth" and charts[0].slots[2] == BERT


def test_a_bad_adoptive_parents_value_in_the_config_names_the_key(tmp_path, capsys):
    (tmp_path / "kincade.toml").write_text(
        'adoptive_parents = "adoptive"\n', encoding="utf-8"
    )
    assert kincade.cli.main(["--show-config"]) == 2
    err = capsys.readouterr().err
    assert "adoptive_parents" in err and "true or false" in err

"""The initial pedigree root pairs one spouse with the chosen marriage."""

from dataclasses import replace
from itertools import combinations

import pytest
from reportlab import rl_config

import kincade.cli
from kincade import Event, Family, Options, Person, Tree, read_gedcom, render_blank
from kincade.charts import plan_charts
from kincade.pdf import page_geom, render_pdf

from conftest import PAPERS, PRINTS, TODAY, full_pedigree, ged, render
from pdfread import drawn as drawn_runs
from pdfread import ink_box, overlaps, pages, rectangles, streams


def joined_rows(pieces):
    """Join the label and value runs of mixed-font spouse rows."""
    rows = []
    for piece in pieces:
        if rows and rows[-1].endswith(" "):
            rows[-1] += piece
        else:
            rows.append(piece)
    return rows


def drawn(pdf):
    return joined_rows(drawn_runs(pdf))


@pytest.fixture
def marriages():
    return read_gedcom(
        ged(
            "0 @R@ INDI",
            "1 NAME Root /vanDyke/",
            "1 DEAT Y",
            "1 FAMS @F1@",
            "1 FAMS @F2@",
            "1 FAMC @FP@",
            "0 @S1@ INDI",
            "1 NAME First /McClure/",
            "1 DEAT Y",
            "0 @S2@ INDI",
            "1 NAME Ada /deVries/",
            "1 DEAT Y",
            "0 @P@ INDI",
            "1 NAME Parent /Line/",
            "1 DEAT Y",
            "1 FAMC @FA@",
            "0 @A@ INDI",
            "1 NAME Ancestor /Line/",
            "1 DEAT Y",
            "1 FAMC @FB@",
            "0 @B@ INDI",
            "1 NAME Continued /Line/",
            "1 DEAT Y",
            "1 FAMC @FC@",
            "0 @C@ INDI",
            "1 NAME Earlier /Line/",
            "1 DEAT Y",
            "0 @F1@ FAM",
            "1 HUSB @R@",
            "1 WIFE @S1@",
            "1 MARR",
            "2 DATE 1925",
            "2 PLAC First Town",
            "0 @F2@ FAM",
            "1 HUSB @R@",
            "1 WIFE @S2@",
            "1 MARR",
            "2 DATE 1935",
            "2 PLAC Other Town",
            "0 @FP@ FAM",
            "1 HUSB @P@",
            "1 CHIL @R@",
            "1 MARR",
            "2 DATE 1890",
            "0 @FA@ FAM",
            "1 HUSB @A@",
            "1 CHIL @P@",
            "1 MARR",
            "2 DATE 1860",
            "0 @FB@ FAM",
            "1 HUSB @B@",
            "1 CHIL @A@",
            "1 MARR",
            "2 DATE 1830",
            "0 @FC@ FAM",
            "1 HUSB @C@",
            "1 CHIL @B@",
            "1 MARR",
            "2 DATE 1800",
        )
    )


def test_default_root_shows_first_spouse_and_matching_marriage(marriages):
    text = drawn(render(marriages, "R"))
    assert "spouse: First McCLURE" in text
    assert "m. 1925" in text and "mp. First Town" in text
    assert "spouse: Ada DEVRIES" not in text and "m. 1935" not in text


@pytest.mark.parametrize("selector", ["F2", "@F2@", " f2 "])
def test_override_switches_spouse_and_marriage_together(marriages, selector):
    text = drawn(render(marriages, "R", root_family=selector))
    assert "spouse: Ada DEVRIES" in text
    assert "m. 1935" in text and "mp. Other Town" in text
    assert "spouse: First McCLURE" not in text and "m. 1925" not in text


def test_mother_role_root_uses_the_other_partner(marriages):
    family = marriages.families["F2"]
    family.father, family.mother = family.mother, family.father
    assert "spouse: Ada DEVRIES" in drawn(render(marriages, "R", root_family="F2"))


@pytest.mark.parametrize("selector", ["missing", "FP", "", 42])
@pytest.mark.parametrize("planned", [False, True])
def test_invalid_override_is_a_clean_api_error(marriages, selector, planned):
    options = Options(root_family=selector)
    with pytest.raises(ValueError, match="root_family"):
        if planned:
            render_pdf(plan_charts(marriages, "R"), marriages, options)
        else:
            render(marriages, "R", root_family=selector)


def test_an_unrelated_family_referenced_by_corrupt_fams_is_rejected(marriages):
    marriages.people["R"].families.append("FP")
    with pytest.raises(ValueError, match="root_family"):
        render(marriages, "R", root_family="FP")


def test_actual_partner_role_accepts_missing_reciprocal_fams(marriages):
    marriages.people["R"].families.remove("F2")
    assert "spouse: Ada DEVRIES" in drawn(render(marriages, "R", root_family="F2"))


@pytest.mark.parametrize(
    "missing", ["family", "spouse_id", "spouse_record", "spouse_name", "marriage"]
)
def test_absent_root_family_fields_remain_drawable(marriages, missing):
    if missing == "family":
        del marriages.families["F1"]
    elif missing == "spouse_id":
        marriages.families["F1"].mother = ""
    elif missing == "spouse_record":
        del marriages.people["S1"]
    elif missing == "spouse_name":
        marriages.people["S1"].given = marriages.people["S1"].surname = ""
    else:
        marriages.families["F1"].marriage = None
    text = drawn(render(marriages, "R"))
    assert ("spouse: First McCLURE" if missing == "marriage" else "spouse:") in text
    assert ("m." if missing in ("family", "marriage") else "m. 1925") in text
    assert "spouse: Ada DEVRIES" not in text  # never skip a missing first FAMS


def test_root_with_no_spouse_family_has_an_empty_spouse_line():
    assert "spouse:" in drawn(render(Tree(people={"R": Person("R")}), "R"))


@pytest.mark.parametrize(
    "root_living, spouse_living",
    [(False, False), (False, True), (True, False), (True, True)],
)
def test_privacy_redacts_spouse_name_and_both_marriage_values(
    marriages, root_living, spouse_living
):
    marriages.people["R"].living = root_living
    marriages.people["S2"].living = spouse_living
    text = drawn(
        render(
            marriages,
            "R",
            root_family="F2",
            exclude_private=True,
            lang={"living_name": "Private"},
        )
    )
    assert ("spouse: Private" if spouse_living else "spouse: Ada DEVRIES") in text
    if root_living or spouse_living:
        assert "m. 1935" not in text and "mp. Other Town" not in text
    else:
        assert "m. 1935" in text and "mp. Other Town" in text


def test_spouse_privacy_estimate_applies_outside_ancestor_slots(marriages):
    marriages.people["S2"].death = None
    text = drawn(render(marriages, "R", root_family="F2", exclude_private=True))
    assert "spouse: Living" in text and "m. 1935" not in text


def test_private_status_does_not_hide_spouse_without_privacy(marriages):
    marriages.people["S2"].living = True
    text = drawn(render(marriages, "R", root_family="F2"))
    assert "spouse: Ada DEVRIES" in text and "m. 1935" in text


def test_spouse_uses_recorded_case_and_custom_language(marriages):
    text = drawn(
        render(
            marriages, "R", preserve_case=True, lang={"labels": {"spouse": "partner:"}}
        )
    )
    assert "partner: First McClure" in text


def test_spouse_label_is_translated_in_german(marriages):
    assert "Ehe mit: First McCLURE" in drawn(render(marriages, "R", lang="de"))


def test_override_leaves_continuations_ancestors_and_index_membership_unchanged(
    marriages,
):
    default, selected = render(marriages, "R"), render(marriages, "R", root_family="F2")
    assert streams(default)[1:] == streams(selected)[1:]
    first_default, first_selected = pages(default)[0], pages(selected)[0]
    changed = {
        "First McCLURE",
        "Ada DEVRIES",
        "m. 1925",
        "m. 1935",
        "mp. First Town",
        "mp. Other Town",
    }
    assert [r for r in first_default if r.text not in changed] == [
        r for r in first_selected if r.text not in changed
    ]
    index = [r.text for r in pages(selected)[-1]]
    assert not any("McCLURE" in t or "DEVRIES" in t for t in index)
    assert sum(t.startswith("spouse:") for t in drawn(selected)) == 1


@pytest.mark.parametrize(
    "default_country, selected_country, ancestor_line",
    [
        ("USA", "UK", "bp. Springfield, …, Northern Missouri, Western Region"),
        ("UK", "USA", "bp. Springfield, …, Western Region, USA"),
    ],
)
@pytest.mark.parametrize("private_spouse", [False, True])
def test_override_keeps_country_plurality_and_unchanged_ancestor_places(
    marriages, default_country, selected_country, ancestor_line, private_spouse
):
    # B occurs on the initial page and as a continuation root. The two USA
    # occurrences plus the first marriage give a plurality; choosing a UK
    # marriage would create a tie with the root's UK birth if counted globally.
    marriages.people["R"].birth = Event(place="Town, UK")
    marriages.people["B"].birth = Event(
        place="Springfield, Greene County, Northern Missouri, Western Region, USA"
    )
    marriages.families["F1"].marriage.place = f"Town, {default_country}"
    marriages.families["F2"].marriage.place = f"Town, {selected_country}"
    marriages.people["S2"].living = private_spouse
    default = render(marriages, "R", exclude_private=private_spouse)
    selected = render(marriages, "R", root_family="F2", exclude_private=private_spouse)
    assert drawn(default).count(ancestor_line) == 2
    assert drawn(selected).count(ancestor_line) == 2
    assert streams(selected)[1:] == streams(default)[1:]
    first = joined_rows(r.text for r in pages(selected)[0])
    assert ("spouse: Living" if private_spouse else "spouse: Ada DEVRIES") in first
    assert ("mp." if private_spouse else f"mp. Town, {selected_country}") in first


@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("large_print", PRINTS)
@pytest.mark.parametrize("shadow", [False, True])
def test_only_initial_root_is_centered_between_neighboring_boxes_without_overlap(
    paper, large_print, shadow
):
    tree = full_pedigree(5)
    tree.people["I1"].families = ["union"]
    tree.people["spouse"] = Person("spouse", given="W" * 250, surname="Long")
    tree.families["union"] = Family("union", "I1", "spouse", Event())
    pdf = render(tree, large_print=large_print, paper=paper, shadow=shadow)
    geom = page_geom(paper, large_print, shadow)
    boxes = rectangles(pdf, "B*")
    root = boxes[0]
    assert root[3] == pytest.approx(88 * geom.scale, abs=0.01)
    above, below = (2, 3) if large_print else (5, 6)
    assert root[1] + root[3] / 2 == pytest.approx(
        (geom.box_top[above] + geom.h(above) + geom.box_top[below]) / 2, abs=0.01
    )
    for pos, box in enumerate(boxes[1:], 2):
        assert box == pytest.approx(
            (geom.box_x0[pos], geom.box_top[pos], geom.box_w, geom.h(pos)), abs=0.01
        )
    for a, b in combinations(boxes, 2):
        assert not overlaps(a, b)
    for i, layer in enumerate(rectangles(pdf, "f*")):
        owner = i // 3
        for j, box in enumerate(boxes):
            if j != owner:
                assert not overlaps(layer, box)
    spouse = next(r for r in pages(pdf)[0] if r.text.startswith("spouse:"))
    assert ink_box(spouse)[1] > root[1]
    assert ink_box(spouse)[1] + ink_box(spouse)[3] < root[1] + root[3]
    spouse_name = next(r for r in pages(pdf)[0] if r.y == spouse.y and r.x > spouse.x)
    assert spouse_name.right() <= root[0] + root[2] - geom.inset_right + 0.01
    assert ink_box(spouse_name)[1] + ink_box(spouse_name)[3] < root[1] + root[3]
    assert rectangles(pdf, "B*", 1)[0][3] == pytest.approx(78 * geom.scale, abs=0.01)


def test_blank_ignores_root_family_and_includes_empty_spouse_line(monkeypatch):
    monkeypatch.setattr(rl_config, "invariant", 1)
    opts = Options(fonts="base14", compress=False, today=TODAY)
    assert render_blank(opts) == render_blank(replace(opts, root_family="missing"))
    assert "spouse:" in drawn(render_blank(opts))
    assert rectangles(render_blank(opts), "B*")[0][3] == 88


ROOT_GED = ged(
    "0 @R@ INDI",
    "1 NAME Root /Family/",
    "1 FAMS @F1@",
    "1 FAMS @F2@",
    "0 @S1@ INDI",
    "1 NAME First /Spouse/",
    "0 @S2@ INDI",
    "1 NAME Second /Spouse/",
    "0 @F1@ FAM",
    "1 HUSB @R@",
    "1 WIFE @S1@",
    "1 MARR",
    "2 DATE 1925",
    "0 @F2@ FAM",
    "1 HUSB @R@",
    "1 WIFE @S2@",
    "1 MARR",
    "2 DATE 1935",
    "0 @OTHER@ FAM",
    "1 HUSB @S1@",
    "1 WIFE @S2@",
)


@pytest.mark.parametrize("configured", [False, True])
def test_cli_and_config_select_the_paired_family(
    tmp_path, capsys, monkeypatch, configured
):
    real = kincade.cli.render_with_counts
    monkeypatch.setattr(
        kincade.cli,
        "render_with_counts",
        lambda tree, root, opts: real(tree, root, replace(opts, compress=False)),
    )
    source, target = tmp_path / "family.ged", tmp_path / "out.pdf"
    source.write_bytes(ROOT_GED)
    args = [str(source), "--root", "R", "-o", str(target)]
    if configured:
        (tmp_path / "kincade.toml").write_text('root_family = "F2"\n')
    else:
        args += ["--root-family", "@F2@"]
    assert kincade.cli.main(args) == 0
    assert target.exists()
    assert "Traceback" not in capsys.readouterr().err
    text = drawn(target.read_bytes())
    assert "spouse: Second SPOUSE" in text and "m. 1935" in text
    assert "spouse: First SPOUSE" not in text


@pytest.mark.parametrize("selector", ["missing", "OTHER", ""])
def test_cli_invalid_family_exits_two_without_writing_pdf(tmp_path, capsys, selector):
    source, target = tmp_path / "family.ged", tmp_path / "out.pdf"
    source.write_bytes(ROOT_GED)
    assert (
        kincade.cli.main(
            [str(source), "--root", "R", "--root-family", selector, "-o", str(target)]
        )
        == 2
    )
    err = capsys.readouterr().err
    assert "root_family" in err and "Traceback" not in err
    assert not target.exists()


def test_fan_rejects_explicit_root_family(capsys):
    with pytest.raises(SystemExit) as error:
        kincade.cli.main(["--fan", "--root-family", "F2", "--show-config"])
    assert error.value.code == 2
    assert "--root-family is for the pedigree only" in capsys.readouterr().err


def test_fan_ignores_root_family_from_config(tmp_path, capsys):
    (tmp_path / "kincade.toml").write_text('fan = true\nroot_family = "missing"\n')
    assert kincade.cli.main(["--show-config"]) == 0
    text = capsys.readouterr().out
    assert "root_family" in text and "missing" not in text

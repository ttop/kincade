"""Root spouse typography and balanced gaps around the enlarged root box."""

import pytest

from kincade import Event, Family, Person, Tree
from kincade.pdf import page_geom

from conftest import PAPERS, PRINTS, full_pedigree, render
from pdfread import ink_box, pages, rectangles


def couple():
    return Tree(
        people={
            "R": Person("R", given="George", surname="Washington", families=["F"]),
            "S": Person("S", given="Martha", surname="Dandridge"),
        },
        families={"F": Family("F", "R", "S", Event())},
    )


@pytest.mark.parametrize("large_print", PRINTS)
def test_spouse_label_keeps_detail_font_and_name_uses_smaller_name_font(large_print):
    page = pages(render(couple(), "R", large_print=large_print))[0]
    root = next(run for run in page if run.text == "George WASHINGTON")
    label = next(run for run in page if run.text.strip() == "spouse:")
    spouse = next(run for run in page if run.text == "Martha DANDRIDGE")
    assert label.font == "Times-Roman" and label.size == root.size
    assert spouse.font == root.font == "Helvetica"
    assert spouse.size == pytest.approx(root.size * 0.9)
    assert spouse.y == label.y
    assert spouse.x >= label.right() - 0.01
    box = rectangles(render(couple(), "R", large_print=large_print), "B*")[0]
    assert (
        spouse.right()
        <= box[0] + box[2] - page_geom("letter", large_print).inset_right + 0.01
    )
    assert ink_box(spouse)[1] >= box[1]
    assert ink_box(spouse)[1] + ink_box(spouse)[3] <= box[1] + box[3]


@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("large_print", PRINTS)
@pytest.mark.parametrize("shadow", [False, True])
def test_initial_root_has_equal_gaps_to_neighboring_left_zone_boxes(
    paper, large_print, shadow
):
    tree = full_pedigree(5)
    boxes = rectangles(
        render(tree, paper=paper, large_print=large_print, shadow=shadow), "B*"
    )
    root = boxes[0]
    upper, lower = (2, 3) if large_print else (5, 6)
    above = root[1] - (boxes[upper - 1][1] + boxes[upper - 1][3])
    below = boxes[lower - 1][1] - (root[1] + root[3])
    assert above == pytest.approx(below, abs=0.01)
    assert above > 0

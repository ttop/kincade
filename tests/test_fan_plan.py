"""Fan planning on small invented trees: seating, years, privacy and colors."""

from datetime import date

import pytest

import kincade
from kincade.fan import Fan, FanCell, LegendEntry, check_fan
from kincade.fanplan import plan_fan
from kincade.lang import LangError
from kincade.model import Date, Day, Event, Family, ParentLink, Person, Tree

from conftest import full_pedigree


def root_years(person, **options):
    return plan_fan(Tree({person.id: person}), person.id, **options).cells[0].years


def test_a_sparse_fan_seats_only_known_people_and_their_missing_parents():
    tree = Tree(
        {
            "jane": Person(
                "jane", given="Jane", surname="Doe", parents=[ParentLink("f1")]
            ),
            "john": Person("john", given="John", surname="Doe"),
        },
        {"f1": Family("f1", "john", "", children=["jane"])},
    )
    fan = plan_fan(tree, "jane", generations=7)
    assert [(c.slot, c.given, c.empty) for c in fan.cells] == [
        (1, "Jane", False),
        (2, "John", False),
        (3, "", True),
        (4, "", True),
        (5, "", True),
    ]
    assert all(c.fill is None for c in fan.cells if c.empty)
    assert fan.legend == [] and fan.highlight == set()
    check_fan(fan)


@pytest.mark.parametrize(
    "adoptive,expected",
    [(False, ["Jane", "John", "June"]), (True, ["Jane", "Jack", "Joan"])],
)
def test_parent_family_selection_follows_the_requested_mode(adoptive, expected):
    tree = Tree(
        {
            "jane": Person(
                "jane",
                given="Jane",
                parents=[
                    ParentLink("adopted", "adopted", "adopted"),
                    ParentLink("birth"),
                ],
            ),
            "john": Person("john", given="John"),
            "june": Person("june", given="June"),
            "jack": Person("jack", given="Jack"),
            "joan": Person("joan", given="Joan"),
        },
        {
            "birth": Family("birth", "john", "june"),
            "adopted": Family("adopted", "jack", "joan"),
        },
    )
    fan = plan_fan(tree, "jane", generations=2, adoptive_parents=adoptive)
    assert [c.given for c in fan.cells] == expected


@pytest.mark.parametrize("missing", ["", "absent"])
def test_missing_partners_are_empty_and_have_no_ancestors(missing):
    tree = Tree(
        {"jane": Person("jane", parents=[ParentLink("f1")])},
        {"f1": Family("f1", missing, missing)},
    )
    fan = plan_fan(tree, "jane")
    assert [(c.slot, c.empty) for c in fan.cells] == [(1, False), (2, True), (3, True)]


def test_a_step_parent_is_empty_even_when_their_ancestors_are_known():
    tree = full_pedigree(4)
    tree.people["I1"].parents[0].father = "step"
    fan = plan_fan(tree, "I1", generations=3)
    assert [(c.slot, c.empty) for c in fan.cells] == [
        (1, False),
        (2, True),
        (3, False),
        (6, False),
        (7, False),
    ]


def test_cousins_shared_ancestors_keep_both_paths_and_count_every_copy():
    tree = full_pedigree(5)
    tree.families["F6"].father = "I8"
    fan = plan_fan(tree, "I1", generations=5)
    cells = {c.slot: c for c in fan.cells}
    assert cells[8].given == cells[12].given == "Person8"
    assert cells[8].copies == cells[12].copies == 2
    assert cells[8].fill == "#cddff4"
    assert cells[12].fill == "#f6e3bf"
    assert cells[16].given == cells[24].given == "Person16"
    assert cells[17].given == cells[25].given == "Person17"
    assert cells[16].copies == cells[24].copies == 2
    assert cells[17].copies == cells[25].copies == 2
    assert cells[9].copies == 1


def test_a_person_as_their_own_ancestor_ends_at_the_requested_ring():
    tree = Tree(
        {"jane": Person("jane", given="Jane", parents=[ParentLink("f1")])},
        {"f1": Family("f1", "jane", "jane")},
    )
    fan = plan_fan(tree, "jane", generations=7, exclude_private=True)
    assert len(fan.cells) == 127
    assert all(
        c.given == "Living" and c.copies == 127 and not c.empty for c in fan.cells
    )
    assert max(c.slot for c in fan.cells) == 127


@pytest.mark.parametrize(
    "generations,count", [(2, 3), (3, 7), (4, 15), (5, 31), (6, 63), (7, 127)]
)
def test_every_generation_limit_seats_exactly_the_requested_cells(generations, count):
    fan = plan_fan(full_pedigree(7), "I1", generations=generations)
    assert fan.generations == generations
    assert len(fan.cells) == count
    assert [c.slot for c in fan.cells] == list(range(1, count + 1))
    assert all(not c.empty and c.copies == 1 for c in fan.cells)
    check_fan(fan)


def test_defaults_give_six_generations_and_uppercase_surnames():
    tree = full_pedigree(7)
    root = tree.people["I1"]
    root.prefix, root.given, root.surname, root.suffix = (
        "Rev.",
        "Jane Ann",
        "Doe",
        "Jr.",
    )
    fan = plan_fan(tree, "I1")
    assert fan.generations == 6 and len(fan.cells) == 63
    assert fan.name == "Rev. Jane Ann DOE, Jr."
    assert (
        fan.cells[0].title,
        fan.cells[0].given,
        fan.cells[0].surname,
        fan.cells[0].suffix,
    ) == ("Rev.", "Jane Ann", "DOE", "Jr.")


@pytest.mark.parametrize("lang,index", [(None, 0), ("de", 1)])
@pytest.mark.parametrize(
    "born,expected",
    [
        (Date("exact", Day(1820, 5, 12)), ("1820–", "* 1820")),
        (Date("about", Day(1820)), ("abt 1820–", "* um 1820")),
        (Date("exact", Day(1820), quality="estimated"), ("abt 1820–", "* um 1820")),
        (Date("exact", Day(1820), quality="calculated"), ("abt 1820–", "* um 1820")),
        (Date("before", Day(1820)), ("bef 1820–", "* vor 1820")),
        (Date("to", Day(1820)), ("bef 1820–", "* vor 1820")),
        (Date("after", Day(1820)), ("aft 1820–", "* nach 1820")),
        (Date("from", Day(1820)), ("aft 1820–", "* nach 1820")),
        (Date("between", Day(1820), Day(1825)), ("bet 1820–", "* zw. 1820")),
        (Date("from_to", Day(1820), Day(1825)), ("bet 1820–", "* zw. 1820")),
        (Date("before", Day(1820), quality="estimated"), ("bef 1820–", "* vor 1820")),
        (
            Date("between", Day(1820), Day(1825), quality="calculated"),
            ("bet 1820–", "* zw. 1820"),
        ),
        (Date("between", Day(month=5), Day(1825)), ("bet 1825–", "* zw. 1825")),
        (Date("exact", Day(1730, dual_year=1731)), ("1730/31–", "* 1730/31")),
        (Date("exact", Day(1799, dual_year=1800)), ("1799/00–", "* 1799/00")),
        (Date("text", text="around 1820 or 1825"), ("1820–", "* 1820")),
        (Date("text", text="11820 then 1825"), ("1825–", "* 1825")),
        (Date("text", text="18200"), ("", "")),
        (Date("text", text="spring"), ("", "")),
        (Date("text", text="abt 1820", quality="estimated"), ("1820–", "* 1820")),
        (Date("exact", Day(1820), text="phrase says 2000"), ("1820–", "* 1820")),
        (Date("about", Day(month=5), text="around 1820"), ("1820–", "* 1820")),
        (Date("exact", Day(1820), text="1820", year_unknown=True), ("", "")),
        (Date("exact", Day(month=5, day=12)), ("", "")),
        (None, ("", "")),
    ],
)
def test_birth_years_follow_the_fans_year_rules_in_both_languages(
    born, expected, lang, index
):
    assert root_years(Person("jane", birth=Event(born)), lang=lang) == expected[index]


@pytest.mark.parametrize("lang,deceased", [(None, "Deceased"), ("de", "verstorben")])
def test_exact_birth_and_death_years_join_with_an_en_dash(lang, deceased):
    person = Person(
        "jane",
        birth=Event(Date("exact", Day(1820))),
        death=Event(Date("exact", Day(1891))),
    )
    assert root_years(person, lang=lang) == "1820–1891"


@pytest.mark.parametrize("lang,deceased", [(None, "Deceased"), ("de", "verstorben")])
@pytest.mark.parametrize(
    "death",
    [
        Event(),
        Event(place="Doeville"),
        Event(Date("text", text="spring")),
        Event(Date("exact", Day(1891), year_unknown=True)),
    ],
)
def test_a_death_record_without_a_readable_year_says_deceased(lang, deceased, death):
    person = Person("jane", birth=Event(Date("exact", Day(1840))), death=death)
    assert root_years(person, lang=lang) == f"1840–{deceased}"


@pytest.mark.parametrize("lang,expected", [(None, "–Deceased"), ("de", "–verstorben")])
def test_an_undated_death_without_a_birth_still_says_deceased(lang, expected):
    assert root_years(Person("jane", death=Event()), lang=lang) == expected


@pytest.mark.parametrize("lang,expected", [(None, "–1891"), ("de", "† 1891")])
def test_a_death_year_alone_follows_the_languages_died_only(lang, expected):
    assert (
        root_years(Person("jane", death=Event(Date("exact", Day(1891)))), lang=lang)
        == expected
    )


@pytest.mark.parametrize("lang,index", [(None, 0), ("de", 1)])
@pytest.mark.parametrize(
    "events,expected",
    [
        (
            {"christenings": [Event(Date("exact", Day(1852)))]},
            ("chr 1852–", "get. 1852–"),
        ),
        (
            {"christenings": [Event(Date("about", Day(1852)))]},
            ("chr abt 1852–", "get. um 1852–"),
        ),
        (
            {
                "birth": Event(Date("about", Day(1820))),
                "burials": [Event(Date("exact", Day(1871)))],
            },
            ("abt 1820–bur 1871", "um 1820–begr. 1871"),
        ),
        (
            {"cremations": [Event(Date("before", Day(1871)))]},
            ("–crem bef 1871", "–krem. vor 1871"),
        ),
        ({"christenings": [Event(Date("text", text="spring"))]}, ("", "")),
        ({"christenings": [Event(place="Doeville")]}, ("", "")),
        (
            {"burials": [Event(Date("text", text="spring"))]},
            ("–Deceased", "–verstorben"),
        ),
        ({"cremations": [Event(place="Doeville")]}, ("–Deceased", "–verstorben")),
        ({"burials": [Event()], "cremations": [Event()]}, ("", "")),
        ({}, ("", "")),
    ],
)
def test_stand_in_words_wrap_only_readable_years(events, expected, lang, index):
    assert root_years(Person("jane", **events), lang=lang) == expected[index]


@pytest.mark.parametrize("lang", [None, "de"])
def test_disabling_stand_ins_ignores_their_years_and_deceased_word(lang):
    person = Person(
        "jane",
        christenings=[Event(Date("exact", Day(1852)))],
        burials=[Event(Date("exact", Day(1871)))],
    )
    assert root_years(person, event_standins=False, lang=lang) == ""
    person.death = Event()
    expected = "–verstorben" if lang == "de" else "–Deceased"
    assert root_years(person, event_standins=False, lang=lang) == expected


def test_stand_ins_reuse_the_first_filled_event_and_prefer_burial_to_cremation():
    person = Person(
        "jane",
        birth=Event(),
        death=Event(),
        christenings=[
            Event(),
            Event(Date("exact", Day(1852))),
            Event(Date("exact", Day(1853))),
        ],
        burials=[Event(), Event(Date("exact", Day(1871)))],
        cremations=[Event(Date("exact", Day(1872)))],
    )
    assert root_years(person) == "chr 1852–bur 1871"


def test_filled_birth_and_death_records_keep_precedence_over_stand_ins():
    person = Person(
        "jane",
        birth=Event(place="Doeville"),
        death=Event(place="Doeville"),
        christenings=[Event(Date("exact", Day(1852)))],
        burials=[Event(Date("exact", Day(1871)))],
    )
    assert root_years(person) == "–Deceased"


@pytest.mark.parametrize("living,hidden", [(None, True), (True, True), (False, False)])
def test_privacy_redacts_names_and_years_and_respects_the_callers_verdict(
    living, hidden
):
    person = Person(
        "jane",
        given="Jane",
        surname="Doe",
        birth=Event(Date("exact", Day(date.today().year - 20))),
        living=living,
    )
    tree = Tree({"jane": person})
    shown = plan_fan(tree, "jane").cells[0]
    private = plan_fan(tree, "jane", exclude_private=True).cells[0]
    assert private.given == ("Living" if hidden else "Jane")
    assert private.surname == ("" if hidden else "DOE")
    assert private.years == ("" if hidden else shown.years)
    assert shown.years != ""


def test_a_living_override_hides_years_even_with_a_death_record():
    person = Person(
        "jane",
        birth=Event(Date("exact", Day(1820))),
        death=Event(Date("exact", Day(1891))),
        living=True,
    )
    assert root_years(person, exclude_private=True) == ""


def test_privacy_uses_the_unlimited_pedigree_even_for_a_two_generation_fan():
    tree = full_pedigree(4)
    tree.families["F3"].mother = "I2"
    tree.people["I6"].birth = Event(Date("exact", Day(1800)))
    tree.people["I6"].parents = [ParentLink("older")]
    tree.families["older"] = Family("older", "I2", "")
    tree.people["I2"].birth = Event(Date("from", Day(1700)))
    fan = plan_fan(tree, "I1", generations=2, exclude_private=True)
    assert fan.cells[1].years == "aft 1700–"


@pytest.mark.parametrize(
    "ink,expected",
    [
        (
            "color",
            [
                "#f7f8fa",
                "#e1e7ef",
                "#f1e3e8",
                "#cddff4",
                "#d3ecd9",
                "#f6e3bf",
                "#f5d2dd",
            ],
        ),
        ("grayscale", [None, None, None, "#c8c8c8", "#a6a6a6", "#e4e4e4", "#b8b8b8"]),
        ("bw", [None, None, None, None, None, None, None]),
    ],
)
def test_ink_colors_the_center_sides_and_each_grandparent_line(ink, expected):
    fan = plan_fan(full_pedigree(4), "I1", generations=4, ink=ink)
    assert [c.fill for c in fan.cells[:7]] == expected
    assert [c.fill for c in fan.cells[7:]] == [
        color for color in expected[3:] for _ in range(2)
    ]
    assert fan.legend == [] and fan.highlight == set()


def test_black_and_white_has_no_fills_at_any_generation():
    assert all(
        c.fill is None
        for c in plan_fan(full_pedigree(7), "I1", generations=7, ink="bw").cells
    )


def test_a_language_mapping_overrides_year_words_and_falls_back_to_english():
    person = Person("jane", christenings=[Event(Date("about", Day(1852)))])
    assert (
        root_years(person, lang={"years": {"about": "circa {y}"}}) == "chr circa 1852–"
    )


def test_a_language_shapes_the_years_and_a_stand_in_alone_keeps_lifespan():
    lang = {"years": {"lifespan": "{born} to {died}", "born_only": "b. {born}"}}
    born = Person("jane", birth=Event(Date("exact", Day(1820))))
    christened = Person("jane", christenings=[Event(Date("exact", Day(1852)))])
    both = Person(
        "jane",
        birth=Event(Date("exact", Day(1820))),
        death=Event(Date("exact", Day(1891))),
    )
    assert root_years(born, lang=lang) == "b. 1820"
    assert root_years(christened, lang=lang) == "chr 1852 to "
    assert root_years(both, lang=lang) == "1820 to 1891"


def test_a_language_path_supplies_year_words(tmp_path):
    path = tmp_path / "wording.toml"
    path.write_text('[years]\nabout = "circa {y}"\n', encoding="utf-8")
    assert (
        root_years(
            Person("jane", birth=Event(Date("about", Day(1820)))), lang=str(path)
        )
        == "circa 1820–"
    )


def test_an_unknown_root_is_a_keyerror():
    with pytest.raises(KeyError, match="absent"):
        plan_fan(Tree(), "absent")


@pytest.mark.parametrize("generations", [1, 8, True, "6", 6.0])
def test_invalid_generations_are_a_valueerror(generations):
    with pytest.raises(ValueError) as error:
        plan_fan(Tree({"jane": Person("jane")}), "jane", generations=generations)
    assert "generations" in str(error.value) and repr(generations) in str(error.value)


@pytest.mark.parametrize("ink", ["gray", "", "COLOR"])
def test_an_invalid_ink_is_a_valueerror(ink):
    with pytest.raises(ValueError) as error:
        plan_fan(Tree({"jane": Person("jane")}), "jane", ink=ink)
    assert "ink" in str(error.value) and repr(ink) in str(error.value)


@pytest.mark.parametrize("lang", ["zz", {"years": {"about": "{year}"}}])
def test_a_bad_language_is_a_langerror(lang):
    with pytest.raises(LangError):
        plan_fan(Tree({"jane": Person("jane")}), "jane", lang=lang)


def test_the_fan_data_and_planner_are_public_names():
    assert kincade.Fan is Fan
    assert kincade.FanCell is FanCell
    assert kincade.LegendEntry is LegendEntry
    assert kincade.plan_fan is plan_fan
    assert {"Fan", "FanCell", "LegendEntry", "plan_fan"} <= set(kincade.__all__)

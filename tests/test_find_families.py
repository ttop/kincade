"""--find keeps each person row and lists usable spouse-family IDs below it."""

import pytest

from kincade.cli import main

from conftest import ged


@pytest.fixture
def unions(tmp_path):
    path = tmp_path / "unions.ged"
    path.write_bytes(
        ged(
            "0 @R@ INDI",
            "1 NAME Root /vanDyke/",
            "1 BIRT",
            "2 DATE 1700",
            "1 DEAT",
            "2 DATE 1780",
            "1 FAMS @F2@",
            "1 FAMS @F1@",
            "1 FAMS @F2@",
            "1 FAMS @FP@",  # a corrupt FAMS must not make parents a spouse family
            "1 FAMS @missing@",
            "1 FAMC @FP@",
            "0 @S1@ INDI",
            "1 NAME First /McClure/",
            "1 DEAT Y",
            "0 @S2@ INDI",
            "1 NAME Second /deVries/",
            "1 DEAT Y",
            "0 @P@ INDI",
            "1 NAME Parent /Line/",
            "1 DEAT Y",
            "0 @F1@ FAM",
            "1 HUSB @R@",
            "1 WIFE @S1@",
            "1 MARR",
            "2 DATE 1725",
            "2 PLAC First Town",
            "0 @F2@ FAM",
            "1 HUSB @R@",
            "1 WIFE @S2@",
            "1 MARR",
            "2 DATE 6 JAN 1759",
            "2 PLAC Other Town",
            "0 @FP@ FAM",
            "1 HUSB @P@",
            "1 CHIL @R@",
            "1 MARR",
            "2 DATE 1680",
            "0 @F3@ FAM",  # an actual partner family missing a reciprocal FAMS
            "1 HUSB @R@",
        )
    )
    return path


def find(path, capsys, text="R", *options):
    assert main([str(path), "--find", text, *options]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return captured.out.splitlines()


def rewrite(path, before, after):
    data = path.read_text()
    assert before in data
    path.write_text(data.replace(before, after))


def test_find_lists_multiple_wives_in_fams_order_once_then_missing_backlinks(
    unions, capsys
):
    assert find(unions, capsys) == [
        "R\tRoot VANDYKE\t1700-1780",
        "    F2\tSecond DEVRIES\tm. 6 Jan 1759\tmp. Other Town\t(default)",
        "    F1\tFirst McCLURE\tm. 1725\tmp. First Town",
        "    F3\tUnknown spouse",
    ]


def test_find_mother_role_lists_the_other_partner(unions, capsys):
    rewrite(unions, "1 HUSB @R@\n1 WIFE @S2@", "1 HUSB @S2@\n1 WIFE @R@")
    assert find(unions, capsys)[1] == (
        "    F2\tSecond DEVRIES\tm. 6 Jan 1759\tmp. Other Town\t(default)"
    )


def test_find_groups_families_beneath_each_matched_person(unions, capsys):
    rewrite(unions, "First /McClure/", "First /vanDyke/")
    rewrite(unions, "Second /deVries/", "Second /vanDyke/")
    assert find(unions, capsys, "vandyke") == [
        "R\tRoot VANDYKE\t1700-1780",
        "    F2\tSecond VANDYKE\tm. 6 Jan 1759\tmp. Other Town\t(default)",
        "    F1\tFirst VANDYKE\tm. 1725\tmp. First Town",
        "    F3\tUnknown spouse",
        "S1\tFirst VANDYKE\t",
        "    F1\tRoot VANDYKE\tm. 1725\tmp. First Town",
        "S2\tSecond VANDYKE\t",
        "    F2\tRoot VANDYKE\tm. 6 Jan 1759\tmp. Other Town",
    ]


@pytest.mark.parametrize("first", ["missing", "FP"])
def test_find_does_not_mark_a_later_family_default_when_first_fams_is_unusable(
    unions, capsys, first
):
    rewrite(unions, "1 FAMS @F2@\n", f"1 FAMS @{first}@\n")
    rows = find(unions, capsys)
    assert rows == [
        "R\tRoot VANDYKE\t1700-1780",
        "    F1\tFirst McCLURE\tm. 1725\tmp. First Town",
        "    F2\tSecond DEVRIES\tm. 6 Jan 1759\tmp. Other Town",
        "    F3\tUnknown spouse",
    ]


def test_find_with_no_fams_includes_partner_families_in_file_order_without_default(
    unions, capsys
):
    unions.write_text(
        "\n".join(
            line for line in unions.read_text().splitlines() if " FAMS " not in line
        )
    )
    assert find(unions, capsys) == [
        "R\tRoot VANDYKE\t1700-1780",
        "    F1\tFirst McCLURE\tm. 1725\tmp. First Town",
        "    F2\tSecond DEVRIES\tm. 6 Jan 1759\tmp. Other Town",
        "    F3\tUnknown spouse",
    ]


def test_find_person_with_only_parent_families_keeps_the_original_person_row(
    tmp_path, capsys
):
    path = tmp_path / "child.ged"
    path.write_bytes(
        ged(
            "0 @R@ INDI",
            "1 NAME Root /vanDyke/",
            "1 BIRT",
            "2 DATE 1700",
            "1 FAMC @FP@",
            "0 @P@ INDI",
            "1 NAME Parent /Line/",
            "0 @FP@ FAM",
            "1 HUSB @P@",
            "1 CHIL @R@",
        )
    )
    assert find(path, capsys) == ["R\tRoot VANDYKE\t1700-"]


@pytest.mark.parametrize(
    "before, after, family_row",
    [
        (
            "1 WIFE @S2@\n",
            "",
            "    F2\tUnknown spouse\tm. 6 Jan 1759\tmp. Other Town\t(default)",
        ),
        (
            "0 @S2@ INDI\n1 NAME Second /deVries/\n1 DEAT Y\n",
            "",
            "    F2\tUnknown spouse\tm. 6 Jan 1759\tmp. Other Town\t(default)",
        ),
        (
            "1 NAME Second /deVries/",
            "1 NAME //",
            "    F2\tUnknown spouse\tm. 6 Jan 1759\tmp. Other Town\t(default)",
        ),
        (
            "1 MARR\n2 DATE 6 JAN 1759\n2 PLAC Other Town\n",
            "",
            "    F2\tSecond DEVRIES\t(default)",
        ),
        (
            "2 DATE 6 JAN 1759\n",
            "",
            "    F2\tSecond DEVRIES\tmp. Other Town\t(default)",
        ),
        (
            "2 PLAC Other Town\n",
            "",
            "    F2\tSecond DEVRIES\tm. 6 Jan 1759\t(default)",
        ),
    ],
    ids=["spouse-id", "spouse-record", "spouse-name", "marriage", "date", "place"],
)
def test_find_keeps_available_values_when_family_fields_are_missing(
    unions, capsys, before, after, family_row
):
    rewrite(unions, before, after)
    assert find(unions, capsys)[1] == family_row


def test_find_missing_first_family_record_does_not_promote_a_later_default(
    unions, capsys
):
    rewrite(
        unions,
        "0 @F2@ FAM\n1 HUSB @R@\n1 WIFE @S2@\n1 MARR\n2 DATE 6 JAN 1759\n2 PLAC Other Town\n",
        "",
    )
    assert find(unions, capsys) == [
        "R\tRoot VANDYKE\t1700-1780",
        "    F1\tFirst McCLURE\tm. 1725\tmp. First Town",
        "    F3\tUnknown spouse",
    ]


def test_find_preserves_spouse_case_with_names_prefixes_suffixes_and_controls(
    unions, capsys
):
    rewrite(
        unions,
        "1 NAME Second /deVries/",
        "1 NAME Dr.\tSecond\x01 /deVries/ , Jr.\n2 NPFX Dr.\n2 NSFX , Jr.",
    )
    rewrite(unions, "2 PLAC Other Town", "2 PLAC Other\tTown\x01")
    rows = find(unions, capsys, "R", "--preserve-case")
    assert rows[0] == "R\tRoot vanDyke\t1700-1780"
    assert rows[1] == (
        "    F2\tDr. Second deVries, Jr.\tm. 6 Jan 1759\tmp. Other Town\t(default)"
    )
    assert rows[2] == "    F1\tFirst McClure\tm. 1725\tmp. First Town"


def test_find_localizes_marriage_labels_and_dates(unions, tmp_path, capsys):
    assert find(unions, capsys, "R", "--lang", "de")[1] == (
        "    F2\tSecond DEVRIES\tverh. 6. Jan. 1759\tin Other Town\t(default)"
    )
    lang = tmp_path / "custom.toml"
    lang.write_text(
        'date_format = "{year}/{month}/{day}"\n'
        '[labels]\nmarriage = "married"\nmarriage_place = "at"\n'
    )
    assert find(unions, capsys, "R", "--lang", str(lang))[1] == (
        "    F2\tSecond DEVRIES\tmarried 1759/Jan/6\tat Other Town\t(default)"
    )


@pytest.mark.parametrize(
    "root_living, spouse_living",
    [(False, False), (False, True), (True, False), (True, True)],
)
def test_find_privacy_hides_living_spouse_identity_and_either_partners_marriage(
    tmp_path, capsys, root_living, spouse_living
):
    path = tmp_path / "privacy.ged"
    records = ["0 @R@ INDI", "1 NAME Root /vanDyke/", "1 BIRT"]
    records += ["2 DATE 2000"] if root_living else ["2 DATE 1700", "1 DEAT Y"]
    records += ["1 FAMS @F1@", "0 @S@ INDI", "1 NAME Spouse /deVries/", "1 BIRT"]
    records += ["2 DATE 2000"] if spouse_living else ["2 DATE 1700", "1 DEAT Y"]
    records += [
        "0 @F1@ FAM",
        "1 HUSB @R@",
        "1 WIFE @S@",
        "1 MARR",
        "2 DATE 6 JAN 2021",
        "2 PLAC Private Town",
    ]
    path.write_bytes(ged(*records))
    rows = find(
        path, capsys, "R", "--exclude-private", "--preserve-case", "--lang", "de"
    )
    assert rows[0] == (
        "R\tLebende Person\t" if root_living else "R\tRoot vanDyke\t1700-"
    )
    spouse = "Lebende Person" if spouse_living else "Spouse deVries"
    if root_living or spouse_living:
        assert rows[1] == f"    F1\t{spouse}\t(default)"
        assert all("2021" not in row and "Private Town" not in row for row in rows)
    else:
        assert rows[1] == (
            "    F1\tSpouse deVries\tverh. 6. Jan. 2021\tin Private Town\t(default)"
        )
    if spouse_living:
        assert all("Spouse" not in row and "deVries" not in row for row in rows)
    public = find(path, capsys)[1]
    assert (
        public == "    F1\tSpouse DEVRIES\tm. 6 Jan 2021\tmp. Private Town\t(default)"
    )


def test_find_default_marker_is_not_changed_by_a_root_family_override(unions, capsys):
    assert find(unions, capsys, "R", "--root-family", "F1")[1:3] == [
        "    F2\tSecond DEVRIES\tm. 6 Jan 1759\tmp. Other Town\t(default)",
        "    F1\tFirst McCLURE\tm. 1725\tmp. First Town",
    ]

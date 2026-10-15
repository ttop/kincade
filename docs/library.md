# Kincade Python library

Use Kincade from Python to read a GEDCOM file or work with a family tree already
in memory. Rendering returns PDF bytes.

```python
from pathlib import Path

from kincade import Options, read_gedcom, render, render_blank

tree = read_gedcom("docs/examples/george-washington.ged")  # a path, or the file's bytes
pdf = render(tree, "I1", Options(generations=7, exclude_private=True))  # PDF bytes
Path("washington.pdf").write_bytes(pdf)
Path("blank.pdf").write_bytes(render_blank(Options(large_print=True, lang="de")))
```

Save this as `example.py` in the `kincade` folder and run:

```sh
uv run python example.py
```

`read_gedcom` accepts a path or bytes. A string is always interpreted as a path.
Record IDs omit GEDCOM's `@` delimiters: `@I12@` in the file becomes `"I12"`.

`render(tree, root, options=None)` plans and draws a pedigree. `root` is a record
ID in `tree.people`; an unknown ID raises `KeyError`.
`render_blank(options=None)` makes a blank chart without a tree.

`load_fontset()` returns `(FontSet or None, missing roles)` without printing a
warning. Pass a returned font set as `Options(fonts=...)` or `FanOptions(fonts=...)`.
Rendering may read system fonts and a language file; it does not write files.
Importing `kincade` has no side effects.

The supported public API is exported from `kincade`: `Tree`, `Person`, `Family`,
`Event`, `Date`, `Day`, `ParentLink`, `Options`, `LangError`, `render`,
`render_blank`, `read_gedcom`, `load_fontset`, `Fan`, `FanCell`, `LegendEntry`,
`FanOptions`, `plan_fan`, `render_fan` and `__version__`. Other module functions
are available for advanced use but are outside that compatibility promise.


## A fan in library code

`plan_fan` turns a `Tree` into a `Fan`. `render_fan` draws that fan and returns
PDF bytes without writing a file. Pass the same ink to both: the planner
chooses fills, and the renderer draws them.

```python
from pathlib import Path

from kincade import FanOptions, plan_fan, read_gedcom, render_fan

tree = read_gedcom("docs/examples/george-washington.ged")
fan = plan_fan(tree, "I1", generations=7, ink="grayscale", exclude_private=True)
pdf = render_fan(fan, FanOptions(ink="grayscale", paper="a3"))
Path("fan.pdf").write_bytes(pdf)
```

`plan_fan(tree, root, ...)` takes `generations` (default 6), `ink` (default
`"color"`), `exclude_private` and `adoptive_parents` (default `False`),
`preserve_case` (default `False`), `event_standins` (default `True`) and `lang`.
An unknown root raises `KeyError`.
It draws nothing and reads only a language file when one is named.

A program with its own family data can build a `Fan` directly.
`Fan`, `FanCell` and `LegendEntry` are mutable dataclasses. The renderer
uses the supplied cells, text, fills, legend and highlight; it chooses no
ancestors or year words.

| `Fan` field | Meaning |
|---|---|
| `generations` | 2 to 7, counting the center as 1. |
| `cells` | A list of `FanCell` objects. |
| `legend` | A list of `LegendEntry` objects in display order; empty by default. |
| `highlight` | A set of cell slots to highlight; empty by default. |
| `name` | The center person's name for the default title; empty by default. |

A `FanCell` has a `slot`: 1 for the center, twice a person's slot for their
father, twice plus one for their mother. It holds `empty` (default `False`),
`title`, `given`, `surname`, `suffix`, `years` (strings, empty by default),
`fill` (`"#rrggbb"` or `None`, default `None`) and `copies` (default 1).
An empty cell has no text or fill. A `copies` value above 1 draws a repeat
mark; values below 2 draw none. Years are already written text.
`LegendEntry(label, color, count)` holds a label, a `"#rrggbb"` swatch or
`None` for an outline, and a count. Colors accept upper- or lowercase hex
digits.
The planner supplies no legend or highlight; the grandparent cells name its
four colored lines.

`FanOptions` takes fields in this order: `ink`, `paper`, `lang`, `title`,
`footer`, `today`, `compress`, `fonts`. The defaults for `ink` and `paper`
are `"color"` and `"letter"`.
`lang=None` selects English. `title=None` and `footer=None` use the language's
page text; `footer=False` leaves the footer off. `today`, `compress` and
`fonts` work as in `Options`. `today` sets only the footer date; the planner
uses today's year for privacy. A `FontSet` from `load_fontset()` works in
either options class. The renderer uses the fills
as supplied, including in grayscale; a caller supplies gray fills for gray
printing. Black and white ignores fills and the legend. A highlight fades
other cells in color, leaves them unfilled in grayscale, and doubles the
highlighted people's outlines in black and white. Empty cells keep their
usual dashed gray outline in every ink. Text is black or white for contrast
against the fill as drawn.

`render_fan` raises `ValueError` for invalid generations, slots outside the
fan, duplicate slots, a cell whose child is missing or empty, invalid fill or
legend colors, or a highlight slot with no cell. It also refuses an unknown
ink or paper, or a legend that cannot fit even with the fan at a quarter of
its full size. A legend sits below the center, inside the bottom gap or
below the fan.
Each entry shows its swatch, label and count in parentheses. More columns,
smaller type and a smaller fan make room; legend text is never cut.

## The Options class

`Options` controls pedigree rendering. Some names describe what is included:
for example, `index=False` corresponds to `--no-index`.
`Options(root_family="F1")` selects the initial root's paired spouse and marriage;
a missing family or a family without the root as a partner raises `ValueError`.

| Field | Default | Flag |
|---|---|---|
| `generations` | `None` (every known ancestor) | `--generations` |
| `exclude_private` | `False` | `--exclude-private` |
| `preserve_case` | `False` | `--preserve-case` |
| `root_family` | `None` (first spouse family) | `--root-family` |
| `adoptive_parents` | `False` | `--adoptive-parents` |
| `event_standins` | `True` | `--no-event-standins` |
| `empty_boxes` | `True` | `--no-empty` |
| `show_ids` | `False` | `--show-ids` |
| `shorten_places` | `True` | `--no-shorten-places` |
| `index` | `True` | `--no-index` |
| `page_numbers` | `True` | `--no-page-numbers` |
| `footer` | `None` (the language's); text; `False` for none | `--footer`, `--no-footer` |
| `title` | `None` (the language's title and root's name) | `--title` |
| `paper` | `"letter"` (or `"a4"`) | `--paper` |
| `large_print` | `False` | `--large-print` |
| `shadow` | `False` | `--shadow` |
| `lang` | `None` (English); a name, a `.toml` path, or a dict of strings | `--lang` |

Three fields are not flags. `fonts` is `"auto"` by default, which is what the command line always uses: it embeds the system TrueType fonts when it finds them and may use them, else the built-in PDF fonts; `"base14"` always uses the built-in fonts, and a `FontSet` from `load_fontset` uses its faces. `today` sets the date in the footer and the year used by the privacy estimate (`None` is today), and `compress=False` writes the PDF's streams uncompressed, so their text can be searched (`True` by default). `render_blank` uses `paper`, `large_print`, `shadow`, `lang`, `title`, `footer`, `fonts` and `compress`, and ignores the others, which have nothing to apply to. With no `footer` its footer is the language's `footer_blank`, so it does not depend on the date.

## The model

Build a tree directly when your program already has the family data:

```python
from kincade import Date, Day, Event, Family, ParentLink, Person, Tree, render

tree = Tree(
    people={
        "ann": Person(
            "ann",
            given="Ann",
            surname="Pell",
            parents=[ParentLink("f1")],
            birth=Event(Date("exact", Day(1990, 4, 2)), "Dayton, Ohio, USA"),
            living=False,
        ),
        "bob": Person(
            "bob",
            given="Bob",
            surname="Pell",
            families=["f1"],
            birth=Event(Date("about", Day(1960))),
            death=Event(Date("exact", Day(2010))),
        ),
    },
    families={
        "f1": Family(
            "f1",
            father="bob",
            children=["ann"],
            marriage=Event(Date("exact", Day(1988)), "Reno"),
        )
    },
)
pdf = render(tree, "ann")
```

- A `Person` has `id`, `given`, `surname`, `prefix`, `suffix`, a `birth` and a `death` event (`None` for no record; a `death` with no date still means the person died), the stand-ins for a missing birth or death (`christenings`, `burials`, `cremations`: lists of events), `parents` (`ParentLink`s in order) and `families` (the families where the person is a parent, in order).
- An `Event` has a `date` (a `Date` or `None`) and a `place` (one text, already joined: `"Eugene, Lane County, Oregon, USA"`).
- A `Day` is a `year` (1 to 9999), `month` (1 to 12), `day` (1 to 31) and `dual_year`, each optional; a `Day` outside them is a `ValueError`. A `Date` has a `form` (`"exact"`, `"about"`, `"before"`, `"after"`, `"between"`, `"from"`, `"to"`, `"from_to"` or `"text"`), a `start` and an `end` (`Day(year, month, day)`, each part optional, plus `dual_year` for a double date such as 1731/32, which must be `year + 1`), a `quality` (`""`, `"estimated"` or `"calculated"`) and a `text`, which is printed in place of the structure when it is set: a date phrase, or text that is not a date. The living estimate reads the structure and any recognized whole-text date shape in the text. `year_unknown=True` marks a date that was recorded in a calendar the reader cannot convert: it prints as it does, but the index shows no year for it and the estimate takes it to allow any year up to today. The GEDCOM reader gives such a date its written text, so it prints as written.
- A `ParentLink` is a family record ID and the child's relationship to each of that family's parents: `father` (to `Family.father`) and `mother` (to `Family.mother`), each `"birth"` (the default), `"adopted"`, `"foster"`, `"step"` or `"other"`. They are separate because a child can be a birth child of one parent and a stepchild of the other, which is how Gramps (`frel`, `mrel`) and other programs store it: `ParentLink("f1", father="step")` is the mother's birth child and her husband's stepchild. A `"step"` parent is never drawn (the box is empty), and when the parents drawn are `"adopted"` or `"foster"`, the child's name is followed by the note `(adopted)` or `(foster)`. `Tree.parent_ids(pid, prefer="birth")` gives the (father, mother) that are drawn. A `Family` has `father`, `mother`, a `marriage` event and its `children`.
- `Person.living` is `None` by default, which keeps Kincade's estimate of who may be living (see [Privacy](../README.md#privacy)). `True` or `False` replaces the estimate for that person only. It matters when `exclude_private` is set: use it when your application already knows who is living.

`Date`, `Day` and `ParentLink` check their words and numbers when they are made and raise `ValueError` for one they do not know. A `Date` that contradicts itself is refused the same way: `"between"` and `"from_to"` need both a `start` and an `end`, no other form takes an `end` (`Date("from", Day(1900), Day(2000))` would print "from 1900" yet be read as bounded by 2000), and `"text"` needs `text`. `read_gedcom` makes exactly these objects: it reads each date once, so the dates, the index and the estimate all read the same structure.

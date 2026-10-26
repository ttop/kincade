# Changelog

## Unreleased

- Pedigree boxes have equal gaps to the facing boxes above and below, with uniform
  spacing in the rightmost column, in normal and large print.
- Browser installs work at directory URLs without a trailing slash, as well as
  URLs ending in `/` or `/index.html`, without requiring a host redirect.
- Failed wheel downloads include the HTTP status, download URL and recovery hint.
- Spanish, French and Italian charts (`--lang es`, `fr`, `it`), with their own date
  forms (French 1er, Italian 1º) and index order (Spanish ñ, French d’ and
  ligatures).
- An `ignore_particles` item ending in an apostrophe, such as `d’`, is skipped
  when it starts a surname: d’Artagnan files under A. An item may be a phrase,
  such as `de la`.
- Skipped particles print in their recorded case (Anna von der HEIDE) and, in the
  index, after the given name (HEIDE, Anna von der). German adds zur, und, ten and
  ter.
- The index sort reads a hyphen as a space, so hyphenated names file word by word.
- Capitalized surnames keep ß (WEIß).
- Language files can word a date qualifier before a full date (`[dates.with_day]`,
  French "avant le 3 mars"), rewrite phrases in worded dates (`[dates.rewrite]`,
  Italian "dall’8") and set the index reference (`index.reference`, German
  `6/1`).
- German wording revised: Lebende Person, Ehe mit:, eingeäschert, a clearer
  index legend and chart note, and spaced date ranges.
- A language file's `[days]` table writes chosen days of the month its own way,
  such as French `1 = "1er"`.
- Automatic PDF file names come from the language file (`file_name`,
  `fan_file_name`, `blank_file_name`), so `--lang de` saves
  `Ahnentafel Jane Doe.pdf`. A root with no usable name gives
  `cascading pedigree.pdf`.
- Fan years come from the language file (`years.lifespan`, `born_only`,
  `died_only`): German prints a birth year alone as `* 1980` and a death year
  alone as `† 1960`.
- The `Mc` of McCLURE is the `[sort]` setting `keep_case_prefixes` (default
  `["Mc"]`), and a prefix keeps its case only when a capital follows it, so
  Mcclure prints as MCCLURE.
- `[sort.surname_start]` replaces the start of a surname's sort key, such as
  `mc = "mac"`. It replaces `mc_as_mac`; `mc_as_mac = true` still reads as
  `mc = "mac"`.
- `--find` and the people an ambiguous `--root` lists print names with the chart
  language's particles and prefixes.
- The browser page speaks English, German, Spanish, French and Italian, chosen
  from the browser's languages, the header or `?lang=`. Chart language sets the
  PDFs' language and follows the page's until another is chosen.

## 1.0

Initial public release.

- Cascading pedigree, fan, and blank charts from GEDCOM files.
- Browser, command-line, and Python library interfaces.

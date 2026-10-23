# Domain packs

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-lightgrey)](README.md) [![English](https://img.shields.io/badge/lang-English-1f6feb)](README.en.md)

Inputs prepared **before** running Specton. A run only reads them; run outputs (requirements, ERD, DDL, etc.) are never written here.

## File kinds

| Mark | Meaning | How to change |
|---|---|---|
| ✍ | Written by people | Edit directly → PR |
| ⚙ | Generated (marked `GENERATED` at the top) | Do not edit. Fix the inputs and regenerate |

```text
sources/                       ✍ copies of the official common standard CSVs + sources.yaml (edition, source)
common/
  manifest.yaml naming.yaml rules.yaml   ✍
  words.yaml                   ⚙ official words used by packs + all official classifier words
  domains.yaml                 ⚙ official domains used by packs (with PostgreSQL mapping)
inventory/ · maintenance/
  manifest.yaml                ✍
  term_specs.yaml              ✍ term names, component words, domains, synonyms
  terms.yaml                   ⚙ resolved physical names and source (official/project)
  words.yaml                   ✍ pack-only words not in the common standard
  patterns.yaml                ✍
  examples/A01.yaml … A09.yaml ✍ few-shot examples per agent (owned by each agent's owner)
```

## How to work

```bash
uv run python -m specton.packs.build          # regenerate ⚙ files after editing ✍ inputs
uv run python -m specton.packs.build --check  # check ⚙ files are up to date (runs in CI)
```

- The generator checks that terms end with a classifier word, that the classifier matches the domain, that physical names fit in 63 bytes, and that physical names are unique; it fails on any violation.
- When a pack changes, bump `version` in its `manifest.yaml`. Freeze it as `status: approved` before evaluation.
- Take few-shot examples only from the development set and put the source ID in `source_id`. Never include documents from the evaluation set.
- Switching common standard editions: replace the CSVs in `sources/`, update `sources.yaml`, then regenerate.

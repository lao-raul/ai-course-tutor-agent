# ChinaTextbook inventory for Hiruzen

**Observed:** 2026-10-07  
**Access:** read-only macOS mount  
**Purpose:** catalog and golden-set planning; no textbook content is copied here

## Corpus baseline

- Development mount: `/Volumes/home/ChinaTextbook`.
- NAS-internal source: `/var/services/homes/lvjial/ChinaTextbook`.
- Checkout size: approximately 85 GiB, including repository history/cache.
- Complete `.pdf` files: 1,905.
- Top-level education families include primary, middle school, five-four-system
  variants, high school and university. Hiruzen first release publishes ChinaTextbook
  K-12 entries only.

The observed hierarchy provides catalog candidates in this form:

```text
education level / subject / publisher-series / grade / textbook file
```

Metadata extracted from paths is staged and normalized; it is not authoritative until
the catalog import validates the required fields.

## Initial pilot: primary-school English FLTRP/外研社

| Series directory | Start grade | Named editor | Complete PDFs | Approx. size |
|---|---|---|---:|---:|
| 外研社版（一年级起点）（主编：陈琳） | Grade 1 | 陈琳 | 12 | 247 MiB |
| 外研社版（三年级起点）（主编：刘兆义） | Grade 3 | 刘兆义 | 8 | 124 MiB |
| 外研社版（三年级起点）（主编：桂诗春） | Grade 3 | 桂诗春 | 8 | 141 MiB |
| 外研社版（三年级起点）（主编：陈琳） | Grade 3 | 陈琳 | 8 | 193 MiB |

Total: 36 complete PDFs, approximately 705 MiB.

Publisher alone is not a stable edition key: `start_grade`, `editor`, `grade` and
`term` must participate in catalog identity/display metadata.

## Import implications

- Exclude `.git`, `.cache` and hidden directories.
- Treat a regular `.pdf` as one Book edition/volume candidate unless an approved
  manifest groups split parts.
- Preserve the original Unicode title for display and maintain normalized search keys.
- Parse education level and subject from parent directories.
- Parse publisher/series, start grade and editor from the series directory where
  present.
- Parse grade and upper/lower term from the filename, but quarantine conflicts between
  directory and filename metadata.
- Generate stable IDs from approved catalog identity, not absolute mount paths.
- The first golden-set book is
  `外研社版（三年级起点）（主编：陈琳）/义务教育教科书·英语（三年级起点）三年级上册.pdf`.
  Catalog implementation still covers all four pilot series.

## Deferred inventory work

- PDF page counts, encryption and extraction-confidence distribution.
- Cover availability and ISBN extraction.
- Chapter/Unit heading extraction quality for primary-school English.
- Duplicate checksum and split-file analysis limited to the pilot family.
- Human-authored questions, expected answers and evidence labels for the selected
  golden-set volume.

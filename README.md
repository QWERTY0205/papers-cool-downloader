# Papers.cool Downloader

Download papers from [papers.cool](https://papers.cool/) by venue, year, and keyword.

This project provides:

- a CLI scraper for scripted workflows
- a lightweight Web App for form-based downloading

It fetches full venue pages from `papers.cool`, filters papers by keywords in title and/or abstract, and can package matched PDFs plus metadata into a ZIP archive.

## Features

- Discover available venues and years directly from the `papers.cool` homepage
- Crawl full venue listings with pagination, not just the first 25 entries
- Filter by keywords in title, abstract, or both
- Support `any` or `all` keyword matching
- Optional group filtering such as `Oral`, `Poster`, or `Spotlight`
- Export structured results as `JSON` or `CSV`
- Download matched PDFs
- Retry and throttle PDF downloads to reduce `429 Too Many Requests` failures from OpenReview
- Web UI that returns a ready-to-download ZIP bundle

## Project Structure

```text
papers-cool-downloader/
├── .gitignore
├── LICENSE
├── README.md
├── requirements.txt
├── scraper.py
└── webapp.py
```

## Requirements

- Python 3.10+
- `requests`

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## CLI Usage

List supported venues and years:

```bash
python3 scraper.py --list-venues
```

Filter papers from `ICML 2025` by keyword:

```bash
python3 scraper.py \
  --venue ICML \
  --year 2025 \
  --keyword diffusion
```

Filter a subgroup and download PDFs:

```bash
python3 scraper.py \
  --venue ICML.2025 \
  --group Oral \
  --keyword scaling \
  --download-pdf \
  --pdf-dir downloads/icml_scaling
```

Require all keywords to match:

```bash
python3 scraper.py \
  --venue NeurIPS \
  --year 2025 \
  --keyword diffusion \
  --keyword video \
  --match-mode all
```

### Useful CLI Options

- `--venue`: venue name like `ICML` or full venue path like `ICML.2025`
- `--year`: required when `--venue` is a short conference name
- `--keyword`: repeatable keyword argument
- `--match-mode any|all`
- `--search-fields title|abstract|both`
- `--group`: optional venue subgroup
- `--format json|csv`
- `--download-pdf`
- `--pdf-dir`

## Web App

Start the local server:

```bash
python3 webapp.py
```

Open:

```text
http://127.0.0.1:8123
```

The form supports:

- venue
- year
- keywords
- optional group
- match mode
- search scope

On submit, the app generates and downloads a ZIP archive.

## ZIP Contents

Each generated ZIP may include:

- `results.json`
- `results.csv`
- `summary.json`
- `download_report.json`
- `pdfs/*.pdf`

## Handling OpenReview 429 Errors

Many venue PDFs are hosted on `openreview.net`, which may rate-limit repeated downloads.

This project reduces failures by:

- downloading PDFs sequentially
- adding request delays
- retrying with exponential backoff
- recording failed downloads instead of aborting the whole task

Failure reports are written to:

- CLI mode: `<pdf_dir>/download_failures.json`
- Web mode: `download_report.json` inside the ZIP

## Notes

- Results depend on the current structure and availability of `papers.cool`
- Some venue pages may change over time
- Some PDFs may still fail due to temporary upstream rate limits or access restrictions

## License

MIT

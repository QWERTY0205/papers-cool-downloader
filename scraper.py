#!/usr/bin/env python3
import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote, urljoin

import requests


BASE_URL = "https://papers.cool"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT = 30


@dataclass
class Paper:
    paper_id: str
    venue_page: str
    venue_label: str = ""
    group: str = ""
    title: str = ""
    abstract: str = ""
    authors: List[str] = field(default_factory=list)
    venue_paper_url: str = ""
    source_url: str = ""
    pdf_url: str = ""
    keywords: List[str] = field(default_factory=list)


def normalize_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "result"


class VenueIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.venue_pages: Dict[str, List[int]] = {}

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        attrs = dict(attrs)
        href = attrs.get("href", "")
        match = re.match(r"^/venue/([A-Za-z0-9\-]+)\.(\d{4})$", href)
        if not match:
            return
        venue, year = match.group(1), int(match.group(2))
        self.venue_pages.setdefault(venue, [])
        if year not in self.venue_pages[venue]:
            self.venue_pages[venue].append(year)


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_text(text)


def derive_subject_fields(paper: "Paper") -> None:
    label = paper.group
    if not label:
        return
    if " - " in label:
        venue_label, _, group = label.partition(" - ")
        paper.venue_label = venue_label.strip()
        paper.group = group.strip()
    else:
        paper.venue_label = label.strip()


def parse_venue_page(page_url: str, html: str) -> List[Paper]:
    papers: List[Paper] = []
    block_pattern = re.compile(
        r'<div id="(?P<paper_id>[^"]+)" class="panel paper"(?P<attrs>[^>]*)>(?P<body>.*?)<hr id="fold-[^"]+"[^>]*></hr>\s*</div>',
        re.DOTALL,
    )
    for match in block_pattern.finditer(html):
        attrs = match.group("attrs") or ""
        keyword_match = re.search(r'keywords="([^"]*)"', attrs)
        paper = Paper(
            paper_id=match.group("paper_id"),
            venue_page=page_url,
            keywords=[
                kw.strip()
                for kw in keyword_match.group(1).split(",")
                if kw.strip()
            ] if keyword_match else [],
        )
        body = match.group("body")

        title_match = re.search(
            r'<a id="title-[^"]+" class="title-link[^"]*" href="([^"]+)"[^>]*>(.*?)</a>',
            body,
            re.DOTALL,
        )
        if title_match:
            paper.venue_paper_url = urljoin(BASE_URL, title_match.group(1))
            paper.title = strip_tags(title_match.group(2))

        source_match = re.search(
            r'<h2 class="title">\s*<a href="(https?://[^"]+)"',
            body,
            re.DOTALL,
        )
        if source_match:
            paper.source_url = source_match.group(1)

        pdf_match = re.search(r'class="title-pdf[^"]*"[^>]*data="([^"]+)"', body)
        if pdf_match:
            paper.pdf_url = pdf_match.group(1)

        abstract_match = re.search(
            r'<p id="summary-[^"]+" class="summary[^"]*">(.*?)</p>',
            body,
            re.DOTALL,
        )
        if abstract_match:
            paper.abstract = strip_tags(abstract_match.group(1))

        paper.authors = [
            strip_tags(author)
            for author in re.findall(r'<a class="author[^"]*"[^>]*>(.*?)</a>', body, re.DOTALL)
            if strip_tags(author)
        ]

        subject_match = re.search(
            r'<p id="subjects-[^"]+" class="metainfo subjects">.*?<a class="subject-1"[^>]*>(.*?)</a>',
            body,
            re.DOTALL,
        )
        if subject_match:
            paper.group = strip_tags(subject_match.group(1))
            derive_subject_fields(paper)

        papers.append(paper)
    return papers


def fetch_text(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def list_available_venues(session: requests.Session) -> Dict[str, List[int]]:
    parser = VenueIndexParser()
    parser.feed(fetch_text(session, BASE_URL + "/"))
    for years in parser.venue_pages.values():
        years.sort(reverse=True)
    return parser.venue_pages


def resolve_venue_path(session: requests.Session, venue: str, year: Optional[int]) -> str:
    if re.fullmatch(r"[A-Za-z0-9\-]+\.\d{4}", venue):
        return venue
    venues = list_available_venues(session)
    years = venues.get(venue)
    if not years:
        known = ", ".join(sorted(venues))
        raise ValueError(f"Venue '{venue}' not found on homepage index. Known venues: {known}")
    resolved_year = year if year is not None else max(years)
    if resolved_year not in years:
        available = ", ".join(str(item) for item in years)
        raise ValueError(f"Venue '{venue}' does not expose year {resolved_year}. Available years: {available}")
    return f"{venue}.{resolved_year}"


def fetch_venue_papers(session: requests.Session, venue_path: str, group: Optional[str]) -> List[Paper]:
    url = f"{BASE_URL}/venue/{venue_path}"
    query_parts = []
    if group:
        query_parts.append(f"group={quote(group, safe='')}")

    papers_by_id: Dict[str, Paper] = {}
    skip = 0
    show = 100

    while True:
        page_query = list(query_parts)
        page_query.append(f"skip={skip}")
        page_query.append(f"show={show}")
        page_url = f"{url}?{'&'.join(page_query)}"
        page_papers = parse_venue_page(page_url, fetch_text(session, page_url))
        if not page_papers:
            break
        for paper in page_papers:
            papers_by_id.setdefault(paper.paper_id, paper)
        if len(page_papers) < show:
            break
        skip += show

    papers = list(papers_by_id.values())
    if not papers:
        raise ValueError(f"No papers parsed from {url}")
    for paper in papers:
        if not paper.venue_label:
            paper.venue_label = venue_path
        if group and not paper.group:
            paper.group = group
    return papers


def paper_matches(paper: Paper, keywords: List[str], match_mode: str, search_fields: str) -> bool:
    if not keywords:
        return True
    parts: List[str] = []
    if search_fields in {"title", "both"}:
        parts.append(paper.title)
    if search_fields in {"abstract", "both"}:
        parts.append(paper.abstract)
    haystack = normalize_text(" ".join(parts)).lower()
    checks = [keyword.lower() in haystack for keyword in keywords]
    return all(checks) if match_mode == "all" else any(checks)


def export_json(path: Path, papers: List[Paper]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(paper) for paper in papers]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def export_csv(path: Path, papers: List[Paper]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "paper_id",
        "venue_page",
        "venue_label",
        "group",
        "title",
        "abstract",
        "authors",
        "venue_paper_url",
        "source_url",
        "pdf_url",
        "keywords",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for paper in papers:
            row = asdict(paper)
            row["authors"] = "; ".join(paper.authors)
            row["keywords"] = "; ".join(paper.keywords)
            writer.writerow(row)


def search_papers(
    venue: str,
    year: Optional[int] = None,
    keywords: Optional[List[str]] = None,
    match_mode: str = "any",
    search_fields: str = "both",
    group: Optional[str] = None,
) -> tuple[str, List[Paper], List[Paper]]:
    keywords = keywords or []
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    venue_path = resolve_venue_path(session, venue, year)
    papers = fetch_venue_papers(session, venue_path, group)
    filtered = [
        paper
        for paper in papers
        if paper_matches(paper, keywords, match_mode, search_fields)
    ]
    return venue_path, papers, filtered


def sanitize_filename(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180] or "paper"


def _retry_after_seconds(response: requests.Response) -> Optional[float]:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None


def download_pdfs(
    session: requests.Session,
    papers: List[Paper],
    pdf_dir: Path,
    *,
    delay_seconds: float = 1.5,
    max_retries: int = 5,
) -> List[Dict[str, str]]:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    failures: List[Dict[str, str]] = []
    for index, paper in enumerate(papers, start=1):
        if not paper.pdf_url:
            continue
        filename = f"{index:03d}_{sanitize_filename(paper.title)}.pdf"
        target = pdf_dir / filename
        last_error = ""
        for attempt in range(max_retries + 1):
            try:
                headers = {"Referer": paper.source_url or paper.venue_paper_url or BASE_URL}
                with session.get(paper.pdf_url, timeout=TIMEOUT, stream=True, headers=headers) as response:
                    if response.status_code == 429:
                        wait_seconds = _retry_after_seconds(response)
                        if wait_seconds is None:
                            wait_seconds = max(delay_seconds * (2 ** attempt), 5.0)
                        last_error = f"429 Too Many Requests, retry after {wait_seconds:.1f}s"
                        if attempt >= max_retries:
                            break
                        time.sleep(wait_seconds)
                        continue
                    response.raise_for_status()
                    with target.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=1024 * 64):
                            if chunk:
                                handle.write(chunk)
                last_error = ""
                break
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt >= max_retries:
                    break
                time.sleep(max(delay_seconds * (2 ** attempt), 5.0))
        if last_error:
            failures.append(
                {
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "pdf_url": paper.pdf_url,
                    "error": last_error,
                }
            )
            if target.exists():
                target.unlink()
        time.sleep(delay_seconds)
    return failures


def build_output_path(
    venue_path: str,
    keywords: List[str],
    output_format: str,
    output_path: Optional[str],
) -> Path:
    if output_path:
        return Path(output_path)
    keyword_part = slugify("-".join(keywords) if keywords else "all")
    return Path("outputs") / f"{slugify(venue_path)}_{keyword_part}.{output_format}"


def print_summary(papers: List[Paper], max_items: int) -> None:
    if not papers:
        print("No matching papers found.")
        return
    for index, paper in enumerate(papers[:max_items], start=1):
        authors = ", ".join(paper.authors[:5])
        if len(paper.authors) > 5:
            authors += ", ..."
        print(f"{index}. {paper.title}")
        print(f"   venue: {paper.venue_label or '-'} | group: {paper.group or '-'}")
        print(f"   authors: {authors or '-'}")
        print(f"   pdf: {paper.pdf_url or '-'}")
        print(f"   page: {paper.venue_paper_url or '-'}")
    remaining = len(papers) - min(len(papers), max_items)
    if remaining > 0:
        print(f"... and {remaining} more papers. See the saved output file for the full list.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape papers.cool venue pages and filter papers by keywords in title/abstract."
    )
    parser.add_argument("--venue", help="Venue name like ICML or full venue path like ICML.2025")
    parser.add_argument("--year", type=int, help="Year to use when --venue is a bare conference name")
    parser.add_argument("--keyword", action="append", default=[], help="Keyword or phrase to match. Repeat this flag for multiple keywords.")
    parser.add_argument("--match-mode", choices=["any", "all"], default="any", help="Whether any keyword or all keywords must match.")
    parser.add_argument("--search-fields", choices=["title", "abstract", "both"], default="both", help="Where to search for keywords.")
    parser.add_argument("--group", help="Optional venue subgroup, for example Oral")
    parser.add_argument("--output", help="Output file path. Defaults to outputs/<venue>_<keywords>.<format>")
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Output file format")
    parser.add_argument("--download-pdf", action="store_true", help="Download matched PDFs")
    parser.add_argument("--pdf-dir", help="Directory for downloaded PDFs")
    parser.add_argument("--list-venues", action="store_true", help="List venues discovered on the homepage index")
    parser.add_argument("--max-print", type=int, default=20, help="Maximum matched papers to print to stdout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    try:
        if args.list_venues:
            venues = list_available_venues(session)
            for venue, years in sorted(venues.items()):
                print(f"{venue}: {', '.join(str(year) for year in years)}")
            return 0

        if not args.venue:
            raise ValueError("--venue is required unless --list-venues is used")

        venue_path = resolve_venue_path(session, args.venue, args.year)
        papers = fetch_venue_papers(session, venue_path, args.group)
        filtered = [
            paper
            for paper in papers
            if paper_matches(paper, args.keyword, args.match_mode, args.search_fields)
        ]

        output_path = build_output_path(venue_path, args.keyword, args.format, args.output)
        if args.format == "json":
            export_json(output_path, filtered)
        else:
            export_csv(output_path, filtered)

        failures: List[Dict[str, str]] = []
        if args.download_pdf:
            pdf_dir = Path(args.pdf_dir) if args.pdf_dir else output_path.with_suffix("")
            failures = download_pdfs(session, filtered, pdf_dir)
            if failures:
                report_path = pdf_dir / "download_failures.json"
                report_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"Venue page: {BASE_URL}/venue/{venue_path}")
        if args.group:
            print(f"Group: {args.group}")
        print(f"Matched papers: {len(filtered)} / {len(papers)}")
        print(f"Saved results to: {output_path}")
        if args.download_pdf:
            print(f"PDF directory: {pdf_dir}")
            if failures:
                print(f"PDF failures: {len(failures)} (see {pdf_dir / 'download_failures.json'})")
        print_summary(filtered, args.max_print)
        return 0
    except requests.HTTPError as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

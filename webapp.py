#!/usr/bin/env python3
import io
import json
import os
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

import requests

from scraper import (
    USER_AGENT,
    download_pdfs,
    export_csv,
    export_json,
    list_available_venues,
    search_papers,
    slugify,
)


HOST = "0.0.0.0"
PORT = 8123


def build_index_html(venues: dict[str, list[int]]) -> str:
    options = "\n".join(
        f'<option value="{venue}">{venue} ({", ".join(str(year) for year in years[:5])})</option>'
        for venue, years in sorted(venues.items())
    )
    venues_json = json.dumps(venues, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Papers.cool Downloader</title>
  <style>
    :root {{
      --bg: #f3efe6;
      --panel: rgba(255,255,255,0.88);
      --ink: #1c1b18;
      --muted: #666055;
      --accent: #165dff;
      --accent-2: #0f3fae;
      --line: rgba(28,27,24,0.12);
      --ok: #0f766e;
      --error: #b42318;
      --shadow: 0 20px 60px rgba(0,0,0,0.10);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(22,93,255,0.12), transparent 30%),
        radial-gradient(circle at bottom right, rgba(210,140,60,0.16), transparent 25%),
        linear-gradient(180deg, #f8f5ee 0%, var(--bg) 100%);
      min-height: 100vh;
    }}
    .wrap {{
      max-width: 920px;
      margin: 0 auto;
      padding: 48px 20px 72px;
    }}
    .hero {{
      margin-bottom: 24px;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: clamp(32px, 6vw, 56px);
      line-height: 0.95;
      letter-spacing: -0.04em;
    }}
    .sub {{
      margin: 0;
      max-width: 720px;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.6;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
      overflow: hidden;
    }}
    form {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
      padding: 24px;
    }}
    .full {{ grid-column: 1 / -1; }}
    label {{
      display: block;
      margin-bottom: 8px;
      font-size: 14px;
      font-weight: 700;
    }}
    input, textarea, select, button {{
      width: 100%;
      border-radius: 14px;
      border: 1px solid rgba(28,27,24,0.14);
      font: inherit;
    }}
    input, textarea, select {{
      padding: 14px 16px;
      background: rgba(255,255,255,0.82);
    }}
    textarea {{
      min-height: 120px;
      resize: vertical;
      line-height: 1.5;
    }}
    button {{
      padding: 16px 18px;
      border: 0;
      background: linear-gradient(135deg, var(--accent) 0%, var(--accent-2) 100%);
      color: white;
      font-weight: 700;
      cursor: pointer;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      padding: 0 24px 24px;
      color: var(--muted);
      font-size: 13px;
    }}
    .chip {{
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(28,27,24,0.05);
      border: 1px solid rgba(28,27,24,0.08);
    }}
    #status {{
      margin-top: 18px;
      padding: 16px 18px;
      border-radius: 16px;
      background: rgba(255,255,255,0.7);
      border: 1px solid var(--line);
      color: var(--muted);
      min-height: 56px;
      white-space: pre-wrap;
    }}
    #status.ok {{ color: var(--ok); }}
    #status.error {{ color: var(--error); }}
    .footer {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    @media (max-width: 720px) {{
      form {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>Papers.cool<br>Auto Downloader</h1>
      <p class="sub">输入会议、年份和关键词，自动抓取指定会议页，筛选命中论文，并下载包含结果清单和 PDF 的 ZIP。</p>
    </div>
    <div class="panel">
      <form id="download-form">
        <div>
          <label for="venue">会议</label>
          <input id="venue" name="venue" list="venue-list" placeholder="例如 ICML / CVPR / NeurIPS" required>
          <datalist id="venue-list">
            {options}
          </datalist>
        </div>
        <div>
          <label for="year">年份</label>
          <input id="year" name="year" type="number" min="2000" max="2100" placeholder="例如 2025" required>
        </div>
        <div class="full">
          <label for="keywords">关键词</label>
          <textarea id="keywords" name="keywords" placeholder="每行一个关键词，或逗号分隔。例如：&#10;diffusion&#10;video"></textarea>
        </div>
        <div>
          <label for="group">分组</label>
          <input id="group" name="group" placeholder="可留空，例如 Oral / Poster / Spotlight">
        </div>
        <div>
          <label for="match_mode">匹配逻辑</label>
          <select id="match_mode" name="match_mode">
            <option value="any">任意关键词命中</option>
            <option value="all">全部关键词命中</option>
          </select>
        </div>
        <div>
          <label for="search_fields">搜索范围</label>
          <select id="search_fields" name="search_fields">
            <option value="both">标题 + 摘要</option>
            <option value="title">仅标题</option>
            <option value="abstract">仅摘要</option>
          </select>
        </div>
        <div class="full">
          <button id="submit-btn" type="submit">生成并下载 ZIP</button>
        </div>
      </form>
      <div class="meta">
        <div class="chip">标准库 HTTP 服务</div>
        <div class="chip">会议索引数: {len(venues)}</div>
        <div class="chip">ZIP 内含结果清单和 PDF</div>
      </div>
    </div>
    <div id="status">等待提交。</div>
    <div class="footer">如果 OpenReview 对部分 PDF 限流，ZIP 也会正常生成，失败项会记录在 `download_report.json`。</div>
  </div>
  <script>
    const venueMap = {venues_json};
    const form = document.getElementById('download-form');
    const status = document.getElementById('status');
    const button = document.getElementById('submit-btn');
    const venueInput = document.getElementById('venue');
    const yearInput = document.getElementById('year');

    venueInput.addEventListener('change', () => {{
      const years = venueMap[venueInput.value];
      if (years && years.length && !yearInput.value) {{
        yearInput.value = years[0];
      }}
    }});

    form.addEventListener('submit', async (event) => {{
      event.preventDefault();
      button.disabled = true;
      status.className = '';
      status.textContent = '正在抓取会议页并打包下载，匹配数量多时可能需要较长时间。';
      try {{
        const response = await fetch('/download', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' }},
          body: new URLSearchParams(new FormData(form)),
        }});
        if (!response.ok) {{
          throw new Error(await response.text());
        }}
        const blob = await response.blob();
        const disposition = response.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="([^"]+)"/);
        const filename = match ? match[1] : 'papers_cool_results.zip';
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        status.className = 'ok';
        status.textContent = 'ZIP 已生成并开始下载。';
      }} catch (error) {{
        status.className = 'error';
        status.textContent = error.message || String(error);
      }} finally {{
        button.disabled = false;
      }}
    }});
  </script>
</body>
</html>"""


def parse_keywords(raw: str) -> list[str]:
    raw = (raw or "").replace("，", ",")
    items = []
    for chunk in raw.splitlines():
        for item in chunk.split(","):
            item = item.strip()
            if item:
                items.append(item)
    return items


def build_archive(
    venue: str,
    year: int,
    keywords: list[str],
    group: str,
    match_mode: str,
    search_fields: str,
) -> tuple[str, bytes]:
    venue_path, papers, filtered = search_papers(
        venue=venue,
        year=year,
        keywords=keywords,
        match_mode=match_mode,
        search_fields=search_fields,
        group=group or None,
    )
    if not filtered:
        raise ValueError(f"没有匹配结果。会议 {venue_path} 共 {len(papers)} 篇论文，关键词未命中。")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    with tempfile.TemporaryDirectory(prefix="papers-cool-") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        export_json(tmp_dir / "results.json", filtered)
        export_csv(tmp_dir / "results.csv", filtered)
        failures = download_pdfs(session, filtered, tmp_dir / "pdfs")
        (tmp_dir / "download_report.json").write_text(
            json.dumps(
                {
                    "downloaded_count": len(filtered) - len(failures),
                    "failed_count": len(failures),
                    "failures": failures,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        summary = {
            "venue": venue,
            "year": year,
            "resolved_venue_path": venue_path,
            "group": group or "",
            "keywords": keywords,
            "match_mode": match_mode,
            "search_fields": search_fields,
            "matched_count": len(filtered),
            "total_count": len(papers),
            "downloaded_pdf_count": len(filtered) - len(failures),
            "failed_pdf_count": len(failures),
        }
        (tmp_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        buffer = io.BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(tmp_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=path.relative_to(tmp_dir))
        buffer.seek(0)

    keyword_part = slugify("-".join(keywords) if keywords else "all")
    group_part = f"_{slugify(group)}" if group else ""
    filename = f"{slugify(venue)}_{year}{group_part}_{keyword_part}.zip"
    return filename, buffer.getvalue()


class PapersCoolHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        venues = list_available_venues(session)
        body = build_index_html(venues).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/download":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length).decode("utf-8")
            form = parse_qs(raw_body, keep_blank_values=True)

            venue = form.get("venue", [""])[0].strip()
            year_raw = form.get("year", [""])[0].strip()
            group = form.get("group", [""])[0].strip()
            match_mode = form.get("match_mode", ["any"])[0].strip() or "any"
            search_fields = form.get("search_fields", ["both"])[0].strip() or "both"
            keywords = parse_keywords(form.get("keywords", [""])[0])

            if not venue:
                raise ValueError("会议不能为空。")
            if not year_raw.isdigit():
                raise ValueError("年份必须是数字。")
            year = int(year_raw)
            if match_mode not in {"any", "all"}:
                raise ValueError("非法的匹配逻辑。")
            if search_fields not in {"title", "abstract", "both"}:
                raise ValueError("非法的搜索范围。")

            filename, payload = build_archive(
                venue=venue,
                year=year,
                keywords=keywords,
                group=group,
                match_mode=match_mode,
                search_fields=search_fields,
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            message = str(exc).encode("utf-8")
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    port = int(os.environ.get("PAPERS_COOL_WEBAPP_PORT", PORT))
    server = ThreadingHTTPServer((HOST, port), PapersCoolHandler)
    print(f"Serving on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

# Papers.cool Downloader

一个零依赖前端、Python 后端的小工具，用于从 `papers.cool` 抓取指定会议年份的论文，按标题和摘要中的关键词过滤，并自动下载结果。

项目包含两种使用方式：

- CLI：适合批量抓取、脚本化调用
- Web App：打开网页表单，输入会议、年份、关键词后直接下载 ZIP

## 功能

- 自动读取 `papers.cool` 首页支持的会议和年份
- 自动翻页抓取完整会议列表，不只拿默认前 25 篇
- 支持关键词匹配标题、摘要，或两者同时匹配
- 支持 `any` / `all` 两种关键词逻辑
- 支持分组过滤，如 `Oral`、`Poster`、`Spotlight`
- 可导出 `JSON` / `CSV`
- 可自动下载 PDF
- 对 OpenReview 的 `429 Too Many Requests` 做限速和退避重试
- Web App 下载 ZIP，包内包含结果文件和已下载 PDF

## 目录结构

```text
papers-cool-downloader/
├── README.md
├── requirements.txt
├── scraper.py
└── webapp.py
```

## 安装

建议使用 Python 3.10+。

```bash
cd /data/papers-cool-downloader
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果你不想创建虚拟环境，只要本机有 `requests` 也可以直接运行。

## CLI 用法

列出支持的会议和年份：

```bash
python3 scraper.py --list-venues
```

抓取 `ICML 2025` 中标题或摘要包含 `diffusion` 的论文：

```bash
python3 scraper.py \
  --venue ICML \
  --year 2025 \
  --keyword diffusion
```

抓取 `ICML.2025` 的 `Oral` 分组，并下载 PDF：

```bash
python3 scraper.py \
  --venue ICML.2025 \
  --group Oral \
  --keyword scaling \
  --download-pdf \
  --pdf-dir downloads/icml_scaling
```

多关键词全部命中：

```bash
python3 scraper.py \
  --venue NeurIPS \
  --year 2025 \
  --keyword diffusion \
  --keyword video \
  --match-mode all
```

## Web App

启动服务：

```bash
cd /data/papers-cool-downloader
python3 webapp.py
```

默认访问：

```text
http://127.0.0.1:8123
```

页面支持输入：

- 会议
- 年份
- 关键词
- 分组
- 匹配逻辑
- 搜索范围

提交后会自动下载一个 ZIP。

ZIP 内包含：

- `results.json`
- `results.csv`
- `summary.json`
- `download_report.json`
- `pdfs/*.pdf`

## 关于 429 限流

PDF 一般来自 `openreview.net`。如果短时间下载过多论文，OpenReview 可能返回 `429 Too Many Requests`。

当前实现会：

- 串行下载 PDF
- 自动限速
- 自动指数退避重试
- 对最终失败的 PDF 记录到报告文件中，而不是让整次任务失败

CLI 模式下，失败记录会写到：

```text
<pdf_dir>/download_failures.json
```

Web App 模式下，失败记录会写到 ZIP 内的：

```text
download_report.json
```

## GitHub 发布建议

如果你要把这个项目发到 GitHub，建议仓库名：

```text
papers-cool-downloader
```

## License

按你的需要补充。当前仓库未附带开源许可证。

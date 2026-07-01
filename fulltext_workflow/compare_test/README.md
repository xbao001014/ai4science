# Isolated channel comparison: JATS vs PyMuPDF vs MinerU

Does **not** modify `kg_fulltext.db` or main `output/`.

## Prerequisites (project venv)

```bash
pip install scansci-pdf pymupdf mineru[core]
```

## Usage

```bash
cd fulltext_workflow

# 1) Download PDFs (ScanSci, already done if manifest exists)
..\.venv\Scripts\python.exe -m compare_test.compare download --limit 30

# 2) PyMuPDF channel LLM extraction
..\.venv\Scripts\python.exe -m compare_test.compare extract --limit 30

# 3) MinerU channel (slow on CPU — ~2-5 min/paper)
..\.venv\Scripts\python.exe -m compare_test.compare extract-mineru --limit 30

# 4) Three-way report
..\.venv\Scripts\python.exe -m compare_test.compare compare --limit 30
```

## Outputs

| Path | Content |
|------|---------|
| `output/comparison_report_mineru.md` | JATS vs PyMuPDF vs MinerU report |
| `output/comparison_summary_mineru.json` | Structured comparison data |
| `cache/mineru_extractions.json` | MinerU LLM results (resumable) |
| `mineru_output/{pmid}/` | MinerU markdown cache per paper |

## Channels

| Channel | Parser | Granularity |
|---------|--------|-------------|
| JATS | Europe PMC fullTextXML | `fulltext` |
| PyMuPDF | fitz + regex sections | `pdf` |
| MinerU | layout Markdown + heading split | `mineru_pdf` |

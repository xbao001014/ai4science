# Design: IEEE / Elsevier Publisher Direct PDF (Campus IP)

**Date:** 2026-08-10  
**Status:** Approved  
**Depends on:** `fetcher/scansci_fetcher.py`, `fetcher/fulltext_fetcher.py` (Tier 2 PDF path), `config.py`, ScanSci `oa_first` fallback  
**Related PMIDs (manual acceptance):** `37030860` (IEEE), `36682215` / `34275655` (Elsevier); also useful: `32881682` (IEEE, local LibGen PDF already present)

## Problem

部分病理 AI 论文的全文只在订阅出版社侧可下（IEEE Xplore `10.1109/`、Elsevier/ScienceDirect `10.1016/`）。当前 Tier 2 仅走 ScanSci OA 赛跑（Unpaywall / Crossref / EuropePMC 等）；对 **closed** 订阅文会超时或失败，最终 `unavailable` / 长期 `jats_unavailable`，只能摘要抽取。

校园网或机构 VPN 下本机 IP 往往已具备出版社直链下载权限，但流水线未使用该渠道。ScanSci 虽能识别 IEEE/Elsevier DOI 前缀，直连工具映射仍只有 Crossref/Unpaywall，且内部 `trust_env=False`，不利于走系统代理。

## Goals

1. 在 **校园网 / 机构 VPN IP 直通**（无需 CARSI 浏览器登录）前提下，可下载 IEEE 与 Elsevier PDF。
2. **默认关闭**；通过环境变量显式打开，避免非校园网环境对订阅域名大量超时。
3. 接入现有 `download_pdf` → MinerU 路径，不新增周常步骤；打开开关后 `fetch-fulltext` 自动受益。
4. 直链失败时静默回退 ScanSci，不破坏现有冷却 / 重试语义。

## Non-goals

- CARSI / Shibboleth / 机构账号交互登录。
- Elsevier / IEEE 官方 API Key 通道。
- 修改 `scansci_pdf` site-packages 或 upstream publisher 表。
- Sci-Hub / 其它灰产源。
- 默认对全库开启；Gap UI 暴露开关（先 env / `.env`）。
- 改变 `full_text_status` 状态机或 PDF attempt 冷却规则。

## Constraints (from brainstorm)

| Item | Choice |
|------|--------|
| Access | A1 — campus / VPN IP passthrough |
| Rollout | B2 — opt-in env flag, default off |
| Approach | Wrap in-repo publisher direct before ScanSci |

## Approach (chosen)

**方案 1：本仓库包一层 publisher direct。**

在 `fetcher/scansci_fetcher.download_pdf` 中，当 `FULLTEXT_PUBLISHER_DIRECT` 为真且 DOI 前缀匹配时，先调用本仓库 `fetcher/publisher_direct.py`；失败再调用现有 ScanSci。

Rejected:

- **改 scansci_pdf publisher 表** — 升级易丢；`trust_env=False` 与校园代理不友好。
- **仅独立 CLI、不进主队列** — 与「打开开关后主流程可用」不一致。

## Call flow

```
download_pdf(doi, pmid)
  ├─ local cache hit → success (source=local_cache)
  ├─ if FULLTEXT_PUBLISHER_DIRECT and doi prefix in {10.1109/, 10.1016/}:
  │     try publisher_direct.download(doi, output_path)
  │       ├─ success → return (source=ieee_direct | elsevier_direct)
  │       └─ fail → fall through
  └─ scansci_pdf.sources.download(..., strategy=SCANSCI_STRATEGY, scihub_enabled=False)
```

Tier 1 JATS / Tier 2 MinerU / cooldown 逻辑不变；本设计只增强 PDF 字节来源。

## Publisher strategies

Shared rules:

- `requests.Session(trust_env=True)` so system HTTP(S)_PROXY / VPN-related env is honored.
- Timeout ~20–30s; stream download; require PDF magic (`%PDF`) / content-type check before rename into `raw/pdfs/{pmid}_{doi_safe}.pdf`.
- HTML paywall / login / interstitial → treat as failure (do not write success).
- Resolve via `https://doi.org/{doi}` redirects first when needed.

### IEEE (`10.1109/…`)

1. Resolve DOI → ieeexplore landing (or stamp URL).
2. Extract `arnumber` (query param, HTML, or redirect).
3. Candidate PDF URLs (try in order), e.g. stamp/stampPDF patterns used by Xplore.
4. On valid PDF → `source=ieee_direct`.

### Elsevier (`10.1016/…`)

1. Resolve DOI → ScienceDirect / Cell / other Elsevier host.
2. Prefer `citation_pdf_url` meta, PII `pdfft` / `pdfft?isDTMRedir=true&download=true`, or publisher “Download PDF” href.
3. On valid PDF → `source=elsevier_direct`.

Implementation may tighten URL patterns after probing the three acceptance PMIDs on campus network; behavior contract is “valid PDF bytes or fail”, not a frozen URL list.

## Config / docs

| Name | Default | Meaning |
|------|---------|---------|
| `FULLTEXT_PUBLISHER_DIRECT` | `false` | Enable IEEE/Elsevier campus-IP direct before ScanSci |

- `config.py`: parse truthy env (`1`/`true`/`yes`/`on`).
- `.env.example` + `fulltext_workflow/SCRIPTS.md`: document flag and “requires campus/VPN IP”.

No new `main.py` subcommand required for MVP.

## Failure / status semantics

- Publisher direct miss → log at info/debug with reason; **do not** mark paper `unavailable` by itself.
- ScanSci still runs; final status remains existing Tier 2 rules.
- Successful direct download uses same cache path as ScanSci so MinerU and retry logic stay unchanged.

## Testing

**Unit (no network):**

- Flag off → `publisher_direct` not called.
- Prefix routing: `10.1109` → IEEE path, `10.1016` → Elsevier, other → skip.
- Non-PDF body rejected; atomic write not left as `.part` on failure.

**Manual (flag on + campus/VPN):**

| PMID | DOI prefix | Expect |
|------|------------|--------|
| 37030860 | IEEE | PDF downloaded, then MinerU → `pdf_available` if parse OK |
| 36682215 | Elsevier | same |
| 34275655 | Elsevier | same |
| flag off | any | identical to pre-change ScanSci-only behavior |

## Future work

- Optional CARSI cookie session for off-campus.
- Broader publishers (Wiley `10.1002/`, Springer `10.1007/`) behind the same flag or per-publisher flags.
- Gap UI checkbox for ops weekly jobs.

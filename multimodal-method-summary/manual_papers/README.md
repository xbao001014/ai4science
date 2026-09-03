# 多模态融合：手工补充论文全文

请将自动抓取失败的出版社正式版 PDF 放在本目录中。

## 命名规则

主文件统一命名为：

```text
{PMID}_{DOI中斜杠替换为下划线}.pdf
```

要求：

- PMID 放在最前面，保持纯数字；
- DOI 保持原有字母、数字和点号，仅将 `/` 替换为 `_`；
- 扩展名使用小写 `.pdf`；
- 不添加空格、中文标题、`(1)`、`final` 等额外后缀；
- 如果另有补充材料，使用同一主文件名并追加 `_supplement.pdf`。

## 当前待补（2026-08-24）

1. Quilt-1M: One Million Image-Text Pairs for Histopathology

```text
38742142_10.5281_zenodo.5143773.pdf
```

2. Vision-Language Transformer for Interpretable Pathology Visual Question Answering

```text
35358054_10.1109_JBHI.2022.3163751.pdf
```

## 后续处理

文件放入后，将依次核验：PDF 文件头、首页题名、PMID/DOI、页数和文本可提取性。核验通过后再用于生成方法总结，不会仅依据文件名认定论文身份。

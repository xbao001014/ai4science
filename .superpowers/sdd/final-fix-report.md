# Final-review fixes — WSI assume annotations disclosure

**Status:** DONE

## Summary

Fixed final-review disclosure gaps without touching `assessment.py` scoring. Observed annotations (raw>0) were mislabeled as full「接口实测 / API-verified」; UI, prompts, and PIPELINE now state that under the temporary flag all `required_annotations` score at `has_wsi`, raw_observed may be sparse, and disclosure is mandatory.

## Files changed

- `fulltext_workflow/gap_ui.py` — expander labels + caption
- `fulltext_workflow/idea_agent.py` — Generator §9 + Critic rules
- `fulltext_workflow/PIPELINE.md` — 临时策略 paragraph

## Tests

```
pytest tests/test_feasibility_sparse_annotation_floor.py tests/test_feasibility.py -v
24 passed in 2.68s
```

## Concerns

None. No commit per instructions.

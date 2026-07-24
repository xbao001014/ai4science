"""Helpers for keeping Streamlit tabs stable across reruns."""

from __future__ import annotations

import json
import re


def normalize_tab_label(label: str) -> str:
    """Slugify ASCII tab labels (legacy). Prefer explicit slug maps for Chinese UI."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower())
    return slug.strip("-")


def build_tab_sync_script(
    tab_labels: list[str],
    requested_tab: str,
    *,
    slug_by_label: dict[str, str] | None = None,
) -> str:
    labels_json = json.dumps(tab_labels, ensure_ascii=False)
    requested_json = json.dumps(requested_tab, ensure_ascii=False)
    slug_map_json = json.dumps(slug_by_label or {}, ensure_ascii=False)
    return f"""
<script>
(() => {{
  const tabLabels = {labels_json};
  const requestedTab = {requested_json};
  const slugByLabel = {slug_map_json};
  const slugify = (label) => {{
    if (slugByLabel && Object.prototype.hasOwnProperty.call(slugByLabel, label)) {{
      return slugByLabel[label];
    }}
    return label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  }};
  const parentDoc = window.parent.document;
  const parentWin = window.parent;
  const queryKey = "main_tab";

  function findTargetTablist() {{
    const tablists = Array.from(parentDoc.querySelectorAll('div[role="tablist"]'));
    return tablists.find((tablist) => {{
      const labels = Array.from(tablist.querySelectorAll('button[role="tab"]')).map((btn) => btn.innerText.trim());
      return tabLabels.every((label) => labels.includes(label));
    }});
  }}

  function syncQueryParam(slug) {{
    try {{
      const url = new URL(parentWin.location.href);
      url.searchParams.set(queryKey, slug);
      parentWin.history.replaceState({{}}, "", url.toString());
    }} catch (err) {{
      console.debug("tab sync replaceState failed", err);
    }}
  }}

  function syncSelectedTab(tablist) {{
    const selected = tablist.querySelector('button[role="tab"][aria-selected="true"]');
    if (!selected) return;
    syncQueryParam(slugify(selected.innerText.trim()));
  }}

  function attachListeners(tablist) {{
    const buttons = Array.from(tablist.querySelectorAll('button[role="tab"]'));
    buttons.forEach((btn) => {{
      if (btn.dataset.gapTabSync === "1") return;
      btn.dataset.gapTabSync = "1";
      btn.addEventListener("click", () => {{
        syncQueryParam(slugify(btn.innerText.trim()));
      }});
    }});
  }}

  function syncCurrentTabBeforeInteraction() {{
    if (parentDoc.body.dataset.gapTabPointerSync === "1") return;
    parentDoc.body.dataset.gapTabPointerSync = "1";
    parentDoc.addEventListener("pointerdown", () => {{
      const tablist = findTargetTablist();
      if (tablist) syncSelectedTab(tablist);
    }}, true);
  }}

  function activateRequestedTab(tablist) {{
    if (!requestedTab) return;
    const buttons = Array.from(tablist.querySelectorAll('button[role="tab"]'));
    const target = buttons.find((btn) => slugify(btn.innerText.trim()) === requestedTab);
    if (!target) return;
    const selected = target.getAttribute("aria-selected") === "true";
    if (!selected) target.click();
  }}

  function init() {{
    const tablist = findTargetTablist();
    if (!tablist) return false;
    attachListeners(tablist);
    activateRequestedTab(tablist);
    return true;
  }}

  syncCurrentTabBeforeInteraction();

  if (!init()) {{
    let attempts = 0;
    const timer = parentWin.setInterval(() => {{
      attempts += 1;
      if (init() || attempts > 40) {{
        parentWin.clearInterval(timer);
      }}
    }}, 150);
  }}
}})();
</script>
"""

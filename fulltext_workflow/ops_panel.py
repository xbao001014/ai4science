"""Gap UI「运维」tab: weekly one-click job control + clear ops memory.

Pure display helpers (`step_status_icon`, `format_sidebar_job_chip`) are kept
free of Streamlit so they can be unit tested directly. Everything else here
renders Streamlit widgets and is exercised via manual smoke testing.
"""
from __future__ import annotations

import streamlit as st

from analysis.focus_filter import normalize_focus
from analysis.ops_jobs import (
    OpsJobError,
    cancel_weekly_job,
    get_active_weekly_job,
    progress_counts,
    start_weekly_job,
    tail_log,
)
from analysis.ops_memory import clear_ops_memory, preview_ops_memory

_STEP_ICONS = {
    "pending": "○",
    "running": "●",
    "succeeded": "✓",
    "skipped": "–",
    "failed": "✗",
    "cancelled": "■",
}
_ACTIVE_STATES = frozenset({"pending", "running"})


def step_status_icon(status: str) -> str:
    """Map a weekly job step status to its display icon (defaults to pending)."""
    return _STEP_ICONS.get(status, "○")


def format_sidebar_job_chip(job: dict | None) -> str:
    """Short sidebar status line: idle, or running with the current step id."""
    if not job or job.get("state") not in _ACTIVE_STATES:
        return "周更：空闲"
    current_step = next(
        (s.get("id") for s in job.get("steps", []) if s.get("status") == "running"),
        None,
    )
    if current_step:
        return f"周更：进行中 · {current_step}"
    return "周更：进行中"


def _render_status_body() -> None:
    job = get_active_weekly_job()
    if job is None:
        st.caption("暂无周常任务记录。")
        return

    state = job.get("state", "?")
    st.caption(f"任务 `{job.get('job_id', '?')}` · 状态：**{state}**")
    if job.get("error"):
        st.error(job["error"])

    done, total = progress_counts(job)
    st.progress(done / total if total else 0.0, text=f"{done}/{total} 步骤完成")

    step_lines = [
        f"{step_status_icon(step.get('status', 'pending'))} {step.get('label', step.get('id', '?'))}"
        for step in job.get("steps", [])
    ]
    st.markdown("　".join(step_lines))

    with st.expander("日志（最近 200 行）", expanded=False):
        st.code(tail_log(job["job_id"], max_lines=200) or "（暂无日志）", language="text")

    if state == "running":
        confirm_cancel = st.checkbox("确认取消", key="ops_confirm_cancel")
        if st.button("取消任务", disabled=not confirm_cancel, key="ops_cancel_btn"):
            try:
                cancel_weekly_job(job["job_id"])
                st.success("已请求取消。")
                st.rerun()
            except OpsJobError as exc:
                st.error(str(exc))


if hasattr(st, "fragment"):
    _status_fragment = st.fragment(run_every=2)(_render_status_body)
else:
    _status_fragment = _render_status_body


def _render_weekly_section() -> None:
    active = get_active_weekly_job()
    is_running = bool(active and active.get("state") in _ACTIVE_STATES)

    col1, col2, col3 = st.columns(3)
    with col1:
        since_days = st.number_input(
            "回溯天数（SinceDays）",
            min_value=1,
            max_value=90,
            value=14,
            step=1,
            key="ops_since_days",
        )
    with col2:
        extract_limit = st.number_input(
            "抽取上限（ExtractLimit，0=全部待抽取）",
            min_value=0,
            max_value=5000,
            value=0,
            step=50,
            key="ops_extract_limit",
        )
    with col3:
        skip_enrich = st.checkbox(
            "跳过引用补全（SkipEnrich）",
            value=False,
            key="ops_skip_enrich",
        )

    if st.button(
        "启动周常更新",
        type="primary",
        disabled=is_running,
        help="已有周常任务在运行时不可再次启动。" if is_running else None,
        key="ops_start_btn",
    ):
        try:
            job = start_weekly_job(
                since_days=int(since_days),
                extract_limit=int(extract_limit),
                skip_enrich=bool(skip_enrich),
            )
            st.success(f"已启动周常任务 {job['job_id']}")
            st.rerun()
        except OpsJobError as exc:
            st.error(str(exc))

    _status_fragment()

    if st.button("刷新状态", key="ops_refresh_status_btn"):
        st.rerun()


def _render_clear_memory_section(focus_hint: str) -> None:
    focus_norm = normalize_focus(focus_hint)
    scope_options = ["全部"] + (["仅当前焦点"] if focus_norm else [])
    scope = st.radio(
        "清空范围",
        scope_options,
        horizontal=True,
        key="ops_clear_scope",
    )
    focus_for_clear = focus_hint if (focus_norm and scope == "仅当前焦点") else None

    preview = preview_ops_memory(focus_for_clear)
    counts = preview.get("counts", {})
    c1, c2, c3 = st.columns(3)
    c1.metric("Ops 运行", counts.get("ops_runs", 0))
    c2.metric("空白条目", counts.get("ops_gap_items", 0))
    c3.metric("提案", counts.get("ops_proposals", 0))

    files = preview.get("file_paths") or []
    delete_files = st.checkbox(
        f"同时删除关联文件（{len(files)} 个）",
        value=False,
        key="ops_clear_delete_files",
    )
    confirm = st.checkbox("我确认清空", value=False, key="ops_clear_confirm")

    if st.button(
        "执行清空",
        disabled=not confirm,
        key="ops_clear_execute_btn",
    ):
        result = clear_ops_memory(
            focus=focus_for_clear,
            execute=True,
            delete_files=delete_files,
        )
        msg = (
            f"已清空：ops_runs {result['before']['ops_runs']} → "
            f"{result['after']['ops_runs']}"
        )
        if delete_files:
            msg += f"；已删除文件 {result.get('files_removed', 0)} 个"
        st.success(msg)
        st.rerun()


def render_ops_tab(focus_hint: str = "") -> None:
    """Render the Gap UI「运维」tab: weekly job control + clear ops memory."""
    st.subheader("周常一键更新")
    st.caption(
        "等价于后台依次执行 `-Stage weekly` 的 10 个步骤；"
        "启动后可切换到其他标签页，任务在后台独立进程运行。"
    )
    _render_weekly_section()

    st.divider()
    st.subheader("清空 ops 记忆")
    st.caption("仅清空 ops_runs / ops_gap_items / ops_proposals，不影响论文与知识图谱数据。")
    _render_clear_memory_section(focus_hint)


def render_ops_sidebar_chip() -> None:
    """Render a one-line weekly-job status chip near the bottom of the sidebar."""
    job = get_active_weekly_job()
    st.caption(format_sidebar_job_chip(job))

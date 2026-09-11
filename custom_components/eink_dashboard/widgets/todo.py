"""To-do widget context builder.

本地新增（不是上游的）。上游 hass-eink-dashboard 沒有待辦清單 widget。

排版刻意跟 calendar widget 完全一致（同樣的 context 形狀、共用同一個
Jinja 模板），所以兩者在面板上看起來是同一種列表。

資料來源比較特別：Home Assistant 的 todo 實體 **state 只有「未完成項目數」**，
項目本身不在 attributes 裡，只能透過 `todo.get_items` 服務拿。渲染這一層沒有
hass 可用，所以項目是由 image.py 在算圖之前先抓好、放進 config["todo_items"]。
"""

from __future__ import annotations

from datetime import datetime

from ..const import (
    COLOR_BLACK,
    COLOR_GRAY,
    DEFAULT_CARD_STYLE,
    PADDING,
    DisplayConfig,
    Widget,
    color_to_hex,
)
from ..svg_render import _mdi_svg_filter
from ._helpers import (
    _auto_row_height,
    _card_insets,
    _color_context,
    _fit_text,
    _metrics_context,
    _text_width,
    _title_layout,
    _widget_dim,
)


def _due_reached(due: object, now: datetime) -> bool:
    """Has this item's due date arrived yet?

    無到期日的一律視為「該做了」。只寫日期（YYYY-MM-DD）時當天就顯示；
    帶時間的要到那個時刻才顯示。解析不出來就顯示 —— 寧可多顯示也不要漏掉。
    """
    if not due:
        return True
    text = str(due)
    try:
        if len(text) <= 10:
            return (
                datetime.strptime(text[:10], "%Y-%m-%d").date() <= now.date()
            )
        # 去掉時區再比，跟 calendar widget 一樣用本地牆上時間
        cleaned = text.replace("Z", "")
        for sep in ("+", "-"):
            idx = cleaned.rfind(sep)
            if idx > 10:
                cleaned = cleaned[:idx]
                break
        return datetime.fromisoformat(cleaned) <= now
    except (ValueError, TypeError):
        return True


def _build_todo_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the to-do widget.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (todo entity id), ``title``, ``max_items``
            (default 5), ``icon`` (MDI name for the row icon,
            default ``"checkbox-blank-outline"``), ``card_style``,
            ``bold_value``, ``x``, ``w``, ``h``.
        config: Display config.  Needs ``todo_items`` — a mapping of
            entity id to the list of items that image.py fetched.

    Returns:
        The same context shape as the calendar widget, consumed by
        ``todo.svg.j2`` (which just includes ``calendar.svg.j2``).
    """
    from ..render import _compute_metrics, _load_font

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    entity_id: str = widget.get("entity", "")
    max_items: int = int(widget.get("max_items", 5))
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    title: str = widget.get("title", "")
    icon_name: str = widget.get("icon", "checkbox-blank-outline")
    value_bold: bool = widget.get("bold_value", False)
    display_levels = config.get("display_levels", 16)

    empty_ctx: dict[str, object] = {
        "w": svg_w,
        "h": _widget_dim(widget, "h", _auto_row_height(title, 1)),
        "has_rows": False,
        **_color_context(),
    }
    if not entity_id:
        return empty_ctx

    all_items = (config.get("todo_items") or {}).get(entity_id) or []
    # 只列還沒完成的；已完成的留在清單裡對面板沒有意義
    pending = [
        i for i in all_items if i.get("status", "needs_action") != "completed"
    ]
    # 有排定時間的，時間到了才顯示 —— 面板要回答的是「現在該做什麼」，
    # 不是完整的待辦清單；下個月的事現在跳出來只是雜訊。
    now = datetime.now()
    pending = [i for i in pending if _due_reached(i.get("due"), now)]
    # 有到期日的排前面（越早越前），沒有到期日的排後面
    pending.sort(key=lambda i: (not i.get("due"), str(i.get("due") or "")))
    visible = pending[:max_items]
    if not visible:
        return empty_ctx

    num_rows = len(visible)
    svg_h = _widget_dim(widget, "h", _auto_row_height(title, num_rows))
    title_font_sz, content_y, content_h = _title_layout(
        title, svg_h, widget.get("title_font_size")
    )
    row_h = content_h // num_rows
    # 跟 calendar 同樣的處理：只剩一項時不要把整個 widget 都給那一列，
    # 否則字級（row_h * 0.32）會大到溢出寬度。
    row_h = min(row_h, max(1, content_h // max(1, max_items)))

    m = _compute_metrics(row_h)
    icon_stroke_w = m.border * 3 if display_levels <= 2 else m.border
    divider_stroke_w = m.divider * 3 if display_levels <= 2 else m.divider
    x_off, r_inset, bar_width = _card_insets(m, card_style, display_levels)
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    f_primary = _load_font(m.font_primary, medium=True)
    f_value = _load_font(m.font_secondary, bold=value_bold)
    text_left = x_off + lpad + m.icon_dia + m.inner_gap
    text_right = svg_w - r_inset - rpad

    icon_svg = _mdi_svg_filter(icon_name, m.icon_inner)

    rows: list[dict[str, object]] = []
    for i, item in enumerate(visible):
        due = str(item.get("due") or "")
        # due 可能是 "YYYY-MM-DD" 或完整 ISO；面板只需要月/日
        label = ""
        if len(due) >= 10:
            label = "%s/%s" % (due[5:7].lstrip("0"), due[8:10].lstrip("0"))
        avail = text_right - text_left - m.inner_gap
        if label:
            avail -= _text_width(label, f_value, m.font_secondary)
        rows.append(
            {
                "y": content_y + i * row_h,
                "primary": _fit_text(
                    str(item.get("summary", "")),
                    f_primary,
                    m.font_primary,
                    avail,
                ),
                "secondary": "",
                "value": label,
                "icon_svg": icon_svg,
                "icon_outline": True,
                "icon_fill": color_to_hex(COLOR_GRAY),
                "secondary_fill": color_to_hex(COLOR_GRAY),
                "value_fill": color_to_hex(COLOR_BLACK),
                "letter": "",
            }
        )

    return {
        "w": svg_w,
        "h": svg_h,
        "has_rows": True,
        "title": title,
        "title_font_sz": title_font_sz,
        "content_y": content_y,
        "content_h": content_h,
        "card_style": card_style,
        "bar_width": bar_width,
        **_metrics_context(m),
        **_color_context(),
        "row_h": row_h,
        "rows": rows,
        "x_off": x_off,
        "r_inset": r_inset,
        "lpad": lpad,
        "rpad": rpad,
        "icon_stroke_w": icon_stroke_w,
        "divider_stroke_w": divider_stroke_w,
        "value_bold": value_bold,
    }

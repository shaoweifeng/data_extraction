"""基于 Matplotlib 的 QA 图表渲染器。

不依赖 Django request 或 API response，所有方法统一使用 Python 绘图。
"""

import base64
import io

import matplotlib
matplotlib.use('Agg')
import matplotlib.font_manager as _fm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _fig_to_b64(fig) -> str:
    """将 matplotlib Figure 转为 data URL 格式的 base64 PNG。"""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return 'data:image/png;base64,' + base64.b64encode(buf.read()).decode()

def _init_cjk_font():
    """用字体文件路径直接设置中文字体，绕过名称查找。
    兼容 macOS（STHeiti/Hiragino）与 Linux（fonts-noto-cjk / wqy）。
    服务器需提前安装：
        apt-get install -y fonts-noto-cjk        # Debian/Ubuntu（推荐）
      或
        yum install -y google-noto-sans-cjk-ttc  # CentOS/RHEL
    """
    candidates = [
        # macOS
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/System/Library/Fonts/STHeiti Medium.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        '/Library/Fonts/Arial Unicode.ttf',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        # Linux — Noto CJK（fonts-noto-cjk）
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc',
        # Linux — WQY（wqy-microhei / wqy-zenhei）
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/wqy-microhei/wqy-microhei.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        # Linux — 通用备用（文泉驿 CJK）
        '/usr/share/fonts/wenquanyi/wqy-microhei/wqy-microhei.ttc',
    ]
    for path in candidates:
        import os as _os
        if _os.path.exists(path):
            try:
                prop = _fm.FontProperties(fname=path)
                name = prop.get_name()
                if name not in plt.rcParams['font.sans-serif']:
                    plt.rcParams['font.sans-serif'].insert(0, name)
                    _fm.fontManager.addfont(path)
                plt.rcParams['axes.unicode_minus'] = False
                return name
            except Exception:
                continue
    plt.rcParams['axes.unicode_minus'] = False
    return None


# ── 颜色/符号（直接沿用原脚本）────────────────────────────────────────────────
_COLORS  = {"High": "#d7191c", "Unclear": "#f1e51d", "Low": "#00b83f"}
_SYMBOLS = {"High": "×", "Unclear": "?", "Low": "+"}
_SYMBOL_FONT_SIZE = 13
_CIRCLE_MARKER_SIZE = 1350
# 内部 key → 原脚本 key 的映射
_JUDGMENT_MAP = {
    "low":     "Low",
    "high":    "High",
    "unclear": "Unclear",
    "pending": "Unclear",
    "na":      "Low",
}

# 图例 / 分组标题国际化（lang='zh' 中文，lang='en' 英文）
_I18N = {
    'zh': {
        'risk_of_bias':           '偏倚风险',
        'applicability_concerns': '适用性问题',
        'high':    '高风险',
        'unclear': '不清楚',
        'low':     '低风险',
    },
    'en': {
        'risk_of_bias':           'Risk of Bias',
        'applicability_concerns': 'Applicability Concerns',
        'high':    'High',
        'unclear': 'Unclear',
        'low':     'Low',
    },
}


def _draw_judgment_marker(ax, x, y, value):
    """用显示坐标中的点大小绘制标记。

    scatter 的圆形 marker 按 points² 计算，不会因坐标轴比例、
    横纵布局或长文献名称改变而被拉伸成椭圆。
    """
    ax.scatter(
        [x], [y],
        s=_CIRCLE_MARKER_SIZE,
        marker='o',
        facecolor=_COLORS[value],
        edgecolor='black',
        linewidth=0.8,
        zorder=2,
    )
    sym_color = "black" if value == "Unclear" else "white"
    ax.text(
        x, y, _SYMBOLS[value],
        ha="center", va="center",
        fontsize=_SYMBOL_FONT_SIZE, fontweight="bold", color=sym_color,
        zorder=3,
    )


def _get_study_label(row: dict, study_labels: dict) -> str:
    ref_id = row['ref_id']
    if study_labels and str(ref_id) in study_labels:
        return study_labels[str(ref_id)][:60]
    author = row.get('first_author') or ''
    year   = row.get('year') or ''
    if author:
        return f"{author} {year}".strip()
    title = row.get('title') or f"Ref {ref_id}"
    return title[:40]


# ── 以下三个函数原封不动来自 quadas2_matplotlib_tryrun_20260830_025320.py ─────

def _draw_summary_bar(ax, summary_df, title):
    y_positions = np.arange(len(summary_df))
    left = np.zeros(len(summary_df))
    for status in ["High", "Unclear", "Low"]:
        values = summary_df[status].values
        ax.barh(y_positions, values, left=left,
                color=_COLORS[status], edgecolor="black", height=0.65, label=status)
        left += values
    ax.set_yticks(y_positions)
    ax.set_yticklabels(summary_df["domain"])
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.tick_params(axis="both", labelsize=8)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)


def _draw_traffic_light_matrix(ax, studies, rows, n_bias, orientation='horizontal', i18n=None):
    """
    studies:     list of str
    rows:        list of {"label": str, "values": list of "High"/"Unclear"/"Low"}
    n_bias:      int — 前几行属于 Risk of Bias（其余为 Applicability Concerns）
    orientation: 'horizontal'（研究=列，默认） | 'vertical'（研究=行）
    i18n:        _I18N['zh'] 或 _I18N['en']
    """
    if i18n is None:
        i18n = _I18N['zh']
    n_studies = len(studies)
    n_domains = len(rows)

    if orientation == 'vertical':
        # ── 纵向：研究=行，领域=列 ─────────────────────────────────────────
        # xlim: (-1.0 ~ n_domains+0.5)  留左侧给研究名标签
        # ylim: (-0.5 ~ n_studies+0.5)  顶部留给列头
        ax.set_xlim(-1.0, n_domains + 0.5)
        ax.set_ylim(-1.0, n_studies + 0.5)
        ax.invert_yaxis()
        ax.axis("off")

        # 领域名（列头，旋转 45°）
        for col_idx, row in enumerate(rows):
            ax.text(col_idx, -0.6, row["label"],
                    ha="center", va="bottom", rotation=45, fontsize=7)

        # bias / applic 纵向分隔线
        ax.plot([n_bias - 0.5, n_bias - 0.5],
                [-0.5, n_studies - 0.5],
                color="black", linewidth=1)

        # 圆 + 符号
        for row_idx, study in enumerate(studies):
            ax.text(-0.6, row_idx, study,
                    ha="right", va="center", fontsize=7)
            for col_idx, domain_row in enumerate(rows):
                value = domain_row["values"][row_idx]
                _draw_judgment_marker(ax, col_idx, row_idx, value)

        # 底部横排组名
        ax.text((n_bias - 1) / 2, n_studies + 0.2,
                i18n['risk_of_bias'],
                ha="center", va="top", fontsize=8)
        if n_domains > n_bias:
            ax.text(n_bias + (n_domains - n_bias - 1) / 2, n_studies + 0.2,
                    i18n['applicability_concerns'],
                    ha="center", va="top", fontsize=8)

    else:
        # ── 横向（默认）：研究=列，领域=行 ───────────────────────────────────
        n_cols = n_studies
        n_rows = n_domains
        ax.set_xlim(-0.5, n_cols + 3.5)
        ax.set_ylim(-1.5, n_rows + 0.6)
        ax.invert_yaxis()
        ax.axis("off")

        # 研究名（列头，旋转 90°）
        for i, study in enumerate(studies):
            ax.text(i, -0.8, study, ha="center", va="bottom",
                    rotation=90, fontsize=7)

        # bias / applic 水平分隔线
        ax.plot([-0.5, n_cols - 0.5],
                [n_bias - 0.5, n_bias - 0.5],
                color="black", linewidth=1)

        # 圆 + 符号 + 行标签
        for row_idx, row in enumerate(rows):
            for col_idx, value in enumerate(row["values"]):
                _draw_judgment_marker(ax, col_idx, row_idx, value)
            ax.text(n_cols + 0.3, row_idx, row["label"],
                    ha="left", va="center", fontsize=8)

        # 右侧竖排组名
        ax.text(n_cols + 2.2, (n_bias - 1) / 2,
                i18n['risk_of_bias'],
                ha="center", va="center", rotation=270, fontsize=8)
        ax.text(n_cols + 2.2, n_bias + (n_rows - n_bias - 1) / 2,
                i18n['applicability_concerns'],
                ha="center", va="center", rotation=270, fontsize=8)


def _draw_legend(ax, i18n=None):
    """用矩形色块画图例（与原脚本对齐，避免 aspect 影响）。"""
    if i18n is None:
        i18n = _I18N['zh']
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    labels = [i18n['high'], i18n['unclear'], i18n['low']]
    for x, key, label in zip([0.1, 0.42, 0.72], ["High", "Unclear", "Low"], labels):
        rect = plt.Rectangle((x, 0.25), 0.08, 0.5,
                              facecolor=_COLORS[key], edgecolor="black", linewidth=0.8)
        ax.add_patch(rect)
        ax.text(x + 0.10, 0.5, label, ha="left", va="center", fontsize=9)
    # 外框
    border = plt.Rectangle((0.05, 0.1), 0.9, 0.8,
                            facecolor="none", edgecolor="black", linewidth=1.0)
    ax.add_patch(border)


# ── 两个对外渲染接口 ───────────────────────────────────────────────────────────

def render_traffic_light(traffic_light_data, bias_domains, applic_domains,
                          method_name, quality_method='', study_labels=None,
                          orientation='horizontal', lang='zh') -> str:
    """生成交通灯图（Panel B），返回 base64 data URL。"""
    _init_cjk_font()
    i18n = _I18N.get(lang, _I18N['zh'])
    if not traffic_light_data:
        return None

    # ── 组装数据（内部 key → "High"/"Unclear"/"Low"）─────────────────────────
    studies = [_get_study_label(r, study_labels) for r in traffic_light_data]

    def _domain_label(d):
        """按 lang 返回领域显示名"""
        return d.get('name_en', d['name']) if lang == 'en' else d['name']

    rows = []
    for d in bias_domains:
        rows.append({
            "label": _domain_label(d),
            "values": [
                _JUDGMENT_MAP.get(r['bias_risk'].get(d['key'], 'pending'), 'Unclear')
                for r in traffic_light_data
            ],
        })
    for d in applic_domains:
        rows.append({
            "label": _domain_label(d),
            "values": [
                _JUDGMENT_MAP.get(r['applicability'].get(d['key'], 'pending'), 'Unclear')
                for r in traffic_light_data
            ],
        })

    n_bias_rows = len(bias_domains)
    n_rows      = len(rows)
    n_studies   = len(studies)

    # 根据方向计算图幅
    if orientation == 'vertical':
        # 纵向：研究=行，领域=列；宽度由领域数决定，高度由研究数决定
        data_w = n_rows + 1.5      # xlim 范围
        data_h = n_studies + 1.5   # ylim 范围
        fig_w  = max(7, n_rows * 1.2 + 2)
        fig_h  = max(5, n_studies * 0.85 + 2)
    else:
        # 横向：研究=列，领域=行
        data_w = n_studies + 4.0
        data_h = n_rows + 2.1
        fig_w  = max(8, n_studies * 0.85 + 5)
        fig_h  = fig_w * data_h / data_w

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    _draw_traffic_light_matrix(ax, studies, rows, n_bias_rows, orientation=orientation, i18n=i18n)

    plt.tight_layout(pad=0.5)
    return _fig_to_b64(fig)


def render_proportion(proportion_data, method_name, quality_method='',
                       traffic_light_data=None, bias_domains=None, applic_domains=None,
                       study_labels=None, lang='zh') -> str:
    """生成比例图（Panel A），返回 base64 data URL。"""
    _init_cjk_font()
    i18n = _I18N.get(lang, _I18N['zh'])
    if not proportion_data:
        return None

    # ── 用原脚本的 _draw_summary_bar + _draw_legend ───────────────────────────
    bias_keys   = {d['key'] for d in (bias_domains   or [])}
    applic_keys = {d['key'] for d in (applic_domains or [])}

    def _make_summary_df(domain_list, key_set):
        records = []
        for d in (domain_list or []):
            k = d['key']
            item = proportion_data.get(k) or proportion_data.get('app_' + k)
            if item is None:
                continue
            total = max(1, sum(item['counts'].values()))
            domain_label = d.get('name_en', d['name']) if lang == 'en' else d['name']
            records.append({
                "domain":   domain_label,
                "High":     item['counts'].get('high', 0)   / total,
                "Unclear":  item['counts'].get('unclear', 0) / total,
                "Low":      item['counts'].get('low', 0)    / total,
            })
        return pd.DataFrame(records) if records else pd.DataFrame(
            columns=["domain", "High", "Unclear", "Low"])

    rob_summary = _make_summary_df(bias_domains,   bias_keys)
    app_summary = _make_summary_df(applic_domains, applic_keys)

    has_applic = len(app_summary) > 0

    fig = plt.figure(figsize=(11, 5.5))
    grid = fig.add_gridspec(
        nrows=2, ncols=2,
        height_ratios=[1.0, 0.22],
        width_ratios=[1, 1],
        hspace=0.5, wspace=0.35,
    )
    ax_left   = fig.add_subplot(grid[0, 0])
    ax_right  = fig.add_subplot(grid[0, 1])
    ax_legend = fig.add_subplot(grid[1, :])

    _draw_summary_bar(ax_left,  rob_summary, i18n['risk_of_bias'])
    if has_applic:
        _draw_summary_bar(ax_right, app_summary, i18n['applicability_concerns'])
    else:
        ax_right.axis("off")

    _draw_legend(ax_legend, i18n=i18n)

    plt.tight_layout(pad=0.5)
    return _fig_to_b64(fig)

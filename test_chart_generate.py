#!/usr/bin/env python3
"""
QUADAS-2 图表生成测试脚本
生成 Panel A（比例图）和 Panel B（交通灯图）
目标：与参考图样式完全一致

运行方式：
    cd /Users/gclx/data_extraction
    python test_chart_generate.py

输出：
    /Users/gclx/test_traffic_light.png   ← Panel B
    /Users/gclx/test_proportion.png      ← Panel A
"""

import os
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import matplotlib.patheffects as pe
from matplotlib.patches import FancyBboxPatch, Rectangle
import numpy as np

# ────────────────────────────────────────────────────────────────────
# 颜色配置（与 robvis 风格一致）
# ────────────────────────────────────────────────────────────────────
C_HIGH    = '#D73027'   # 暗红 – High risk
C_UNCLEAR = '#FDAE61'   # 橙黄 – Unclear
C_LOW     = '#1A9850'   # 深绿 – Low risk
C_NA      = '#BBBBBB'   # 灰   – NA/pending

# ────────────────────────────────────────────────────────────────────
# 样本数据（6篇文献，4个偏倚领域 + 3个适用性领域）
# ────────────────────────────────────────────────────────────────────
STUDIES = [
    'Smith 2018',
    'Johnson 2019',
    'Wang 2020',
    'Garcia 2021',
    'Kim 2022',
    'Zhang 2023',
]

BIAS_DOMAINS = [
    'Patient\nSelection',
    'Index\nTest',
    'Reference\nStandard',
    'Flow and\nTiming',
]

APPLIC_DOMAINS = [
    'Patient\nSelection',
    'Index\nTest',
    'Reference\nStandard',
]

# bias_data[study_idx][domain_idx]  值：low / high / unclear
BIAS_DATA = [
    ['low',     'low',     'low',     'unclear'],   # Smith 2018
    ['high',    'unclear', 'low',     'low'],        # Johnson 2019
    ['low',     'low',     'unclear', 'low'],        # Wang 2020
    ['unclear', 'high',    'high',    'unclear'],    # Garcia 2021
    ['low',     'low',     'low',     'low'],        # Kim 2022
    ['high',    'unclear', 'low',     'high'],       # Zhang 2023
]

APPLIC_DATA = [
    ['low',     'low',     'low'],      # Smith 2018
    ['unclear', 'low',     'low'],      # Johnson 2019
    ['low',     'unclear', 'low'],      # Wang 2020
    ['low',     'low',     'unclear'],  # Garcia 2021
    ['low',     'low',     'low'],      # Kim 2022
    ['high',    'low',     'low'],      # Zhang 2023
]

# ────────────────────────────────────────────────────────────────────
# 工具函数
# ────────────────────────────────────────────────────────────────────
def _color(j: str) -> str:
    return {'low': C_LOW, 'high': C_HIGH, 'unclear': C_UNCLEAR}.get(j, C_NA)

def _symbol(j: str) -> str:
    return {'low': '+', 'high': '×', 'unclear': '?'}.get(j, '')

def _sym_color(j: str) -> str:
    """黄色背景用深色文字，其余用白色"""
    return '#333333' if j == 'unclear' else 'white'


# ════════════════════════════════════════════════════════════════════
#  Panel B — 交通灯图
# ════════════════════════════════════════════════════════════════════
def build_traffic_light(
    studies: list,
    bias_domains: list,
    applic_domains: list,
    bias_data: list,
    applic_data: list,
    figsize=None,
) -> plt.Figure:
    """
    生成交通灯图（Panel B）

    布局：
        - 研究名 = 列（顶部，旋转 45°）
        - 领域名 = 行（左侧 y 轴标签）
        - 两个行块：Risk of Bias（上）/ Applicability Concerns（下），右侧竖排标签
        - 彩色实心圆 + 白色符号（+/×/?）
        - 底部图例框
        - 整体外框
    """
    n_s = len(studies)
    n_b = len(bias_domains)
    n_a = len(applic_domains)

    # ── 尺寸自适应 ────────────────────────────────────────────────────
    cell_w = 0.75   # 英寸/列
    cell_h = 0.55   # 英寸/行
    margin_l = 1.6  # 左侧领域名宽度
    margin_r = 1.0  # 右侧组名宽度
    margin_t = 1.6  # 顶部研究名高度
    margin_b = 0.9  # 底部图例高度

    n_rows = n_b + n_a  # total rows (gap handled separately)
    if figsize is None:
        figsize = (
            margin_l + cell_w * n_s + margin_r,
            margin_t + cell_h * (n_rows + 1) + margin_b,  # +1 for gap
        )

    fig, ax = plt.subplots(figsize=figsize, facecolor='white')
    fig.subplots_adjust(
        left   = margin_l / figsize[0],
        right  = 1.0 - margin_r / figsize[0],
        top    = 1.0 - margin_t / figsize[1],
        bottom = margin_b / figsize[1],
    )

    # ── Y 坐标分配（从上到下 = y 减小）────────────────────────────────
    #   bias 行：y = (n_a + GAP + n_b - 1) … (n_a + GAP)  （上→下）
    #   applic 行：y = (n_a - 1) … 0                       （上→下）
    GAP = 0.9
    bias_ys   = [n_a + GAP + (n_b - 1 - i) for i in range(n_b)]    # index 0 = 最上行
    applic_ys = [n_a - 1 - i               for i in range(n_a)]    # index 0 = 最上行

    all_ys     = bias_ys + applic_ys
    all_labels = [d.replace('\n', ' ') for d in bias_domains] + \
                 [d.replace('\n', ' ') for d in applic_domains]

    # ── 交替背景条纹 ──────────────────────────────────────────────────
    stripe_colors = ['#F7F7F7', '#EFEFEF']
    for idx, y in enumerate(all_ys):
        ax.barh(y, n_s, left=-0.5, height=0.85,
                color=stripe_colors[idx % 2], zorder=0, linewidth=0)

    # ── 竖向网格线（分隔列）─────────────────────────────────────────────
    for x in range(n_s - 1):
        ax.axvline(x + 0.5, color='white', linewidth=1.0, zorder=1)

    # ── 画圆 + 符号 ───────────────────────────────────────────────────
    CIRCLE_S = max(200, int(3500 / max(n_s, n_rows)))   # 自适应圆大小

    for di, y in enumerate(bias_ys):
        for si in range(n_s):
            j = bias_data[si][di]
            ax.scatter(si, y, s=CIRCLE_S, c=_color(j), zorder=3,
                       edgecolors='none', clip_on=False)
            ax.text(si, y, _symbol(j), ha='center', va='center',
                    fontsize=9, fontweight='bold', color=_sym_color(j),
                    zorder=4, clip_on=False)

    for di, y in enumerate(applic_ys):
        for si in range(n_s):
            j = applic_data[si][di]
            ax.scatter(si, y, s=CIRCLE_S, c=_color(j), zorder=3,
                       edgecolors='none', clip_on=False)
            ax.text(si, y, _symbol(j), ha='center', va='center',
                    fontsize=9, fontweight='bold', color=_sym_color(j),
                    zorder=4, clip_on=False)

    # ── 块分隔线 ──────────────────────────────────────────────────────
    sep_y = (min(bias_ys) + max(applic_ys)) / 2
    ax.axhline(sep_y, color='#888888', linewidth=1.5, zorder=2)

    # ── Y 轴（领域名，左侧）──────────────────────────────────────────
    ax.set_yticks(all_ys)
    ax.set_yticklabels(all_labels, fontsize=8.5, ha='right')
    ax.yaxis.tick_left()
    ax.tick_params(axis='y', length=0, pad=4)

    # ── X 轴（研究名，顶部，旋转 45°）────────────────────────────────
    ax.set_xticks(range(n_s))
    ax.set_xticklabels(studies, rotation=45, ha='left',
                       rotation_mode='anchor', fontsize=8.5)
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position('top')
    ax.tick_params(axis='x', length=0, pad=3)

    # ── 轴范围 ────────────────────────────────────────────────────────
    ax.set_xlim(-0.5, n_s - 0.5)
    y_min = min(applic_ys) - 0.5
    y_max = max(bias_ys) + 0.5
    ax.set_ylim(y_min, y_max)

    # ── 外框 ──────────────────────────────────────────────────────────
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(1.2)
        spine.set_edgecolor('#888888')

    # ── 右侧组名（坐标超出绘图区域，clip_on=False）────────────────────
    bias_center   = np.mean(bias_ys)
    applic_center = np.mean(applic_ys)
    right_x = n_s - 0.5 + 0.55   # data 坐标，超出右边界

    for y_c, label in [(bias_center, 'Risk of Bias'),
                       (applic_center, 'Applicability\nConcerns')]:
        ax.text(right_x, y_c, label,
                rotation=90, ha='center', va='center',
                fontsize=8.5, fontweight='bold', color='#333333',
                transform=ax.transData, clip_on=False,
                multialignment='center')

    # ── 底部图例 ──────────────────────────────────────────────────────
    legend_patches = [
        mpatches.Patch(color=C_HIGH,    label='High'),
        mpatches.Patch(color=C_UNCLEAR, label='Unclear'),
        mpatches.Patch(color=C_LOW,     label='Low'),
    ]
    leg = ax.legend(
        handles=legend_patches,
        loc='lower center',
        bbox_to_anchor=(0.5, -0.18),
        ncol=3,
        fontsize=9,
        frameon=True,
        edgecolor='#888888',
        fancybox=False,
        handlelength=1.2,
        handleheight=1.0,
        borderpad=0.6,
        columnspacing=1.2,
    )
    leg.get_frame().set_linewidth(1.0)

    fig.suptitle('')
    return fig


# ════════════════════════════════════════════════════════════════════
#  Panel A — 比例图（两个并排水平堆叠柱状图）
# ════════════════════════════════════════════════════════════════════
def build_proportion(
    studies: list,
    bias_domains: list,
    applic_domains: list,
    bias_data: list,
    applic_data: list,
    figsize=None,
) -> plt.Figure:
    """
    生成比例图（Panel A）

    布局：
        - 左子图：Risk of Bias（4 行水平堆叠柱）
        - 右子图：Applicability Concerns（3 行水平堆叠柱）
        - 颜色：High=红 | Unclear=黄 | Low=绿
        - X 轴：0% 25% 50% 75% 100%
        - 底部共享图例框
    """
    n_s = len(studies)
    n_b = len(bias_domains)
    n_a = len(applic_domains)

    if figsize is None:
        figsize = (10, max(4, 0.55 * max(n_b, n_a) + 2.5))

    fig, (ax_b, ax_a) = plt.subplots(
        1, 2, figsize=figsize, facecolor='white',
        gridspec_kw={'wspace': 0.38}
    )
    fig.subplots_adjust(left=0.18, right=0.97, top=0.88, bottom=0.18)

    def calc_props(data, n_domains):
        """计算每个领域各判断的占比 [{high, unclear, low}, ...]"""
        result = []
        for di in range(n_domains):
            c = {'high': 0, 'unclear': 0, 'low': 0}
            for si in range(n_s):
                j = data[si][di]
                if j in c:
                    c[j] += 1
            total = n_s or 1
            result.append({k: v / total for k, v in c.items()})
        return result

    def draw_one(ax, domains, props, title):
        n = len(domains)
        ys = list(range(n - 1, -1, -1))   # 第0领域在最顶部
        BAR_H = 0.68

        lefts = [0.0] * n
        # 顺序：High | Unclear | Low（从左到右）
        for key, color in [
            ('high',    C_HIGH),
            ('unclear', C_UNCLEAR),
            ('low',     C_LOW),
        ]:
            widths = [props[i][key] for i in range(n)]
            ax.barh(ys, widths, left=lefts, height=BAR_H,
                    color=color, edgecolor='white', linewidth=0.6, zorder=2)
            lefts = [lefts[i] + widths[i] for i in range(n)]

        # X 轴
        ax.set_xlim(0, 1)
        ax.set_xticks([0, 0.25, 0.50, 0.75, 1.0])
        ax.set_xticklabels(['0%', '25%', '50%', '75%', '100%'], fontsize=8)
        ax.tick_params(axis='x', length=3)

        # Y 轴（领域名，无刻度线）
        clean_labels = [d.replace('\n', ' ') for d in domains]
        ax.set_yticks(ys)
        ax.set_yticklabels(clean_labels, fontsize=8.5, ha='right')
        ax.tick_params(axis='y', length=0, pad=4)
        ax.set_ylim(-0.5, n - 0.5)

        # 标题
        ax.set_title(title, fontsize=9.5, fontweight='bold', pad=7)

        # 样式
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.set_facecolor('#F7F7F7')
        ax.grid(axis='x', color='white', linewidth=1.0, zorder=1)
        ax.axvline(0, color='#AAAAAA', linewidth=0.8, zorder=3)

    bias_props   = calc_props(bias_data,   n_b)
    applic_props = calc_props(applic_data, n_a)

    draw_one(ax_b, bias_domains,   bias_props,   'Risk of Bias')
    draw_one(ax_a, applic_domains, applic_props, 'Applicability Concerns')

    # ── 底部共享图例 ───────────────────────────────────────────────────
    legend_patches = [
        mpatches.Patch(color=C_HIGH,    label='High'),
        mpatches.Patch(color=C_UNCLEAR, label='Unclear'),
        mpatches.Patch(color=C_LOW,     label='Low'),
    ]
    leg = fig.legend(
        handles=legend_patches,
        loc='lower center',
        bbox_to_anchor=(0.5, 0.01),
        ncol=3,
        fontsize=9,
        frameon=True,
        edgecolor='#888888',
        fancybox=False,
        handlelength=1.2,
        handleheight=1.0,
        borderpad=0.6,
        columnspacing=1.2,
    )
    leg.get_frame().set_linewidth(1.0)

    return fig


# ════════════════════════════════════════════════════════════════════
#  入口：生成并保存
# ════════════════════════════════════════════════════════════════════
def main():
    out_tl   = '/Users/gclx/test_traffic_light.png'
    out_prop = '/Users/gclx/test_proportion.png'

    print('生成 Panel B（交通灯图）...')
    fig_b = build_traffic_light(
        STUDIES, BIAS_DOMAINS, APPLIC_DOMAINS, BIAS_DATA, APPLIC_DATA
    )
    fig_b.savefig(out_tl, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig_b)
    print(f'  ✓ 已保存：{out_tl}')

    print('生成 Panel A（比例图）...')
    fig_a = build_proportion(
        STUDIES, BIAS_DOMAINS, APPLIC_DOMAINS, BIAS_DATA, APPLIC_DATA
    )
    fig_a.savefig(out_prop, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig_a)
    print(f'  ✓ 已保存：{out_prop}')

    print('\n完成！请查看以上两个文件，确认样式后告知是否需要调整。')


if __name__ == '__main__':
    main()

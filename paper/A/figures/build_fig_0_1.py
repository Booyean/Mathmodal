#!/usr/bin/env python3
"""Generate editable vector SVG and print-ready PDF for Fig 0-1 (Problem A pipeline)."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from xml.sax.saxutils import escape

import pymupdf


FIG_WIDTH_MM = 160.0
FIG_HEIGHT_MM = 64.0


def _text_block(
    x: float,
    y: float,
    lines: list[str],
    size: float = 2.35,
    fill: str = "#1F2937",
    line_gap: float = 3.05,
) -> str:
    parts = []
    start_y = y - (len(lines) - 1) * line_gap * 0.5
    for idx, line in enumerate(lines):
        parts.append(
            f'<text x="{x:.2f}" y="{start_y + idx * line_gap:.2f}" text-anchor="middle" '
            f'dominant-baseline="central" font-family="Microsoft YaHei, SimHei, sans-serif" '
            f'font-size="{size:.2f}" fill="{fill}">{escape(line)}</text>'
        )
    return "\n    ".join(parts)


def _node_box(
    node_id: str,
    x: float,
    y: float,
    w: float,
    h: float,
    fill: str,
    stroke: str,
    header_fill: str,
    header_h: float,
    title: str,
    body_lines: list[str],
    title_size: float = 2.4,
    body_size: float = 2.25,
    rx: float = 1.5,
) -> str:
    cx = x + w / 2.0
    body_cy = y + header_h + (h - header_h) / 2.0
    return f"""  <g id="{escape(node_id)}">
    <rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{rx:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="0.45"/>
    <path d="M {x:.2f},{y + header_h:.2f} L {x:.2f},{y + rx:.2f} Q {x:.2f},{y:.2f} {x + rx:.2f},{y:.2f} L {x + w - rx:.2f},{y:.2f} Q {x + w:.2f},{y:.2f} {x + w:.2f},{y + rx:.2f} L {x + w:.2f},{y + header_h:.2f} Z" fill="{header_fill}"/>
    <text x="{cx:.2f}" y="{y + header_h / 2.0:.2f}" text-anchor="middle" dominant-baseline="central" font-family="Microsoft YaHei, SimHei, sans-serif" font-size="{title_size:.2f}" font-weight="700" fill="#FFFFFF">{escape(title)}</text>
    {_text_block(cx, body_cy, body_lines, size=body_size, fill="#1F2937", line_gap=2.95)}
  </g>"""


def _dashed_polyline_d(
    points: list[tuple[float, float]],
    dash: float = 1.7,
    gap: float = 1.15,
) -> str:
    """Build explicit dashed SVG subpaths so PDF renderers without dasharray still show dashes."""
    subpaths: list[str] = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        dx = x1 - x0
        dy = y1 - y0
        seg_len = math.hypot(dx, dy)
        if seg_len <= 1e-6:
            continue
        ux, uy = dx / seg_len, dy / seg_len
        pos = 0.0
        while pos < seg_len:
            end = min(pos + dash, seg_len)
            sx, sy = x0 + ux * pos, y0 + uy * pos
            ex, ey = x0 + ux * end, y0 + uy * end
            subpaths.append(f"M {sx:.2f},{sy:.2f} L {ex:.2f},{ey:.2f}")
            pos += dash + gap
    return " ".join(subpaths)


def _ortho_arrow(
    points: list[tuple[float, float]],
    color: str,
    width: float = 0.52,
    dashed: bool = False,
) -> str:
    """Render an orthogonal polyline plus explicit vector triangle arrowhead."""
    if len(points) < 2:
        raise ValueError("Need >= 2 points")
    (x_prev, y_prev), (x_end, y_end) = points[-2], points[-1]
    dx = x_end - x_prev
    dy = y_end - y_prev
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    head_len = 1.65
    head_half_w = 0.85
    bx, by = x_end - ux * head_len, y_end - uy * head_len
    px, py = -uy * head_half_w, ux * head_half_w

    line_pts = points[:-1] + [(bx + 0.1 * ux, by + 0.1 * uy)]
    if dashed:
        d_str = _dashed_polyline_d(line_pts, dash=1.7, gap=1.15)
    else:
        d_str = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in line_pts)
    tri = (
        f"{x_end:.2f},{y_end:.2f} "
        f"{bx + px:.2f},{by + py:.2f} "
        f"{bx - px:.2f},{by - py:.2f}"
    )
    return (
        f'    <path d="{d_str}" fill="none" stroke="{color}" stroke-width="{width:.2f}"/>\n'
        f'    <polygon points="{tri}" fill="{color}"/>'
    )


def build_svg() -> str:
    """Return clean, editable SVG matching §2.4 pipeline flow (no empirical values)."""
    nodes = [
        # Col 1: Input & Preprocessing (x=1.5..31.5, w=30.0)
        _node_box(
            "node-input",
            x=1.5,
            y=5.8,
            w=30.0,
            h=13.6,
            fill="#F1F5F9",
            stroke="#334155",
            header_fill="#334155",
            header_h=4.4,
            title="原始观测输入",
            body_lines=["附件 2/3 原始 .dat", "64 阵元(1发63收)交错阵"],
        ),
        _node_box(
            "node-d0",
            x=1.5,
            y=23.2,
            w=30.0,
            h=13.6,
            fill="#EFF6FF",
            stroke="#1D4ED8",
            header_fill="#1D4ED8",
            header_h=4.4,
            title="D0 读取契约",
            body_lines=["协议解析与 sync 交集", "63 路掩码与异常隔离"],
        ),
        _node_box(
            "node-d1",
            x=1.5,
            y=40.6,
            w=30.0,
            h=14.4,
            fill="#EFF6FF",
            stroke="#1D4ED8",
            header_fill="#1D4ED8",
            header_h=4.4,
            title="D1-2 一致性门控折迭",
            body_lines=["包内 4 段相干与 F1/F2 门控", "等权折迭 → 带内频谱"],
        ),
        # Col 2: Q1 Calibration & Direct-Wave Suppression Freeze Pool (outer x=37.5..75.5, inner x=39.2..73.8, w=34.6)
        _node_box(
            "node-q11",
            x=39.2,
            y=11.0,
            w=34.6,
            h=17.0,
            fill="#F0FDFA",
            stroke="#0F766E",
            header_fill="#0F766E",
            header_h=4.5,
            title="Q1.1 通道校准 (M0-Cal-Base)",
            title_size=2.25,
            body_size=2.18,
            body_lines=["对齐聚合与投影正交分解", "Tikhonov 正则比值校准", "纯空场留一 LOO 冻结参数"],
        ),
        _node_box(
            "node-q12",
            x=39.2,
            y=32.5,
            w=34.6,
            h=17.0,
            fill="#F0FDFA",
            stroke="#0F766E",
            header_fill="#0F766E",
            header_h=4.5,
            title="Q1.2 抑直模板 (M0-DW-Base)",
            title_size=2.25,
            body_size=2.18,
            body_lines=["第二奈奎斯特区 RF 镜像对齐", "α=1 减除与 S_eff 模板重构", "输出压缩域响应 z_MF"],
        ),
        # Col 3: Downstream Solving Branches (x=81.5..121.5, w=40.0)
        _node_box(
            "node-q13",
            x=81.5,
            y=5.8,
            w=40.0,
            h=14.0,
            fill="#FFFBEB",
            stroke="#B45309",
            header_fill="#B45309",
            header_h=4.4,
            title="问题 1.3 · 一维平面测距",
            body_lines=["归一化 GLRT 剖面 P_norm,eff", "墙体首峰判别与 10/10 评价"],
        ),
        _node_box(
            "node-q2",
            x=81.5,
            y=23.2,
            w=40.0,
            h=14.2,
            fill="#FFFBEB",
            stroke="#B45309",
            header_fill="#B45309",
            header_h=4.4,
            title="问题 2 · 二维剖面聚焦成像",
            body_lines=["两步封顶增益 M2-Gain-BSEC", "第 4 行聚焦 CohBPA / EnvBPA"],
        ),
        _node_box(
            "node-q3",
            x=81.5,
            y=40.6,
            w=40.0,
            h=14.4,
            fill="#FFFBEB",
            stroke="#B45309",
            header_fill="#B45309",
            header_h=4.4,
            title="问题 3 · 全阵三维成像定位",
            body_lines=["63 路解耦孔径 3D 反向投影", "柱域 3D-NMS 与遮挡阴影诊断"],
        ),
        # Col 4: Independent Verification & Sensitivity Loop (x=128.5..158.5, w=30.0)
        _node_box(
            "node-val",
            x=128.5,
            y=10.5,
            w=30.0,
            h=39.5,
            fill="#FAF5FF",
            stroke="#6B21A8",
            header_fill="#6B21A8",
            header_h=4.8,
            title="独立验证与检验闭环",
            body_lines=[
                "合成 / 校准 / 盲评闭环",
                "跨机器与可复现核查",
                "参数灵敏度与稳定性",
                "多行一致与遮挡对照",
                "物理边界与误差归因",
            ],
        ),
    ]

    arrows = [
        # Input -> D0 -> D1
        _ortho_arrow([(16.5, 19.4), (16.5, 23.2)], "#334155"),
        _ortho_arrow([(16.5, 36.8), (16.5, 40.6)], "#1D4ED8"),
        # D1 -> Q1.1
        _ortho_arrow([(31.5, 47.8), (34.6, 47.8), (34.6, 19.5), (39.2, 19.5)], "#0F766E"),
        # Q1.1 -> Q1.2
        _ortho_arrow([(56.5, 28.0), (56.5, 32.5)], "#0F766E"),
        # Q1.2 freeze output bus -> F1, F2, F3
        '    <path d="M 73.8,41.0 L 77.6,41.0 M 77.6,12.8 L 77.6,47.8" fill="none" stroke="#0F766E" stroke-width="0.52"/>',
        _ortho_arrow([(77.6, 12.8), (81.5, 12.8)], "#0F766E"),
        _ortho_arrow([(77.6, 30.3), (81.5, 30.3)], "#0F766E"),
        _ortho_arrow([(77.6, 47.8), (81.5, 47.8)], "#0F766E"),
        # F1, F2, F3 -> Verification
        _ortho_arrow([(121.5, 12.8), (124.8, 12.8), (124.8, 19.5), (128.5, 19.5)], "#6B21A8"),
        _ortho_arrow([(121.5, 30.3), (128.5, 30.3)], "#6B21A8"),
        _ortho_arrow([(121.5, 47.8), (124.8, 47.8), (124.8, 41.0), (128.5, 41.0)], "#6B21A8"),
        # Controlled N0 feedback loop
        _ortho_arrow([(143.5, 50.0), (143.5, 60.0), (56.5, 60.0), (56.5, 52.2)], "#6B21A8", width=0.45, dashed=True),
    ]

    pool_x, pool_y, pool_w, pool_h, pool_r = 37.5, 5.6, 38.0, 46.4, 2.0
    pool_dash = " ".join([
        _dashed_polyline_d([(pool_x + pool_r, pool_y), (pool_x + pool_w - pool_r, pool_y)], 1.8, 1.2),
        _dashed_polyline_d([(pool_x + pool_w, pool_y + pool_r), (pool_x + pool_w, pool_y + pool_h - pool_r)], 1.8, 1.2),
        _dashed_polyline_d([(pool_x + pool_w - pool_r, pool_y + pool_h), (pool_x + pool_r, pool_y + pool_h)], 1.8, 1.2),
        _dashed_polyline_d([(pool_x, pool_y + pool_h - pool_r), (pool_x, pool_y + pool_r)], 1.8, 1.2),
        f"M {pool_x:.2f},{pool_y + pool_r:.2f} Q {pool_x:.2f},{pool_y:.2f} {pool_x + pool_r:.2f},{pool_y:.2f}",
        f"M {pool_x + pool_w - pool_r:.2f},{pool_y:.2f} Q {pool_x + pool_w:.2f},{pool_y:.2f} {pool_x + pool_w:.2f},{pool_y + pool_r:.2f}",
        f"M {pool_x + pool_w:.2f},{pool_y + pool_h - pool_r:.2f} Q {pool_x + pool_w:.2f},{pool_y + pool_h:.2f} {pool_x + pool_w - pool_r:.2f},{pool_y + pool_h:.2f}",
        f"M {pool_x + pool_r:.2f},{pool_y + pool_h:.2f} Q {pool_x:.2f},{pool_y + pool_h:.2f} {pool_x:.2f},{pool_y + pool_h - pool_r:.2f}",
    ])

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{FIG_WIDTH_MM:.0f}mm" height="{FIG_HEIGHT_MM:.0f}mm" viewBox="0 0 {FIG_WIDTH_MM:.0f} {FIG_HEIGHT_MM:.0f}">
  <g id="stage-backgrounds">
    <rect x="{pool_x:.2f}" y="{pool_y:.2f}" width="{pool_w:.2f}" height="{pool_h:.2f}" rx="{pool_r:.2f}" fill="#F8FAFC" stroke="none"/>
    <path d="{pool_dash}" fill="none" stroke="#0F766E" stroke-width="0.46"/>
    <text x="56.5" y="8.3" text-anchor="middle" dominant-baseline="central" font-family="Microsoft YaHei, SimHei, sans-serif" font-size="1.95" font-weight="700" fill="#0F766E">冻结校准池（空场 + cal · 标签隔离）</text>
  </g>

  <g id="stage-headers">
    <text x="16.5" y="2.6" text-anchor="middle" dominant-baseline="central" font-family="Microsoft YaHei, SimHei, sans-serif" font-size="2.5" font-weight="700" fill="#1E3A8A">一、数据读取与门控</text>
    <text x="56.5" y="2.6" text-anchor="middle" dominant-baseline="central" font-family="Microsoft YaHei, SimHei, sans-serif" font-size="2.5" font-weight="700" fill="#0F766E">二、基准参数冻结</text>
    <text x="101.5" y="2.6" text-anchor="middle" dominant-baseline="central" font-family="Microsoft YaHei, SimHei, sans-serif" font-size="2.5" font-weight="700" fill="#92400E">三、多维求解分支</text>
    <text x="143.5" y="2.6" text-anchor="middle" dominant-baseline="central" font-family="Microsoft YaHei, SimHei, sans-serif" font-size="2.5" font-weight="700" fill="#581C87">四、独立验证闭环</text>
  </g>

{chr(10).join(nodes)}

  <g id="connectors">
{chr(10).join(arrows)}
    <text x="100.0" y="58.2" text-anchor="middle" dominant-baseline="central" font-family="Microsoft YaHei, SimHei, sans-serif" font-size="2.15" fill="#581C87">受控改进消融对照闭环（基准冻结后单因子迭代 · 检验标签仍盲评隔离）</text>
  </g>
</svg>
"""


def export_fig_0_1(out_dir: Path, preview_png: Path | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = out_dir / "fig_0_1_pipeline.svg"
    pdf_path = out_dir / "fig_0_1_pipeline.pdf"

    svg_text = build_svg()
    svg_path.write_text(svg_text, encoding="utf-8")

    svg_doc = pymupdf.open(stream=svg_text.encode("utf-8"), filetype="svg")
    pdf_bytes = svg_doc.convert_to_pdf()
    pdf_path.write_bytes(pdf_bytes)

    pdf_doc = pymupdf.open(str(pdf_path))
    rect = pdf_doc[0].rect
    if preview_png is not None:
        preview_png.parent.mkdir(parents=True, exist_ok=True)
        pix = pdf_doc[0].get_pixmap(dpi=220)
        pix.save(str(preview_png))

    return {
        "svg_path": str(svg_path),
        "pdf_path": str(pdf_path),
        "pages": len(pdf_doc),
        "width_cm": round(rect.width * 2.54 / 72.0, 2),
        "height_cm": round(rect.height * 2.54 / 72.0, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Fig 0-1 editable SVG and PDF.")
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--preview-png", type=Path, default=None)
    args = parser.parse_args()
    info = export_fig_0_1(args.out_dir, args.preview_png)
    print(info)


if __name__ == "__main__":
    main()

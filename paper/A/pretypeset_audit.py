#!/usr/bin/env python3
"""Static pre-typesetting assembler and Word/PDF page-budget auditor for Problem A."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor
import pymupdf
import win32com.client


REPO_ROOT = Path(__file__).resolve().parents[2]
PAPER_DIR = REPO_ROOT / "paper" / "A"


def extract_section_block(path: Path, start_prefix: str, end_prefix: str | None = None) -> str:
    """Extract lines from a markdown draft starting at start_prefix until end_prefix (exclusive)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start_idx = next((i for i, line in enumerate(lines) if line.startswith(start_prefix)), None)
    if start_idx is None:
        raise ValueError(f"Missing start marker {start_prefix!r} in {path}")
    end_idx = len(lines)
    if end_prefix is not None:
        found_end = next(
            (i for i in range(start_idx + 1, len(lines)) if lines[i].startswith(end_prefix)),
            None,
        )
        if found_end is None:
            raise ValueError(f"Missing end marker {end_prefix!r} in {path}")
        end_idx = found_end
    return "\n".join(lines[start_idx:end_idx]).strip()


def normalize_cross_refs(text: str) -> str:
    """Keep unified heading hierarchy consistent inside single-file manuscript."""
    # Convert scaffold ### 九、参考文献 heading to ## 九、参考文献
    text = re.sub(r"^### (九、参考文献.*)$", r"## \1", text, flags=re.MULTILINE)
    return text


def build_toc_lines(body_markdown: str) -> list[str]:
    """Build concise level-2/level-3 TOC lines fitting within <= 0.8 page."""
    toc = []
    for line in body_markdown.splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            toc.append(f"- **{title}** …… `[P.?]`")
        elif line.startswith("### "):
            title = line[4:].strip()
            toc.append(f"  - {title}")
    return toc


def assemble_manuscript() -> str:
    """Assemble full static Problem A manuscript from merged source drafts on main."""
    scaffold = PAPER_DIR / "PAPER_SCAFFOLD.md"
    ch14 = PAPER_DIR / "draft_ch1_4.md"
    ch57 = PAPER_DIR / "draft_ch5_7.md"
    ch810 = PAPER_DIR / "draft_ch8_10.md"

    title_line = "单发多收穿墙雷达频域正则校准与多维聚焦成像模型"
    abstract_block = extract_section_block(scaffold, "### 摘要", "---")
    abstract_block = re.sub(r"^### 摘要.*$", "## 摘要（全量定量结果 `[待补]`）", abstract_block, count=1, flags=re.MULTILINE)

    part_ch14 = extract_section_block(ch14, "## 一、问题重述")
    part_ch57 = extract_section_block(ch57, "## 五、问题一：通道校准、直射波抑制与平面目标测距")
    part_ch8 = extract_section_block(ch810, "## 八、模型评价、适用边界与改进方向", "## 十、AI 使用报告与附录清单")
    part_ch8 = re.sub(r"\n---\s*$", "", part_ch8).strip()
    part_ch9 = normalize_cross_refs(extract_section_block(scaffold, "### 九、参考文献", "---"))
    part_ch10 = extract_section_block(ch810, "## 十、AI 使用报告与附录清单")

    counted_body = "\n\n---\n\n".join([part_ch14, part_ch57, part_ch8, part_ch9])
    toc_block = "## 目录（静态预排版自动索引；合稿定版由 Word 域更新页码）\n\n" + "\n".join(
        build_toc_lines(counted_body + "\n" + part_ch10)
    )

    sections = [
        f"# {title_line}",
        "> **静态预排版合规声明**：本文由主线（`main`）已合入各章静态初稿自动合编生成，仅用于预排页数统计与结果回填空间核算；全部实测指标、实测图表（`Fig 1-1`~`Fig 3-2`、`Table 1-1`~`Table 3-2`、`Table 8-1`）及摘要待测数据仍严格保持 **`[待补]`**。",
        abstract_block,
        toc_block,
        counted_body,
        part_ch10,
    ]
    return "\n\n---\n\n".join(sections) + "\n"


@dataclass(frozen=True)
class ReservedSlotSpec:
    slot_id: str
    height_cm: float
    commentary_chars: int
    description: str


# Conservative sizing per RESULTS_AND_FIGURES_CHECKLIST.md figure types
RESERVED_SLOTS: dict[str, ReservedSlotSpec] = {
    "Fig 0-1": ReservedSlotSpec("Fig 0-1", 6.5, 0, "全题整体技术路线与数据流框图（Mermaid 替换为矢量图）"),
    "Fig 1-1": ReservedSlotSpec("Fig 1-1", 8.5, 160, "2×2 定量网格：代表通道校准前/后波形与带内幅相差谱对比"),
    "Table 1-1": ReservedSlotSpec("Table 1-1", 4.5, 140, "63 路校准参数分布统计与空场 10 折 LOO 残差三线表"),
    "Fig 1-2": ReservedSlotSpec("Fig 1-2", 8.0, 160, "上下双栏对比：代表组直射波抑制前后压缩延迟响应剖面"),
    "Table 1-2": ReservedSlotSpec("Table 1-2", 4.5, 140, "空场 LOO 与先导抑制指标及固定 alpha=1.0 峰保留度三线表"),
    "Fig 1-3": ReservedSlotSpec("Fig 1-3", 8.0, 180, "左：归一化 1D 测距剖面；右：20 组检验误差对比散点/柱图"),
    "Table 1-3": ReservedSlotSpec("Table 1-3", 6.0, 180, "Q1.3 墙体/金属板分区分组（cal / test-interp / test-extrap）测距误差表"),
    "Fig 1-4": ReservedSlotSpec("Fig 1-4", 7.5, 160, "超参摄动敏感度图 + 空场 10 折 LOO 抑制比分布箱线图"),
    "Fig 2-1": ReservedSlotSpec("Fig 2-1", 8.5, 180, "1×2 共享色标 2D 剖面热图 + 典型测线 y 向截面（增益前 vs 增益后）"),
    "Fig 2-2": ReservedSlotSpec("Fig 2-2", 7.5, 160, "左：第 4 行 vs 第 3/5 行多行一致性对比；右：增益参数敏感性曲线"),
    "Table 2-1": ReservedSlotSpec("Table 2-1", 5.0, 160, "Q2 增益前后定量对比与前/后墙表观位置走向回归三线表"),
    "Fig 3-1": ReservedSlotSpec("Fig 3-1", 8.5, 180, "Q3.1 全 63 路墙体三维等值面渲染与三视图正交投影切片"),
    "Table 3-1": ReservedSlotSpec("Table 3-1", 4.5, 140, "Q3.1 前墙 A / 后墙 B 三维界面坐标范围与 Q2 切片对账表"),
    "Fig 3-2": ReservedSlotSpec("Fig 3-2", 8.5, 180, "Q3.2 金属柱与金属铲三维重构图 + 后方墙面阴影衰减对比剖面"),
    "Table 3-2": ReservedSlotSpec("Table 3-2", 5.0, 160, "Q3.2 金属目标主峰/质心/-10 dB 跨度及 ShadowRatio 遮挡统计表"),
}


def set_cell_border_and_height(cell, height_cm: float | None = None, fill_hex: str | None = None) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        '<w:top w:val="single" w:sz="6" w:space="0" w:color="666666"/>'
        '<w:left w:val="single" w:sz="6" w:space="0" w:color="666666"/>'
        '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="666666"/>'
        '<w:right w:val="single" w:sz="6" w:space="0" w:color="666666"/>'
        "</w:tcBorders>"
    )
    tc_pr.append(borders)
    if fill_hex:
        shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
        tc_pr.append(shading)
    if height_cm is not None:
        tr_pr = cell._tc.getparent().get_or_add_trPr()
        tr_height = OxmlElement("w:trHeight")
        tr_height.set(qn("w:val"), str(int(round(height_cm * 567))))
        tr_height.set(qn("w:hRule"), "atLeast")
        tr_pr.append(tr_height)


def apply_run_font(run, font_size_pt: float, bold: bool = False, color: RGBColor | None = None) -> None:
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    run.font.size = Pt(font_size_pt)
    run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def add_styled_paragraph(
    doc: Document,
    text: str,
    font_size_pt: float = 12.0,
    line_spacing: float = 1.25,
    bold: bool = False,
    align=WD_ALIGN_PARAGRAPH.LEFT,
    space_before_pt: float = 0.0,
    space_after_pt: float = 4.0,
    left_indent_cm: float = 0.0,
    color: RGBColor | None = None,
):
    p = doc.add_paragraph()
    p.alignment = align
    fmt = p.paragraph_format
    fmt.line_spacing = line_spacing
    fmt.space_before = Pt(space_before_pt)
    fmt.space_after = Pt(space_after_pt)
    if left_indent_cm > 0:
        fmt.left_indent = Cm(left_indent_cm)
    # Strip markdown bold/code wrappers cleanly while preserving visible text
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    clean = re.sub(r"`([^`]+)`", r"\1", clean)
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
    r = p.add_run(clean)
    apply_run_font(r, font_size_pt=font_size_pt, bold=bold, color=color)
    return p


def add_reserved_box(doc: Document, spec: ReservedSlotSpec, font_size_pt: float, line_spacing: float) -> None:
    tbl = doc.add_table(rows=1, cols=1)
    tbl.autofit = False
    tbl.columns[0].width = Cm(15.6)
    cell = tbl.cell(0, 0)
    cell.width = Cm(15.6)
    set_cell_border_and_height(cell, height_cm=spec.height_cm, fill_hex="F5F7FA")
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(f"[待补预留占位框] {spec.slot_id}（预留高度 {spec.height_cm:.1f} cm）：{spec.description}")
    apply_run_font(r, font_size_pt=10.0, bold=True, color=RGBColor(0x33, 0x44, 0x66))
    if spec.commentary_chars > 0:
        filler = "实测定量对比分析与物理解释预留段" + ("（待独立验收数值落库后撰写完整结果评述与误差归因说明）" * 4)
        filler = filler[: spec.commentary_chars]
        add_styled_paragraph(
            doc,
            f"[待补文字扩写预留 ~{spec.commentary_chars} 字] {filler}",
            font_size_pt=font_size_pt,
            line_spacing=line_spacing,
            space_after_pt=4.0,
            color=RGBColor(0x55, 0x55, 0x55),
        )


def build_docx(
    manuscript_md: str,
    out_docx: Path,
    include_reserved_boxes: bool,
    font_size_pt: float = 12.0,
    line_spacing: float = 1.25,
) -> None:
    """Render manuscript markdown into an A4 competition-layout Word document."""
    doc = Document()
    for sec in doc.sections:
        sec.page_width = Cm(21.0)
        sec.page_height = Cm(29.7)
        sec.top_margin = Cm(2.2)
        sec.bottom_margin = Cm(2.2)
        sec.left_margin = Cm(2.5)
        sec.right_margin = Cm(2.5)

    lines = manuscript_md.splitlines()
    i = 0
    seen_slots: set[str] = set()
    in_code_block = False
    code_lines: list[str] = []
    in_body_ch1_8 = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip internal pre-typesetting preamble blockquote before TOC/Abstract from rendered PDF page 1
        if stripped.startswith("> **静态预排版合规声明**"):
            i += 1
            continue

        # Fence blocks (mermaid or python/powershell snippets)
        if stripped.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lines = []
            else:
                in_code_block = False
                if any("flowchart" in cl for cl in code_lines):
                    if include_reserved_boxes and "Fig 0-1" not in seen_slots:
                        seen_slots.add("Fig 0-1")
                        add_reserved_box(doc, RESERVED_SLOTS["Fig 0-1"], font_size_pt, line_spacing)
                    else:
                        add_styled_paragraph(
                            doc,
                            "\n".join(code_lines),
                            font_size_pt=9.5,
                            line_spacing=1.1,
                            left_indent_cm=0.5,
                        )
                else:
                    add_styled_paragraph(
                        doc,
                        "\n".join(code_lines),
                        font_size_pt=9.5,
                        line_spacing=1.1,
                        left_indent_cm=0.5,
                    )
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # Multi-line display equations $$ ... $$ -> realistic OMML / LaTeX rendered height
        if stripped.startswith("$$"):
            eq_lines = [line]
            if stripped == "$$" or not stripped.endswith("$$") or len(stripped) == 2:
                i += 1
                while i < len(lines):
                    eq_lines.append(lines[i])
                    if lines[i].strip().endswith("$$"):
                        break
                    i += 1
            eq_raw = " ".join(x.strip() for x in eq_lines)
            # Extract equation tag if present so rendered display block uses realistic 1-2 line math height
            tag_m = re.search(r"\\tag\{([^}]+)\}", eq_raw)
            tag_str = f"   ({tag_m.group(1)})" if tag_m else ""
            # Approximate rendered OMML visual line count (~1 line per <=130 LaTeX chars, max 3 lines)
            n_vis_lines = max(1, min(3, (len(eq_raw) + 129) // 130))
            preview = "[公式显示块" + (" / 多行" if n_vis_lines > 1 else "") + f"]{tag_str}"
            if n_vis_lines > 1:
                preview = "\n".join([preview] + ["[公式续行]"] * (n_vis_lines - 1))
            add_styled_paragraph(
                doc,
                preview,
                font_size_pt=max(10.0, font_size_pt - 0.5),
                line_spacing=1.25,
                align=WD_ALIGN_PARAGRAPH.CENTER,
                space_before_pt=3.0,
                space_after_pt=4.0,
                color=RGBColor(0x33, 0x33, 0x33),
            )
            i += 1
            continue

        # Markdown pipe tables
        if stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|---"):
            table_rows: list[list[str]] = []
            header = [c.strip() for c in stripped.strip("|").split("|")]
            table_rows.append(header)
            i += 2  # skip header + separator
            while i < len(lines) and lines[i].strip().startswith("|"):
                row_cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                while len(row_cells) < len(header):
                    row_cells.append("")
                table_rows.append(row_cells[: len(header)])
                i += 1

            tbl = doc.add_table(rows=len(table_rows), cols=len(header))
            tbl.style = "Table Grid"
            for r_idx, row_vals in enumerate(table_rows):
                for c_idx, val in enumerate(row_vals):
                    cell = tbl.cell(r_idx, c_idx)
                    p = cell.paragraphs[0]
                    p.paragraph_format.line_spacing = 1.15
                    p.paragraph_format.space_before = Pt(2)
                    p.paragraph_format.space_after = Pt(2)
                    clean_val = re.sub(r"`([^`]+)`", r"\1", re.sub(r"\*\*(.+?)\*\*", r"\1", val))
                    run = p.add_run(clean_val)
                    apply_run_font(run, font_size_pt=9.5, bold=(r_idx == 0))
            continue

        if stripped == "---":
            i += 1
            continue

        if not stripped:
            i += 1
            continue

        # Headings
        if stripped.startswith("# "):
            add_styled_paragraph(
                doc,
                stripped[2:].strip(),
                font_size_pt=18.0,
                line_spacing=1.3,
                bold=True,
                align=WD_ALIGN_PARAGRAPH.CENTER,
                space_before_pt=6.0,
                space_after_pt=10.0,
            )
        elif stripped.startswith("## "):
            heading_txt = stripped[3:].strip()
            if heading_txt.startswith("一、问题重述"):
                in_body_ch1_8 = True
            elif heading_txt.startswith("九、参考文献") or heading_txt.startswith("十、AI 使用报告"):
                in_body_ch1_8 = False
            # Page breaks before 目录, 一、问题重述, and 十、AI 使用报告与附录清单
            if heading_txt.startswith("目录") or heading_txt.startswith("一、问题重述") or heading_txt.startswith("十、AI 使用报告"):
                doc.add_page_break()
            add_styled_paragraph(
                doc,
                heading_txt,
                font_size_pt=14.0 if not heading_txt.startswith("摘要") else 15.0,
                line_spacing=1.25,
                bold=True,
                align=WD_ALIGN_PARAGRAPH.CENTER if heading_txt.startswith("摘要") else WD_ALIGN_PARAGRAPH.LEFT,
                space_before_pt=8.0,
                space_after_pt=6.0,
            )
        elif stripped.startswith("### "):
            add_styled_paragraph(
                doc,
                stripped[4:].strip(),
                font_size_pt=12.5,
                line_spacing=1.25,
                bold=True,
                space_before_pt=6.0,
                space_after_pt=4.0,
            )
        elif stripped.startswith("#### "):
            add_styled_paragraph(
                doc,
                stripped[5:].strip(),
                font_size_pt=font_size_pt,
                line_spacing=line_spacing,
                bold=True,
                space_before_pt=4.0,
                space_after_pt=2.0,
            )
        elif stripped.startswith(">"):
            add_styled_paragraph(
                doc,
                stripped.lstrip(">").strip(),
                font_size_pt=max(10.0, font_size_pt - 1.0),
                line_spacing=line_spacing,
                left_indent_cm=0.5,
                space_after_pt=4.0,
            )
        else:
            indent = 0.6 if line.startswith("  ") else 0.0
            # Keep TOC bullet entries compact so TOC fits on a single page (0.5-0.8 page budget)
            is_toc_entry = ("……" in stripped or stripped.startswith("- **") or (line.startswith("  - ") and any(k in stripped for k in ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10."))))
            add_styled_paragraph(
                doc,
                stripped,
                font_size_pt=10.5 if is_toc_entry else font_size_pt,
                line_spacing=1.08 if is_toc_entry else line_spacing,
                left_indent_cm=indent,
                space_after_pt=1.0 if is_toc_entry else 3.0,
            )

        # Only inject reserved physical figure/table boxes at real body slot announcements inside Ch.1-Ch.8
        if include_reserved_boxes and in_body_ch1_8:
            for slot_id, spec in RESERVED_SLOTS.items():
                if slot_id != "Fig 0-1" and slot_id in stripped and slot_id not in seen_slots and "[待补" in stripped:
                    seen_slots.add(slot_id)
                    add_reserved_box(doc, spec, font_size_pt, line_spacing)

        i += 1

    out_docx.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_docx))


def word_to_pdf(docx_path: Path, pdf_path: Path) -> None:
    """Convert Word .docx to .pdf using Microsoft Word COM automation."""
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        wb = word.Documents.Open(str(docx_path.resolve()))
        wb.SaveAs(str(pdf_path.resolve()), FileFormat=17)  # wdFormatPDF = 17
        wb.Close(False)
    finally:
        word.Quit()


def analyze_pdf_pages(pdf_path: Path) -> dict:
    """Extract total pages and exact sequential page ranges for each chapter/section."""
    doc = pymupdf.open(str(pdf_path))
    markers = [
        ("title_abstract", "单发多收穿墙雷达频域正则校准与多维聚焦成像模型"),
        ("toc", "目录（静态预排版自动索引"),
        ("ch1", "一、问题重述"),
        ("ch2", "二、问题分析"),
        ("ch3", "三、模型假设与符号说明"),
        ("ch4", "四、数据读取与周期一致性预处理"),
        ("ch5", "五、问题一：通道校准、直射波抑制与平面目标测距"),
        ("ch6", "六、问题二：远距离回波增益补偿与墙体二维剖面成像"),
        ("ch7", "七、问题三：全阵列墙体与金属目标三维成像"),
        ("ch8", "八、模型评价、适用边界与改进方向"),
        ("ch9", "九、参考文献"),
        ("ch10_appendix", "十、AI 使用报告与附录清单"),
    ]
    starts: dict[str, int] = {}
    # Find sequential chapter headings ignoring TOC lines (which have '……' or follow '目录')
    # Find TOC span (from toc start up to last page containing '……' or '目录' entries)
    for page_idx in range(len(doc)):
        txt = doc[page_idx].get_text()
        if "title_abstract" not in starts and markers[0][1] in txt:
            starts["title_abstract"] = page_idx + 1
        if "toc" not in starts and markers[1][1] in txt:
            starts["toc"] = page_idx + 1
        if "toc" in starts and "……" in txt:
            min_body_page = page_idx + 2  # Body starts strictly after the last TOC page

    # Scan sequentially starting from body ch1 so page numbers strictly advance
    next_marker_idx = 2
    for page_idx in range(min_body_page - 1, len(doc)):
        lines = [ln.strip() for ln in doc[page_idx].get_text().splitlines() if ln.strip()]
        while next_marker_idx < len(markers):
            key, needle = markers[next_marker_idx]
            if any(ln.startswith(needle) and "……" not in ln and not ln.startswith("-") for ln in lines):
                starts[key] = page_idx + 1
                next_marker_idx += 1
            else:
                break

    total_pages = len(doc)
    ch10_start = starts.get("ch10_appendix", total_pages + 1)
    counted_pages = ch10_start - 1
    appendix_pages = total_pages - counted_pages

    # Last page fill ratio of counted body (how full is page `counted_pages`)
    last_counted_fill = 0.0
    if 1 <= counted_pages <= total_pages:
        blocks = doc[counted_pages - 1].get_text("blocks")
        if blocks:
            max_y = max(b[3] for b in blocks)
            page_h = doc[counted_pages - 1].rect.height
            usable_h = page_h - 124.8
            last_counted_fill = max(0.0, min(1.0, (max_y - 62.4) / usable_h))

    return {
        "total_pdf_pages": total_pages,
        "counted_pages_excl_ch10": counted_pages,
        "appendix_pages": appendix_pages,
        "headroom_to_25_pages": round(25 - counted_pages + (1.0 - last_counted_fill), 2),
        "last_counted_page_fill_ratio": round(last_counted_fill, 3),
        "section_start_pages": starts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble static manuscript and audit page budget.")
    parser.add_argument("--work-dir", type=Path, required=True, help="Temporary directory for generated docx/pdf files.")
    parser.add_argument("--write-manuscript", action="store_true", help="Write paper/A/manuscript_pretypeset.md.")
    args = parser.parse_args()

    manuscript_md = assemble_manuscript()
    if args.write_manuscript:
        (PAPER_DIR / "manuscript_pretypeset.md").write_text(manuscript_md, encoding="utf-8")

    configs = [
        ("static_baseline_12pt", False, 12.0, 1.25),
        ("reserved_full_12pt", True, 12.0, 1.25),
        ("reserved_compact_10_5pt", True, 10.5, 1.15),
    ]
    results = {}
    for label, with_boxes, font_pt, spacing in configs:
        docx_p = args.work_dir / f"{label}.docx"
        pdf_p = args.work_dir / f"{label}.pdf"
        build_docx(manuscript_md, docx_p, include_reserved_boxes=with_boxes, font_size_pt=font_pt, line_spacing=spacing)
        word_to_pdf(docx_p, pdf_p)
        results[label] = analyze_pdf_pages(pdf_p)
        results[label]["font_pt"] = font_pt
        results[label]["line_spacing"] = spacing
        results[label]["include_reserved_boxes"] = with_boxes

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

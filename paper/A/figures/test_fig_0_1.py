#!/usr/bin/env python3
"""Validation checks for Fig 0-1 editable SVG and print-ready vector PDF."""

from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf

from build_fig_0_1 import build_svg, export_fig_0_1


FIG_DIR = Path(__file__).resolve().parent
SVG_PATH = FIG_DIR / "fig_0_1_pipeline.svg"
PDF_PATH = FIG_DIR / "fig_0_1_pipeline.pdf"

MAX_WIDTH_CM = 16.6
MAX_HEIGHT_CM = 6.5

EXPECTED_GROUP_IDS = {
    "stage-backgrounds",
    "stage-headers",
    "node-input",
    "node-d0",
    "node-d1",
    "node-q11",
    "node-q12",
    "node-q13",
    "node-q2",
    "node-q3",
    "node-val",
    "connectors",
}

FORBIDDEN_EMPIRICAL_TOKENS = (
    "待补",
    "4.19",
    "2.98",
    "6.18",
    "5.84",
    "0.030",
    "RMSE",
    "MAE",
)


class Fig01Tests(unittest.TestCase):
    def test_svg_is_valid_editable_and_workflow_only(self) -> None:
        self.assertTrue(SVG_PATH.exists(), f"Missing {SVG_PATH}")
        svg_text = SVG_PATH.read_text(encoding="utf-8")
        self.assertEqual(svg_text, build_svg(), "Tracked SVG is out of sync with build_fig_0_1.py")

        root = ET.fromstring(svg_text)
        self.assertTrue(root.tag.endswith("svg"))
        group_ids = {elem.attrib["id"] for elem in root.iter() if elem.tag.endswith("g") and "id" in elem.attrib}
        self.assertTrue(EXPECTED_GROUP_IDS.issubset(group_ids), f"Missing groups: {EXPECTED_GROUP_IDS - group_ids}")

        text_content = "\n".join(
            (elem.text or "") for elem in root.iter() if elem.tag.endswith("text")
        )
        for token in ("D0", "D1-2", "M0-Cal-Base", "M0-DW-Base", "问题 1.3", "问题 2", "问题 3", "独立验证与检验闭环"):
            self.assertIn(token, text_content)
        for forbidden in FORBIDDEN_EMPIRICAL_TOKENS:
            self.assertNotIn(forbidden, text_content, f"Unexpected empirical token {forbidden!r} in workflow figure")

    def test_pdf_budget_and_grayscale_contrast(self) -> None:
        self.assertTrue(PDF_PATH.exists(), f"Missing {PDF_PATH}")
        doc = pymupdf.open(str(PDF_PATH))
        self.assertEqual(len(doc), 1)
        rect = doc[0].rect
        width_cm = rect.width * 2.54 / 72.0
        height_cm = rect.height * 2.54 / 72.0
        self.assertLessEqual(width_cm, MAX_WIDTH_CM)
        self.assertLessEqual(height_cm, MAX_HEIGHT_CM)

        gray = doc[0].get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
        samples = gray.samples
        self.assertGreater(len(samples), 0)
        self.assertLess(min(samples), 80, "Expected dark ink strokes/headers in grayscale render")
        self.assertEqual(max(samples), 255, "Expected clean white paper background")
        ink_fraction = sum(1 for px in samples if px < 220) / len(samples)
        self.assertGreater(ink_fraction, 0.04)

    def test_reproducible_export_to_temp_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            info = export_fig_0_1(Path(tmp))
            self.assertEqual(info["pages"], 1)
            self.assertLessEqual(info["width_cm"], MAX_WIDTH_CM)
            self.assertLessEqual(info["height_cm"], MAX_HEIGHT_CM)
            self.assertTrue(Path(info["svg_path"]).exists())
            self.assertTrue(Path(info["pdf_path"]).exists())


if __name__ == "__main__":
    unittest.main()

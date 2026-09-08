#!/usr/bin/env python3
"""Convert an EPUB file to PDF using headless Google Chrome."""

from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def epub_to_pdf(epub_path: Path, pdf_path: Path) -> Path:
    if not epub_path.is_file():
        raise FileNotFoundError(f"EPUB not found: {epub_path}")

    with zipfile.ZipFile(epub_path, "r") as zf:
        # 1. Locate rootfile from META-INF/container.xml
        container_data = zf.read("META-INF/container.xml")
        container_root = ET.fromstring(container_data)
        rootfile_elem = container_root.find(".//{*}rootfile")
        if rootfile_elem is None:
            raise ValueError("Invalid EPUB: no rootfile in container.xml")
        opf_path = rootfile_elem.attrib["full-path"]
        opf_dir = Path(opf_path).parent

        # 2. Parse OPF manifest & spine
        opf_data = zf.read(opf_path)
        opf_root = ET.fromstring(opf_data)

        manifest = {}
        for item in opf_root.findall(".//{*}manifest/{*}item"):
            item_id = item.attrib["id"]
            href = item.attrib["href"]
            media_type = item.attrib.get("media-type", "")
            manifest[item_id] = (href, media_type)

        spine_items = []
        for itemref in opf_root.findall(".//{*}spine/{*}itemref"):
            idref = itemref.attrib["idref"]
            if idref in manifest:
                spine_items.append(manifest[idref][0])

        # 3. Read title and author metadata
        title_elem = opf_root.find(".//{*}metadata/{*}title")
        author_elem = opf_root.find(".//{*}metadata/{*}creator")
        title = title_elem.text if title_elem is not None and title_elem.text else epub_path.stem
        author = author_elem.text if author_elem is not None and author_elem.text else ""

        # 4. Helper to inline images as data URIs
        def inline_images(html_text: str, current_dir: Path) -> str:
            def replace_img(match: re.Match[str]) -> str:
                src = match.group(1)
                if src.startswith("data:") or src.startswith("http"):
                    return match.group(0)
                img_rel = (current_dir / src).as_posix()
                # Normalize relative path components
                img_rel_parts: list[str] = []
                for p in img_rel.split("/"):
                    if p == "..":
                        if img_rel_parts:
                            img_rel_parts.pop()
                    elif p and p != ".":
                        img_rel_parts.append(p)
                clean_img_path = "/".join(img_rel_parts)
                try:
                    raw_img = zf.read(clean_img_path)
                    mime, _ = mimetypes.guess_type(clean_img_path)
                    mime = mime or "image/jpeg"
                    b64 = base64.b64encode(raw_img).decode("ascii")
                    return f'src="data:{mime};base64,{b64}"'
                except KeyError:
                    return match.group(0)

            return re.sub(r'src=["\']([^"\']+)["\']', replace_img, html_text)

        # 5. Extract and concatenate chapters
        combined_body_parts = []
        for href in spine_items:
            full_item_path = (opf_dir / href).as_posix() if str(opf_dir) != "." else href
            # Normalize path
            norm_parts: list[str] = []
            for p in full_item_path.split("/"):
                if p == "..":
                    if norm_parts:
                        norm_parts.pop()
                elif p and p != ".":
                    norm_parts.append(p)
            clean_item_path = "/".join(norm_parts)
            try:
                raw_bytes = zf.read(clean_item_path)
            except KeyError:
                continue

            html_text = raw_bytes.decode("utf-8", errors="replace")
            # Inline images
            html_text = inline_images(html_text, Path(clean_item_path).parent)

            # Extract body contents
            body_match = re.search(r"<body[^>]*>(.*?)</body>", html_text, re.DOTALL | re.IGNORECASE)
            if body_match:
                chapter_html = body_match.group(1)
            else:
                chapter_html = html_text

            combined_body_parts.append(
                f'<section class="chapter">{chapter_html}</section>'
            )

    # 6. Build combined HTML document with clean styling
    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  @page {{
    size: A4;
    margin: 20mm 15mm 20mm 15mm;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Georgia, serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #1a1a1a;
    background: #fff;
  }}
  h1, h2, h3, h4 {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    color: #111;
    page-break-after: avoid;
  }}
  h1 {{
    font-size: 20pt;
    margin-top: 24pt;
    margin-bottom: 12pt;
    text-align: center;
  }}
  h2 {{
    font-size: 16pt;
    margin-top: 18pt;
    margin-bottom: 8pt;
  }}
  p {{
    margin-top: 0;
    margin-bottom: 10pt;
    text-align: justify;
  }}
  .chapter {{
    page-break-after: always;
  }}
  .chapter:last-child {{
    page-break-after: auto;
  }}
  img {{
    max-width: 90%;
    height: auto;
    display: block;
    margin: 12pt auto;
    page-break-inside: avoid;
  }}
</style>
</head>
<body>
{chr(10).join(combined_body_parts)}
</body>
</html>
"""

    with tempfile.NamedTemporaryFile("w", suffix=".html", encoding="utf-8", delete=False) as tmp_html:
        tmp_html.write(full_html)
        tmp_html_path = tmp_html.name

    try:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            CHROME_BIN,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path.resolve()}",
            f"file://{tmp_html_path}",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0 or not pdf_path.exists():
            raise RuntimeError(f"Chrome PDF generation failed (code {res.returncode}): {res.stderr}")
    finally:
        if os.path.exists(tmp_html_path):
            os.remove(tmp_html_path)

    return pdf_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert EPUB to PDF via headless Chrome")
    parser.add_argument("epub", type=Path, help="Input EPUB file path")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output PDF path")
    args = parser.parse_args()

    out_pdf = args.output or args.epub.with_suffix(".pdf")
    res_path = epub_to_pdf(args.epub, out_pdf)
    print(f"Generated PDF: {res_path}")


if __name__ == "__main__":
    main()

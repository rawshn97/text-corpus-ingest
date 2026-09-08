#!/usr/bin/env python3
"""Convert an EPUB file to styled PDF using headless Google Chrome / Chromium."""

from __future__ import annotations

import argparse
import base64
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


def find_chrome_binary() -> str:
    """Discover Chrome or Chromium binary across macOS, Linux, or custom environment."""
    env_bin = os.getenv("CHROME_BIN") or os.getenv("GOOGLE_CHROME_BIN")
    if env_bin and os.path.isfile(env_bin):
        return env_bin

    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    for name in [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ]:
        found = shutil.which(name)
        if found:
            return found

    return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def epub_to_pdf(epub_path: Path, pdf_path: Path, chrome_bin: str | None = None) -> Path:
    """Extract EPUB content, assemble styled HTML, and render to PDF via headless browser."""
    if not epub_path.is_file():
        raise FileNotFoundError(f"EPUB not found: {epub_path}")

    chrome_exec = chrome_bin or find_chrome_binary()
    if not os.path.isfile(chrome_exec) and not shutil.which(chrome_exec):
        raise FileNotFoundError(
            f"Chrome/Chromium binary not found at {chrome_exec}. "
            f"Set CHROME_BIN environment variable or install Google Chrome."
        )

    with zipfile.ZipFile(epub_path, "r") as zf:
        # 1. Locate rootfile from META-INF/container.xml
        container_data = zf.read("META-INF/container.xml")
        container_root = ET.fromstring(container_data)
        rootfile_elem = container_root.find(".//{*}rootfile")
        if rootfile_elem is None:
            raise ValueError("Invalid EPUB: no rootfile in container.xml")
        opf_path = rootfile_elem.attrib["full-path"]
        opf_dir = Path(opf_path).parent

        # 2. Parse OPF manifest and spine
        opf_data = zf.read(opf_path)
        opf_root = ET.fromstring(opf_data)

        manifest: dict[str, tuple[str, str]] = {}
        for item in opf_root.findall(".//{*}manifest/{*}item"):
            item_id = item.attrib["id"]
            href = item.attrib["href"]
            media_type = item.attrib.get("media-type", "")
            manifest[item_id] = (href, media_type)

        spine_items: list[str] = []
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
                if src.startswith(("data:", "http")):
                    return match.group(0)
                img_rel = (current_dir / src).as_posix()
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
        combined_body_parts: list[str] = []
        for href in spine_items:
            full_item_path = (opf_dir / href).as_posix() if str(opf_dir) != "." else href
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

            chapter_html = raw_bytes.decode("utf-8", errors="replace")
            chapter_html = inline_images(chapter_html, Path(clean_item_path).parent)

            body_match = re.search(
                r"<body[^>]*>(.*?)</body>", chapter_html, re.DOTALL | re.IGNORECASE
            )
            if body_match:
                chapter_body = body_match.group(1)
            else:
                chapter_body = chapter_html

            combined_body_parts.append(f'<section class="chapter">\n{chapter_body}\n</section>')

    # 6. Compose modern styled HTML document
    styled_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  @page {{
    size: A4;
    margin: 2.2cm 2.0cm 2.2cm 2.0cm;
    @bottom-center {{
      content: counter(page);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 9pt;
      color: #718096;
    }}
  }}

  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Georgia, serif;
    font-size: 11pt;
    line-height: 1.68;
    color: #1a202c;
    background-color: #ffffff;
    max-width: 100%;
    margin: 0;
    padding: 0;
  }}

  .cover {{
    page-break-after: always;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    height: 80vh;
    text-align: center;
    padding: 2rem;
  }}

  .cover h1 {{
    font-size: 28pt;
    font-weight: 700;
    color: #2b6cb0;
    margin-bottom: 0.5rem;
    line-height: 1.25;
  }}

  .cover .author {{
    font-size: 16pt;
    color: #4a5568;
    margin-top: 1rem;
    font-style: italic;
  }}

  .chapter {{
    page-break-before: always;
  }}

  h1, h2, h3, h4, h5, h6 {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #2d3748;
    page-break-after: avoid;
    break-after: avoid;
  }}

  h1 {{
    font-size: 20pt;
    margin-top: 2rem;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 0.4rem;
  }}
  h2 {{ font-size: 16pt; margin-top: 1.6rem; }}
  h3 {{ font-size: 13pt; margin-top: 1.2rem; }}

  p {{
    margin-top: 0;
    margin-bottom: 0.85rem;
    text-align: justify;
    text-justify: inter-word;
    orphans: 2;
    widows: 2;
  }}

  img {{
    max-width: 100%;
    height: auto;
    display: block;
    margin: 1.5rem auto;
    page-break-inside: avoid;
  }}

  blockquote {{
    border-left: 3px solid #cbd5e0;
    margin: 1rem 0 1rem 1.5rem;
    padding-left: 1rem;
    color: #4a5568;
    font-style: italic;
  }}

  pre, code {{
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 9.5pt;
    background-color: #edf2f7;
    border-radius: 3px;
  }}

  pre {{
    padding: 1rem;
    overflow-x: auto;
    page-break-inside: avoid;
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 1.5rem 0;
    page-break-inside: avoid;
  }}

  th, td {{
    border: 1px solid #e2e8f0;
    padding: 0.5rem 0.75rem;
    text-align: left;
    font-size: 10pt;
  }}

  th {{
    background-color: #f7fafc;
    font-weight: 600;
  }}
</style>
</head>
<body>

<div class="cover">
  <h1>{title}</h1>
  {f'<div class="author">{author}</div>' if author else ""}
</div>

{"".join(combined_body_parts)}

</body>
</html>
"""

    with tempfile.NamedTemporaryFile(
        "w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp_html:
        tmp_html.write(styled_html)
        tmp_html_path = tmp_html.name

    try:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            chrome_exec,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path.resolve()}",
            f"file://{tmp_html_path}",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0 or not pdf_path.exists():
            raise RuntimeError(
                f"Chrome PDF generation failed (code {res.returncode}): {res.stderr}"
            )
    finally:
        if os.path.exists(tmp_html_path):
            os.remove(tmp_html_path)

    return pdf_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert EPUB to publication-quality PDF via headless Chrome/Chromium"
    )
    parser.add_argument("epub", type=Path, help="Input EPUB file path")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output PDF path (default: <stem>.pdf)",
    )
    parser.add_argument(
        "--chrome-bin", default=None, help="Explicit path to Chrome or Chromium binary"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    out_pdf = args.output or args.epub.with_suffix(".pdf")
    try:
        res_path = epub_to_pdf(args.epub, out_pdf, chrome_bin=args.chrome_bin)
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        logger.error("EPUB to PDF conversion failed: %s", exc)
        return 1

    print(f"Generated PDF: {res_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

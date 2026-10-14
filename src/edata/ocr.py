"""Text of RIK document PDFs, page by page.

Most polling-station decisions are scanned images. Each page is read with the PDF's own
text layer when it has one, otherwise rendered at 300 dpi and read with Tesseract (Serbian
Cyrillic model). OCR text contains recognition errors; the `engine` column says which
method produced each page, and the PDF itself stays in the raw store as the reference.

Needs the `pdftoppm`/`pdftotext` (poppler) and `tesseract` programs, and srp.traineddata in
data/tessdata. Page text is cached under data/ocr/<sha256>/, so reruns only do new files.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
from PIL import Image

from .store import DATA_ROOT
from .tables import write_table

MIN_TEXT_LAYER = 200  # characters on a page before its text layer is trusted
# Tesseract spreads one page over every core by default; keep it to one so a laptop stays cool
os.environ.setdefault("OMP_THREAD_LIMIT", "1")


def _pages(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return 0


def _read_page(pdf: Path, page: int, cache: Path) -> None:
    target = cache / f"{page:04d}.txt"
    if target.exists():
        return
    layer = subprocess.run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(pdf), "-"],
                           capture_output=True, text=True).stdout
    if len(layer.strip()) >= MIN_TEXT_LAYER:
        engine, text = "pdftotext", layer
    else:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", "-f", str(page), "-l", str(page),
                            "-singlefile", str(pdf), f"{tmp}/p"], capture_output=True)
            tessdata = ["--tessdata-dir", str(DATA_ROOT / "tessdata")]
            osd = subprocess.run(["tesseract", f"{tmp}/p.png", "-", *tessdata, "--psm", "0"],
                                 capture_output=True, text=True).stdout
            rotate = re.search(r"Rotate: (\d+)", osd)
            if rotate and rotate.group(1) != "0":  # page scanned sideways or upside down
                with Image.open(f"{tmp}/p.png") as im:
                    im.rotate(-int(rotate.group(1)), expand=True).save(f"{tmp}/p.png")
            text = subprocess.run(
                ["tesseract", f"{tmp}/p.png", "-", "--tessdata-dir", str(DATA_ROOT / "tessdata"),
                 "-l", "srp", "--psm", "6"], capture_output=True, text=True).stdout
        engine = "tesseract-srp"
    (cache / f"{page:04d}.engine").write_text(engine)
    target.write_text(text)


def run(doc_types: str = "3", workers: int = 1) -> dict[str, int]:
    con = duckdb.connect()
    docs = con.execute(
        f"""SELECT DISTINCT round_id, doc_type, municipality_display_name, document_name,
                   published_at_unix, file_url, local_path, file_sha256
            FROM read_parquet('{DATA_ROOT}/parsed/rik_documents/documents.parquet')
            WHERE local_path LIKE '%.pdf' AND list_contains(?, doc_type)""",
        [doc_types.split(",")]).fetchall()
    jobs = []
    for doc in docs:
        pdf, cache = DATA_ROOT / doc[6], DATA_ROOT / "ocr" / doc[7]
        cache.mkdir(parents=True, exist_ok=True)
        jobs += [(pdf, page, cache) for page in range(1, _pages(pdf) + 1)]
    print(f"ocr: {len(docs)} documents, {len(jobs)} pages", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, _ in enumerate(pool.map(lambda job: _read_page(*job), jobs), 1):
            if i % 500 == 0:
                print(f"ocr: {i}/{len(jobs)}", flush=True)
    rows = []
    for doc in docs:
        cache = DATA_ROOT / "ocr" / doc[7]
        for txt in sorted(cache.glob("*.txt")):
            rows.append({"round_id": doc[0], "doc_type": doc[1], "municipality": doc[2],
                         "document_name": doc[3], "published_at_unix": doc[4], "file_url": doc[5],
                         "file_sha256": doc[7], "page": int(txt.stem),
                         "engine": txt.with_suffix(".engine").read_text(), "text": txt.read_text()})
    write_table("derived", "document_pages", rows)
    return {"document_pages": len(rows)}

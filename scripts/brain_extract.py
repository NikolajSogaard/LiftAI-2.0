"""Dump plain text from a 1-based, inclusive page range of a PDF (no image render).

Usage: python scripts/brain_extract.py "<pdf_path>" <start> <end>
Used during brain ingestion to pull a chapter's text from Data/raw_data/.
"""
import sys
import fitz  # PyMuPDF

path, start, end = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
doc = fitz.open(path)
for p in range(start - 1, min(end, doc.page_count)):
    print(f"\n===== PAGE {p + 1} =====")
    print(doc[p].get_text("text").strip())
doc.close()

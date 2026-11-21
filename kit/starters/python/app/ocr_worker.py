"""Optional isolated OCR CLI: python app/ocr_worker.py /private/path/input.pdf.
Never run inside an async API handler. The TS adapter bounds runtime and output.
"""
import json
import os
import sys
from pathlib import Path

def main():
    from PIL import Image
    import pytesseract
    Image.MAX_IMAGE_PIXELS = 25_000_000
    source = Path(sys.argv[1])
    if source.stat().st_size > 10_000_000:
        raise ValueError("Input exceeds 10 MB")
    pages = []
    if source.suffix == ".pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(source))
        try:
            if len(pdf) > 100:
                raise ValueError("PDF exceeds 100 pages")
            for n in range(len(pdf)):
                page = pdf[n]
                width, height = page.get_size()
                if width * height * 4 > 25_000_000:
                    raise ValueError("Rendered page exceeds pixel limit")
                bitmap = page.render(scale=2)
                image = bitmap.to_pil()
                text = pytesseract.image_to_string(image, timeout=15)
                pages.append({"page": n + 1, "text": text})
                image.close()
                bitmap.close()
                page.close()
        finally:
            pdf.close()
    else:
        with Image.open(source) as image:
            if image.width * image.height > 25_000_000:
                raise ValueError("Image exceeds pixel limit")
            pages.append({"page": 1, "text": pytesseract.image_to_string(image, timeout=15)})
    output = json.dumps({"pages": pages, "engine": "tesseract"}, ensure_ascii=False)
    if len(output) > 5_000_000:
        raise ValueError("OCR output exceeds limit")
    print(output)

if __name__ == "__main__":
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    main()

from __future__ import annotations

import os
import argparse
import tempfile
from pathlib import Path
from tkinter import Tk, filedialog, messagebox


PROJECT_DIR = Path(__file__).resolve().parent
ASCII_CACHE_ROOT = Path(os.environ.get("LOCALAPPDATA", r"C:\Temp")) / "paddleocr_codex"
ASCII_CACHE_ROOT.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("USERPROFILE", str(ASCII_CACHE_ROOT / "home"))
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(ASCII_CACHE_ROOT / "paddlex-cache"))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import pypdfium2 as pdfium
from paddleocr import PaddleOCR


def ask_pdf_path() -> Path | None:
    root = Tk()
    root.withdraw()
    root.update()

    selected = filedialog.askopenfilename(
        title="Select a PDF for PaddleOCR",
        filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
    )
    root.destroy()
    return Path(selected) if selected else None


def ask_output_path(pdf_path: Path) -> Path | None:
    root = Tk()
    root.withdraw()
    root.update()

    selected = filedialog.asksaveasfilename(
        title="Save OCR text as",
        defaultextension=".txt",
        initialfile=f"{pdf_path.stem}_paddleocr.txt",
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
    )
    root.destroy()
    return Path(selected) if selected else None


def extract_text_from_result(result: object) -> list[str]:
    if isinstance(result, dict):
        texts = result.get("rec_texts")
        if isinstance(texts, list):
            return [str(text).strip() for text in texts if str(text).strip()]

    if isinstance(result, list):
        lines: list[str] = []
        for item in result:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                text_part = item[1]
                if isinstance(text_part, (list, tuple)) and text_part:
                    lines.append(str(text_part[0]).strip())
        return [line for line in lines if line]

    return []


def show_done(out_path: Path) -> None:
    root = Tk()
    root.withdraw()
    messagebox.showinfo("PaddleOCR", f"OCR complete.\n\nSaved to:\n{out_path}")
    root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PaddleOCR on a PDF.")
    parser.add_argument("--pdf", type=Path, help="PDF file to OCR.")
    parser.add_argument("--out", type=Path, help="Output text file.")
    parser.add_argument("--device", choices=["cpu", "gpu"], default="cpu")
    parser.add_argument("--scale", type=float, default=1.5)
    parser.add_argument("--pages", type=int, default=0, help="0 means all pages.")
    args = parser.parse_args()

    runtime_device = "gpu:0" if args.device == "gpu" else "cpu"

    pdf_path = args.pdf or ask_pdf_path()
    if pdf_path is None:
        print("Canceled.")
        return

    out_path = args.out or ask_output_path(pdf_path)
    if out_path is None:
        print("Canceled.")
        return

    print("Loading PaddleOCR. The first run may download OCR models.")
    ocr = PaddleOCR(
        lang="korean",
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device=runtime_device,
        enable_mkldnn=False,
        enable_cinn=False,
    )

    doc = pdfium.PdfDocument(str(pdf_path))
    page_count = len(doc) if args.pages <= 0 else min(args.pages, len(doc))
    output: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        for page_index in range(page_count):
            page_number = page_index + 1
            print(f"OCR page {page_number}/{page_count} on {runtime_device}")

            image_path = tmp_path / f"page_{page_number:04d}.png"
            page = doc[page_index]
            image = page.render(scale=args.scale).to_pil()
            image.save(image_path)

            results = ocr.predict(str(image_path))
            lines: list[str] = []
            for result in results:
                lines.extend(extract_text_from_result(result))

            output.append(f"--- page {page_number} ---")
            output.extend(lines if lines else ["(no text found)"])
            output.append("")

    out_path.write_text("\n".join(output), encoding="utf-8")
    print(f"Saved OCR text to {out_path}")
    show_done(out_path)


if __name__ == "__main__":
    main()

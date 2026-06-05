from __future__ import annotations

import argparse
from pathlib import Path
from tkinter import Tk, filedialog, messagebox

import fitz


def extract_text(pdf_path: Path) -> str:
    parts: list[str] = []

    with fitz.open(pdf_path) as doc:
        for page_index, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            parts.append(f"--- page {page_index} ---")
            parts.append(text if text else "(no text found)")

    return "\n\n".join(parts)


def ask_pdf_path() -> Path | None:
    root = Tk()
    root.withdraw()
    root.update()

    pdf_file = filedialog.askopenfilename(
        title="Select a PDF to extract text from",
        filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
    )
    if not pdf_file:
        root.destroy()
        return None

    root.destroy()
    return Path(pdf_file)


def ask_output_path(pdf_path: Path) -> Path | None:
    root = Tk()
    root.withdraw()
    root.update()

    default_name = f"{pdf_path.stem}_extracted.txt"
    out_file = filedialog.asksaveasfilename(
        title="Save extracted text as",
        defaultextension=".txt",
        initialfile=default_name,
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
    )
    if not out_file:
        root.destroy()
        return None

    root.destroy()
    return Path(out_file)


def show_done(out_path: Path) -> None:
    root = Tk()
    root.withdraw()
    messagebox.showinfo("PyMuPDF", f"Text extraction complete.\n\nSaved to:\n{out_path}")
    root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract text from a PDF with PyMuPDF.")
    parser.add_argument("pdf", nargs="?", type=Path, help="Path to the PDF file.")
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        help="Output .txt file. If omitted, a save dialog opens.",
    )
    args = parser.parse_args()

    if args.pdf:
        pdf_path = args.pdf
        out_path = args.out
        if out_path is None:
            out_path = ask_output_path(pdf_path)
            if out_path is None:
                print("Canceled.")
                return
    else:
        pdf_path = ask_pdf_path()
        if pdf_path is None:
            print("Canceled.")
            return
        out_path = ask_output_path(pdf_path)
        if out_path is None:
            print("Canceled.")
            return

    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    text = extract_text(pdf_path)

    out_path.write_text(text, encoding="utf-8")
    print(f"Saved extracted text to {out_path}")

    try:
        show_done(out_path)
    except Exception:
        pass


if __name__ == "__main__":
    main()

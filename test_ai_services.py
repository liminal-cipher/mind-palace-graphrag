from __future__ import annotations

import argparse
import os
from pathlib import Path
from tkinter import Tk, filedialog

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".ENV")
load_dotenv(PROJECT_DIR / ".env")


def first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def require_env(label: str, *names: str) -> str:
    value = first_env(*names)
    if value:
        print(f"[OK] {label}: found")
        return value

    print(f"[MISSING] {label}: set one of {', '.join(names)}")
    raise SystemExit(1)


def ask_pdf_path() -> Path | None:
    root = Tk()
    root.withdraw()
    root.update()
    selected = filedialog.askopenfilename(
        title="Select a PDF for Document Intelligence",
        filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
    )
    root.destroy()
    return Path(selected) if selected else None


def test_openai() -> None:
    from openai import OpenAI

    api_key = require_env("OpenAI API key", "OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    print(f"[INFO] OpenAI model: {model}")
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input="Reply with exactly this Korean text: OpenAI 연결 테스트 성공",
    )

    print("[OK] OpenAI response:")
    print(response.output_text)


def test_document_intelligence(pdf_path: Path | None, out_path: Path | None) -> None:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    endpoint = require_env(
        "Document Intelligence endpoint",
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT",
        "DOCUMENT_INTELLIGENCE_ENDPOINT",
        "AZURE_FORM_RECOGNIZER_ENDPOINT",
    )
    key = require_env(
        "Document Intelligence key",
        "AZURE_DOCUMENT_INTELLIGENCE_KEY",
        "DOCUMENT_INTELLIGENCE_KEY",
        "AZURE_FORM_RECOGNIZER_KEY",
    )

    if pdf_path is None:
        pdf_path = ask_pdf_path()
    if pdf_path is None:
        print("[CANCELED] No PDF selected.")
        return
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    client = DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    print(f"[INFO] Analyzing PDF: {pdf_path}")
    with pdf_path.open("rb") as file:
        poller = client.begin_analyze_document(
            "prebuilt-read",
            body=file,
            content_type="application/octet-stream",
        )
        result = poller.result()

    text = (result.content or "").strip()
    print("[OK] Document Intelligence response:")
    print(f"pages: {len(result.pages or [])}")
    print(f"characters: {len(text)}")
    print("preview:")
    print(text[:1000] if text else "(no text found)")

    if out_path:
        out_path.write_text(text, encoding="utf-8")
        print(f"[OK] Saved text to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test OpenAI and Azure Document Intelligence.")
    parser.add_argument(
        "service",
        choices=["openai", "document", "all"],
        help="Which service to test.",
    )
    parser.add_argument("--pdf", type=Path, help="PDF file for Document Intelligence test.")
    parser.add_argument("--out", type=Path, help="Optional output text file for OCR result.")
    args = parser.parse_args()

    if args.service in {"openai", "all"}:
        test_openai()

    if args.service in {"document", "all"}:
        test_document_intelligence(args.pdf, args.out)


if __name__ == "__main__":
    main()

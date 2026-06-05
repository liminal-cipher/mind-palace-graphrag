# PDF Lecture Parser MVP - Project Brief

## Goal

Build a Python MVP in VS Code that processes university lecture PDFs.

The user uploads a PDF only. The backend should automatically inspect the PDF, classify pages, route each page or region to the appropriate processing tool, extract text/tables/images/figures, optionally analyze complex visual content, and save structured JSON output that can later be connected to Palace JSON and Azure AI Search.

## Core Idea

Do not send every PDF page directly to an expensive vision model.

Instead:

1. Use PyMuPDF as the first-pass PDF inspector and router.
2. Use cheap direct text extraction for easy text pages.
3. Use Azure Document Intelligence for scanned pages, complex layouts, tables, and image-heavy pages.
4. Use Azure OpenAI GPT-4o Vision only for pages or cropped regions that require semantic visual interpretation.
5. Store all outputs with page number, bbox, source text, source image, evidence, and confidence metadata.

## Tool Roles

### PyMuPDF

Use for:

- Opening PDF files
- Extracting selectable PDF text
- Detecting image objects
- Rendering pages to PNG
- Generating page-level diagnostics
- Creating crops if needed
- First-pass page routing

PyMuPDF is not the main OCR engine. It should not be relied on for text inside images.

### Azure Document Intelligence

Use for:

- OCR on scanned pages
- Layout extraction
- Table extraction
- Reading order
- Complex lecture slides
- Pages with mixed text, tables, and images

Use the `prebuilt-layout` model first.

### Azure OpenAI GPT-4o Vision

Use for:

- Graph interpretation
- Diagram interpretation
- Flowchart interpretation
- Concept explanation
- Slide-level semantic summary
- Exam-oriented learning notes

Do not use this for every page by default because of cost.

### Azure AI Search

Not required in the first MVP.

Later use for:

- Indexing extracted text
- Indexing image descriptions
- Indexing concept metadata
- RAG retrieval

## Page Classification

For each PDF page, classify into one of:

- `easy_text`
- `mostly_text`
- `scan_or_image`
- `mixed_or_figure`
- `complex_layout`
- `unknown`

Suggested heuristic:

- If extracted text length is high and image count is zero: `easy_text`
- If extracted text length is high and image count is low: `mostly_text`
- If extracted text length is very low and image count is high: `scan_or_image`
- If image count is high or the page appears slide-like: `mixed_or_figure`
- If tables/layout complexity are suspected: `complex_layout`

## MVP Pipeline

Implement this initial pipeline:

1. Load PDF.
2. Compute file hash.
3. For each page:
   - Extract selectable text with PyMuPDF.
   - Count image objects.
   - Estimate page type.
   - Save diagnostic metadata.
4. Run Azure Document Intelligence `prebuilt-layout` on the full PDF.
5. Render selected complex pages to PNG with PyMuPDF.
6. Send selected page images to Azure OpenAI GPT-4o Vision for semantic analysis.
7. Merge results into page-level JSON.
8. Save output to `outputs/{document_id}.json`.

## JSON Output Shape

Use this rough structure:

```json
{
  "document_id": "sample_001",
  "file_name": "sample.pdf",
  "pages": [
    {
      "page": 1,
      "page_type": "mixed_or_figure",
      "text_pymupdf": "...",
      "document_intelligence_text": "...",
      "tables": [
        {
          "row_count": 3,
          "column_count": 4,
          "cells": [
            {
              "row_index": 0,
              "column_index": 0,
              "content": "..."
            }
          ]
        }
      ],
      "images": [
        {
          "source_image": "outputs/images/page_1.png",
          "description": "Vision model explanation here",
          "concepts": [],
          "evidence": "",
          "confidence": null
        }
      ]
    }
  ]
}
#!/usr/bin/env python
"""
Test script for the PDF OCR/Translation Pipeline.
"""
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from mehdi_w_clap.pdf_ocr_translate import PDFOCRTranslatePipeline, PageType
    print("SUCCESS: Module imported successfully")

    # Try to create an instance
    pipeline = PDFOCRTranslatePipeline(
        ocr_engine="tesseract",
        ocr_lang="eng",
        preprocessing=True,
        enable_diagnostics=False
    )
    print("SUCCESS: Pipeline instantiated")

    # Check if the OCR processor is initialized
    if pipeline.ocr_processor:
        print("SUCCESS: OCR processor initialized")
    else:
        print("WARNING: OCR processor is None")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
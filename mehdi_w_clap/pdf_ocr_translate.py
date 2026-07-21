"""
PDF OCR/Translation Pipeline for MEHDI system.

Implements a robust pipeline for processing PDFs, especially scanned documents
and those with non-Latin scripts like Urdu Nastaliq.

Features:
1. Per-page text/image detection
2. Configurable image preprocessing (deskew, enhance, denoise, upscale)
3. Confidence-based fallback from OCR to vision-LLM
4. Combined OCR+translation via vision-LLM for low-confidence cases
5. Structured output with confidence flags and human-review hooks
6. Diagnostic reporting for development/tuning
"""
from __future__ import annotations

import logging
import os
import time
import base64
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import fitz  # PyMuPDF
import numpy as np

# Import our local OCR and vision tools
from .ocr_processor import TesseractOCR, EasyOCRReader, create_ocr_processor
# from .vision_tool import preprocess_image_for_ocr, capture_process, VISION_TOOL_DEF  # Not used in this pipeline
from enhanced_assistant.llm_client import (
    call_llm,
    get_llm_provider,
    get_llm_settings,
    ensure_ollama_running,
)

logger = logging.getLogger(__name__)


class PageType(Enum):
    TEXT = "text"
    IMAGE = "image"


class ConfidenceLevel(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class OCRResult:
    """Result from OCR processing on a single page."""
    text: str
    confidence: float  # 0.0 to 1.0
    engine_used: str
    processing_time: float
    raw_data: Any = None  # Engine-specific raw output (e.g., Tesseract dict)


@dataclass
class TranslationResult:
    """Result from translation or OCR+translation."""
    source_text: str
    translation: str
    confidence: ConfidenceLevel
    processing_time: float
    flagged_spans: List[Dict[str, Any]] = field(default_factory=list)
    needs_human_review: bool = False


@dataclass
class PageProcessResult:
    """Result of processing a single PDF page."""
    page_number: int
    page_type: PageType
    ocr_result: Optional[OCRResult] = None
    translation_result: Optional[TranslationResult] = None
    processing_time: float = 0.0
    needs_human_review: bool = False
    debug_info: Dict[str, Any] = field(default_factory=dict)


class PDFOCRTranslatePipeline:
    """
    Main pipeline for processing PDFs with OCR and translation.
    """

    def __init__(
        self,
        ocr_engine: str = "tesseract",
        ocr_lang: str = "eng",
        preprocessing: bool = True,
        ocr_confidence_threshold: float = 0.6,
        urdu_ocr_confidence_threshold: float = 0.4,  # Stricter for Urdu/Nastaliq
        vision_llm_prompt: Optional[str] = None,
        enable_diagnostics: bool = False,
    ):
        """
        Initialize the pipeline.

        Args:
            ocr_engine: OCR engine to use ("tesseract" or "easyocr")
            ocr_lang: Language code(s) for OCR (e.g., "eng", "urd", "eng+urd")
            preprocessing: Whether to apply image preprocessing
            ocr_confidence_threshold: Confidence threshold for general OCR acceptance
            urdu_ocr_confidence_threshold: Confidence threshold for Urdu-specific OCR
            vision_llm_prompt: Custom prompt for vision-LLM (if None, uses default)
            enable_diagnostics: Whether to save debug images and verbose logging
        """
        self.ocr_engine = ocr_engine
        self.ocr_lang = ocr_lang
        self.preprocessing = preprocessing
        self.ocr_confidence_threshold = ocr_confidence_threshold
        self.urdu_ocr_confidence_threshold = urdu_ocr_confidence_threshold
        self.enable_diagnostics = enable_diagnostics

        # Initialize OCR processor
        self.ocr_processor = create_ocr_processor(engine=ocr_engine, lang=ocr_lang)

        # Default vision-LLM prompt for OCR+translation
        self.vision_llm_prompt = vision_llm_prompt or (
            "You are an expert OCR and translation system. "
            "Given the image of a document page, perform the following:\n"
            "1. Extract all text from the image (transcribe)\n"
            "2. Translate the extracted text into English\n"
            "3. For any uncertain parts (especially proper nouns, numbers, dates, or unclear symbols), "
            "   flag them with explanations and provide alternatives if possible.\n"
            "Output MUST be a valid JSON object with the following structure:\n"
            "{\n"
            "  \"source_transcription\": \"...\",\n"
            "  \"translation\": \"...\",\n"
            "  \"confidence\": \"high|medium|low\",\n"
            "  \"flagged_spans\": [\n"
            "    {\n"
            "      \"source_text\": \"...\",\n"
            "      \"translated_text\": \"...\",\n"
            "      \"reason\": \"ambiguous_stroke|proper_noun|unclear_scan|low_context\",\n"
            "      \"suggested_alternatives\": [\"...\", \"...\"]\n"
            "    }\n"
            "  ],\n"
            "  \"needs_human_review\": true\n"
            "}\n"
            "If you are confident in the entire transcription and translation, set "
            "\"needs_human_review\" to false and \"flagged_spans\" to an empty array.\n"
            "Do not include any text outside the JSON object."
        )

        # Diagnostics directory
        if self.enable_diagnostics:
            self.debug_dir = Path("debug_pipeline")
            self.debug_dir.mkdir(exist_ok=True)
            (self.debug_dir / "original").mkdir(exist_ok=True)
            (self.debug_dir / "processed").mkdir(exist_ok=True)

    def _is_ursu_script(self) -> bool:
        """Check if the configured language includes Urdu."""
        urd_codes = ["urd", "urdu", "ur"]
        return any(code in self.ocr_lang.lower() for code in urd_codes)

    def _get_ocr_confidence_threshold(self) -> float:
        """Get the appropriate confidence threshold based on language."""
        if self._is_ursu_script():
            return self.urdu_ocr_confidence_threshold
        return self.ocr_confidence_threshold

    def _convert_pdf_page_to_image(
        self,
        pdf_doc: fitz.Document,
        page_num: int,
        dpi: int = 300,
    ) -> np.ndarray:
        """
        Convert a PDF page to a high-resolution image.

        Args:
            pdf_doc: PyMuPDF document object
            page_num: Page number (0-indexed)
            dpi: Resolution for rendering (default 300 for OCR)

        Returns:
            Image as numpy array in BGR format
        """
        page = pdf_doc.load_page(page_num)
        # Set up the transformation matrix for the desired DPI
        zoom = dpi / 72.0  # 72 is the default DPI in PDF
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # Convert to numpy array (OpenCV BGR format)
        img_data = pix.samples
        img = np.frombuffer(img_data, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        # PyMuPDF gives RGB, OpenCV uses BGR
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        return img

    def _detect_page_type(
        self,
        pdf_doc: fitz.Document,
        page_num: int,
        text_length_threshold: int = 50,
    ) -> Tuple[PageType, Dict[str, Any]]:
        """
        Determine if a PDF page contains extractable text or is image-based.

        Args:
            pdf_doc: PyMuPDF document object
            page_num: Page number (0-indexed)
            text_length_threshold: Minimum text length to consider as text-based

        Returns:
            (PageType, details_dict)
        """
        page = pdf_doc.load_page(page_num)
        text = page.get_text("text")
        text = text.strip()

        details = {
            "text_length": len(text),
            "text_preview": text[:100] if text else "",
        }

        if len(text) >= text_length_threshold:
            return PageType.TEXT, details
        else:
            return PageType.IMAGE, details

    def _preprocess_image(self, image: np.ndarray) -> np.ndarray:
        """
        Apply preprocessing pipeline to enhance image for OCR.
        Steps: deskew -> adaptive threshold/contrast -> denoise -> ensure adequate DPI.

        Args:
            image: Input image in BGR format

        Returns:
            Preprocessed image (grayscale for OCR)
        """
        start_time = time.time()

        # Step 1: Deskew
        deskewed = self._deskew(image)

        # Step 2: Convert to grayscale and apply adaptive thresholding
        gray = cv2.cvtColor(deskewed, cv2.COLOR_BGR2GRAY)
        # Adaptive thresholding for varying illumination
        processed = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10
        )

        # Step 3: Denoise (non-local means denoising works well for text)
        denoised = cv2.fastNlMeansDenoising(
            processed, h=10, templateWindowSize=7, searchWindowSize=21
        )

        # Step 4: Ensure minimum DPI equivalent (if original was low-res)
        # We'll check the average character width heuristically, but for simplicity,
        # we'll upscale if the image is too small (e.g., < 1000px width)
        height, width = denoised.shape
        if width < 1000:  # Arbitrary threshold; adjust based on testing
            scale_factor = 1000 / width
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            upscaled = cv2.resize(
                denoised, (new_width, new_height), interpolation=cv2.INTER_CUBIC
            )
            processed = upscaled
            if self.enable_diagnostics:
                logger.info(
                    f"Upscaled image from {width}x{height} to {new_width}x{new_height}"
                )
        else:
            processed = denoised

        # Optional: Additional contrast enhancement (CLAHE)
        if self.preprocessing:  # Already determined by constructor
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            processed = clahe.apply(processed)

        if self.enable_diagnostics:
            elapsed = time.time() - start_time
            logger.debug(f"Preprocessing took {elapsed:.2f}s")

        return processed

    def _deskew(self, image: np.ndarray) -> np.ndarray:
        """
        Deskew an image using moment-based skew detection.
        Returns the deskewed image.
        """
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # Threshold to get binary image
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Find coordinates of non-zero pixels
        coords = np.column_stack(np.where(binary > 0))

        # Calculate the angle of the minimum area rectangle
        if len(coords) < 10:  # Too few points, skip deskewing
            return image

        rect = cv2.minAreaRect(coords)
        angle = rect[-1]

        # The angle needs correction based on OpenCV's convention
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        # Avoid over-rotation for near-horizontal lines
        if abs(angle) < 0.5:
            return image

        # Get the center and rotate the image
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )

        if self.enable_diagnostics and abs(angle) > 0.5:
            logger.debug(f"Deskewed by {angle:.2f} degrees")

        return rotated

    def _run_ocr(self, image: np.ndarray) -> OCRResult:
        """
        Run OCR on a preprocessed image and return results with confidence.

        Args:
            image: Preprocessed image (grayscale or BGR)

        Returns:
            OCRResult object
        """
        start_time = time.time()

        # Ensure image is in the format expected by the OCR processor
        # Our OCR processors expect BGR or grayscale; we'll handle both.
        if len(image.shape) == 3:
            # BGR to RGB for Tesseract/EasyOCR (they typically expect RGB)
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            # Grayscale: convert to RGB by stacking
            rgb_image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)

        # Run OCR
        try:
            text = self.ocr_processor.extract_text(rgb_image)
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            text = ""

        # Calculate confidence (this is engine-specific)
        confidence = self._get_ocr_confidence(ocr_result=None if not text else text, image=rgb_image)

        processing_time = time.time() - start_time

        return OCRResult(
            text=text,
            confidence=confidence,
            engine_used=self.ocr_engine,
            processing_time=processing_time,
        )

    def _get_ocr_confidence(self, ocr_result: Optional[str], image: np.ndarray) -> float:
        """
        Estimate OCR confidence. This is a placeholder; real implementations
        would use engine-specific confidence scores.

        For Tesseract, we can use word-level confidences.
        For EasyOCR, we can use the detection confidence.

        Since we abstracted the OCR processor, we'll implement a simple heuristic:
        - If text is empty, confidence = 0.0
        - If text is very short, confidence = 0.3
        - Otherwise, we'll estimate based on character distribution (crude)

        In a production system, we would expose the engine's native confidence.
        For now, we'll return a fixed value for demonstration and let the
        vision-LLM fallback handle uncertain cases.

        TODO: Implement proper confidence scoring per engine.
        """
        if not ocr_result:
            return 0.0

        # Very basic heuristic: longer text with varied characters -> higher confidence
        # This is a placeholder; replace with actual engine confidence.
        if len(ocr_result) < 10:
            return 0.3
        if len(ocr_result) < 50:
            return 0.5

        # Check for ratio of alphanumeric to total characters
        alphanumeric = sum(c.isalnum() or c.isspace() for c in ocr_result)
        if len(ocr_result) == 0:
            return 0.0
        ratio = alphanumeric / len(ocr_result)
        # Scale to 0.4-0.9 range
        return 0.4 + 0.5 * ratio

    def _run_vision_llm_ocr_translate(
        self, image: np.ndarray, page_number: int
    ) -> TranslationResult:
        """
        Use a vision-LLM to perform OCR and translation in one step.

        Args:
            image: Input image (BGR format)
            page_number: Page number for logging

        Returns:
            TranslationResult object
        """
        start_time = time.time()

        # Encode image to base64
        _, buffer = cv2.imencode(".jpg", image)
        img_base64 = base64.b64encode(buffer).decode("utf-8")

        # Prepare message for LLM
        messages = [
            {
                "role": "user",
                "content": "Analyze this image and provide OCR and translation as per instructions.",
                "images": [img_base64],
            }
        ]

        # We'll use a system message to set the behavior
        system_prompt = self.vision_llm_prompt

        try:
            response = call_llm(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Please process this image.", "images": [img_base64]},
                ],
                timeout=60,  # Vision-LLM might take longer
            )
            # Parse the JSON response
            import json

            # The response should be a JSON string in the content field
            result_text = response["content"].strip()
            # Try to extract JSON if there's extra text
            if result_text.startswith("{") and result_text.endswith("}"):
                result_json = json.loads(result_text)
            else:
                # Try to find JSON-like content
                import re

                json_match = re.search(r"\{.*\}", result_text, re.DOTALL)
                if json_match:
                    result_json = json.loads(json_match.group())
                else:
                    raise ValueError("Could not parse JSON from LLM response")

            # Validate and extract fields
            source_text = result_json.get("source_transcription", "")
            translation = result_json.get("translation", "")
            confidence_str = result_json.get("confidence", "low").lower()
            try:
                confidence = ConfidenceLevel(confidence_str)
            except ValueError:
                confidence = ConfidenceLevel.LOW

            flagged_spans = result_json.get("flagged_spans", [])
            needs_human_review = result_json.get("needs_human_reward", False)

            # Ensure flagged_spans is a list of dicts
            if not isinstance(flagged_spans, list):
                flagged_spans = []

            processing_time = time.time() - start_time

            return TranslationResult(
                source_text=source_text,
                translation=translation,
                confidence=confidence,
                processing_time=processing_time,
                flagged_spans=flagged_spans,
                needs_human_review=needs_human_review,
            )
        except Exception as e:
            logger.error(f"Vision-LLM processing failed for page {page_number}: {e}")
            # Fallback: return empty result with low confidence
            return TranslationResult(
                source_text="",
                translation="",
                confidence=ConfidenceLevel.LOW,
                processing_time=time.time() - start_time,
                needs_human_review=True,
                flagged_spans=[
                    {
                        "source_text": "",
                        "translated_text": "",
                        "reason": "llm_processing_error",
                        "suggested_alternatives": [],
                    }
                ],
            )

    def process_pdf(
        self, pdf_path: Union[str, Path]
    ) -> List[PageProcessResult]:
        """
        Process a PDF document page by page.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            List of PageProcessResult objects, one per page
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        doc = fitz.open(pdf_path)
        results = []

        try:
            for page_num in range(len(doc)):
                page_start = time.time()
                logger.info(f"Processing page {page_num + 1}/{len(doc)}")

                # Step 1: Detect page type (text vs image)
                page_type, detect_details = self._detect_page_type(doc, page_num)

                # Initialize result for this page
                page_result = PageProcessResult(
                    page_number=page_num + 1,  # 1-indexed for user
                    page_type=page_type,
                    debug_info={"detection_details": detect_details},
                )

                if page_type == PageType.TEXT:
                    # For text-based pages, we could extract text directly and translate via LLM
                    # But to keep the pipeline focused on OCR/translation of images, we'll
                    # treat text pages as a special case: extract text and send to text-only LLM for translation.
                    # However, the user's request is about image-based pages, so we'll implement
                    # a simple text extraction and translation for completeness.
                    page = doc.load_page(page_num)
                    text = page.get_text("text").strip()

                    if text:
                        # Translate using text-only LLM (faster and cheaper for text)
                        translation_result = self._translate_text(text)
                        page_result.translation_result = translation_result
                    else:
                        # No text found; treat as image
                        page_type = PageType.IMAGE
                        # Fall through to image processing

                if page_type == PageType.IMAGE or not getattr(page_result, "translation_result", None):
                    # Process as image
                    # Step 2: Convert PDF page to image
                    image = self._convert_pdf_page_to_image(doc, page_num)

                    if self.enable_diagnostics:
                        debug_path = self.debug_dir / "original" / f"page_{page_num+1:03d}.png"
                        cv2.imwrite(str(debug_path), image)
                        logger.debug(f"Saved original image to {debug_path}")

                    # Step 3: Preprocess image
                    processed_image = self._preprocess_image(image)

                    if self.enable_diagnostics:
                        debug_path = self.debug_dir / "processed" / f"page_{page_num+1:03d}.png"
                        cv2.imwrite(str(debug_path), processed_image)
                        logger.debug(f"Saved processed image to {debug_path}")

                    # Step 4: Run OCR
                    ocr_result = self._run_ocr(processed_image)
                    page_result.ocr_result = ocr_result
                    page_result.debug_info["ocr_confidence"] = ocr_result.confidence

                    # Step 5: Check if OCR confidence is sufficient
                    confidence_threshold = self.get_ocr_confidence_threshold()
                    if ocr_result.confidence >= confidence_threshold:
                        # OCR is good enough; translate the OCR text
                        translation_result = self._translate_text(ocr_result.text)
                        page_result.translation_result = translation_result
                    else:
                        # OCR confidence low; use vision-LLM for OCR+translation
                        logger.info(
                            f"Page {page_num+1}: OCR confidence {ocr_result.confidence:.2f} < threshold {confidence_threshold}. "
                            f"Using vision-LLM."
                        )
                        translation_result = self._run_vision_llm_ocr_translate(
                            processed_image, page_num + 1
                        )
                        page_result.translation_result = translation_result

                    # Determine if human review is needed
                    if (
                        page_result.translation_result
                        and page_result.translation_result.needs_human_review
                    ):
                        page_result.needs_human_review = True

                page_result.processing_time = time.time() - page_start
                results.append(page_result)

                # Log progress
                logger.info(
                    f"Page {page_num+1} processed in {page_result.processing_time:.2f}s. "
                    f"Type: {page_type.value}, "
                    f"OCR conf: {getattr(page_result.ocr_result, 'confidence', 'N/A') if hasattr(page_result, 'ocr_result') else 'N/A'}, "
                    f"Translation: {'Yes' if page_result.translation_result else 'No'}"
                )

        finally:
            doc.close()

        return results

    def _translate_text(self, text: str) -> TranslationResult:
        """
        Translate plain text using the text-only LLM.
        This is a helper for text-based pages or as a fallback.

        Args:
            text: Text to translate

        Returns:
            TranslationResult object
        """
        if not text.strip():
            return TranslationResult(
                source_text="",
                translation="",
                confidence=ConfidenceLevel.LOW,
                processing_time=0.0,
                needs_human_review=True,
            )

        start_time = time.time()
        try:
            # Use a simple translation prompt
            prompt = f"Translate the following text to English, preserving meaning and tone:\n\n{text}"
            response = call_llm_text(
                prompt=prompt,
                system="You are a professional translator. Provide accurate and natural translations.",
                timeout=30,
            )
            translation = response.strip()

            # For text translation, we assume high confidence unless the output is empty
            confidence = (
                ConfidenceLevel.HIGH
                if translation and len(translation) > len(text) * 0.5
                else ConfidenceLevel.LOW
            )

            return TranslationResult(
                source_text=text,
                translation=translation,
                confidence=confidence,
                processing_time=time.time() - start_time,
                needs_human_review=(confidence == ConfidenceLevel.LOW),
            )
        except Exception as e:
            logger.error(f"Text translation failed: {e}")
            return TranslationResult(
                source_text=text,
                translation="",
                confidence=ConfidenceLevel.LOW,
                processing_time=time.time() - start_time,
                needs_human_review=True,
                flagged_spans=[
                    {
                        "source_text": text,
                        "translated_text": "",
                        "reason": "translation_error",
                        "suggested_alternatives": [],
                    }
                ],
            )

    def get_human_review_items(
        self, results: List[PageProcessResult]
    ) -> List[PageProcessResult]:
        """
        Get a list of pages that require human review.

        Args:
            results: List of PageProcessResult from process_pdf

        Returns:
            Subset of results where needs_human_review is True
        """
        return [r for r in results if r.needs_human_review]

    def generate_diagnostic_report(
        self, results: List[PageProcessResult]
    ) -> Dict[str, Any]:
        """
        Generate a diagnostic report for tuning and debugging.

        Args:
            results: List of PageProcessResult from process_pdf

        Returns:
            Dictionary with statistics and insights
        """
        total_pages = len(results)
        text_pages = sum(1 for r in results if r.page_type == PageType.TEXT)
        image_pages = total_pages - text_pages

        ocr_used = sum(1 for r in results if r.ocr_result is not None)
        vision_llm_used = sum(
            1 for r in results if r.translation_result and r.translation_result.processing_time > 1.0
        )  # Rough heuristic

        low_confidence_ocr = sum(
            1
            for r in results
            if r.ocr_result and r.ocr_result.confidence < self.get_ocr_confidence_threshold()
        )

        needs_review = sum(1 for r in results if r.needs_human_review)

        report = {
            "summary": {
                "total_pages": total_pages,
                "text_pages": text_pages,
                "image_pages": image_pages,
                "ocr_used": ocr_used,
                "vision_llm_used": vision_llm_used,
                "low_confidence_ocr": low_confidence_ocr,
                "needs_human_review": needs_review,
            },
            "averages": {
                "ocr_confidence": (
                    sum(r.ocr_result.confidence for r in results if r.ocr_result) / max(ocr_used, 1)
                ),
                "processing_time_per_page": (
                    sum(r.processing_time for r in results) / total_pages
                ),
            },
            "details": [
                {
                    "page": r.page_number,
                    "type": r.page_type.value,
                    "ocr_confidence": (
                        r.ocr_result.confidence if r.ocr_result else None
                    ),
                    "translation_confidence": (
                        r.translation_result.confidence.value
                        if r.translation_result
                        else None
                    ),
                    "needs_review": r.needs_human_review,
                    "processing_time": r.processing_time,
                }
                for r in results
            ],
        }
        return report


# Convenience function for simple usage
def process_pdf_file(
    pdf_path: str,
    ocr_engine: str = "tesseract",
    ocr_lang: str = "eng",
    preprocessing: bool = True,
    **kwargs,
) -> List[PageProcessResult]:
    """
    Process a PDF file with the OCR/translation pipeline.

    Args:
        pdf_path: Path to the PDF file
        ocr_engine: OCR engine to use
        ocr_lang: Language for OCR
        preprocessing: Whether to apply preprocessing
        **kwargs: Additional arguments to PDFOCRTranslatePipeline

    Returns:
        List of PageProcessResult
    """
    pipeline = PDFOCRTranslatePipeline(
        ocr_engine=ocr_engine,
        ocr_lang=ocr_lang,
        preprocessing=preprocessing,
        **kwargs,
    )
    return pipeline.process_pdf(pdf_path)


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pdf_ocr_translate.py <pdf_path>")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)

    results = process_pdf_file(
        sys.argv[1],
        ocr_engine="tesseract",
        ocr_lang="urd+eng",  # Example: Urdu + English
        preprocessing=True,
        enable_diagnostics=True,
    )

    print(f"\nProcessed {len(results)} pages")
    for res in results:
        print(
            f"Page {res.page_number}: {res.page_type.value} | "
            f"OCR: {res.ocr_result.confidence if res.ocr_result else 'N/A'} | "
            f"Translated: {bool(res.translation_result)} | "
            f"Review: {res.needs_human_review}"
        )
        if res.translation_result:
            print(f"  Translation preview: {res.translation_result.translation[:100]}...")
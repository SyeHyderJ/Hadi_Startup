"""
Optical Character Recognition (OCR) processors for MEHDI_W_CLAP.

Supports multiple OCR backends:
- Tesseract OCR (via pytesseract) - good for documents, requires tesseract-ocr installed
- EasyOCR - good for general purpose, includes models
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class TesseractOCR:
    """Tesseract OCR wrapper."""

    def __init__(self, lang: str = "eng", config: str = ""):
        """
        Initialize Tesseract OCR.

        Args:
            lang: Language code(s) for OCR (e.g., 'eng', 'fra', 'eng+fra')
            text/config: Additional config parameters for tesseract
        """
        try:
            import pytesseract
            from PIL import Image

            self._pytesseract = pytesseract
            self._Image = Image
            self.lang = lang
            self.config = config
            logger.info(f"[OCR] Tesseract OCR initialized with lang='{lang}'")
        except ImportError as e:
            logger.error(
                "[OCR] Tesseract dependencies not installed. "
                "Install with: pip install pytesseract pillow"
            )
            raise RuntimeError(
                "Tesseract OCR dependencies missing. "
                "Install pytesseract and pillow, and ensure Tesseract OCR is installed on your system."
            ) from e

        # Verify tesseract is available
        try:
            self._pytesseract.get_tesseract_version()
        except Exception as e:
            logger.error(
                "[OCR] Tesseract OCR not found. Install Tesseract OCR from "
                "https://github.com/tesseract-ocr/tesseract"
            )
            raise RuntimeError(
                "Tesseract OCR executable not found. Please install Tesseract OCR."
            ) from e

    def extract_text(self, image: np.ndarray) -> str:
        """
        Extract text from an image using Tesseract OCR.

        Args:
            image: numpy array (H, W, C) in RGB format or grayscale

        Returns:
            Extracted text string
        """
        try:
            # Convert numpy array to PIL Image
            if len(image.shape) == 3 and image.shape[2] == 3:
                # RGB image
                pil_image = self._Image.fromarray(image, 'RGB')
            elif len(image.shape) == 2:
                # Grayscale image
                pil_image = self._Image.fromarray(image, 'L')
            else:
                raise ValueError(f"Unsupported image shape: {image.shape}")

            # Extract text
            text = self._pytesseract.image_to_string(
                pil_image,
                lang=self.lang,
                config=self.config
            )
            return text.strip()
        except Exception as e:
            logger.error(f"[OCR] Tesseract OCR failed: {e}")
            return ""


class EasyOCRReader:
    """EasyOCR reader wrapper."""

    def __init__(self, lang_list: list[str] | None = None, gpu: bool = False):
        """
        Initialize EasyOCR reader.

        Args:
            lang_list: List of language codes (e.g., ['en'], ['ch_sim', 'en'])
            gpu: Whether to use GPU if available
        """
        try:
            import easyocr

            self.lang_list = lang_list or ['en']
            self.reader = easyocr.Reader(self.lang_list, gpu=gpu)
            logger.info(f"[OCR] EasyOCR initialized with languages={self.lang_list}, gpu={gpu}")
        except ImportError as e:
            logger.error(
                "[OCR] EasyOCR not installed. Install with: pip install easyocr"
            )
            raise RuntimeError(
                "EasyOCR dependencies missing. Install easyocr."
            ) from e
        except Exception as e:
            logger.error(f"[OCR] Failed to initialize EasyOCR: {e}")
            raise

    def extract_text(self, image: np.ndarray) -> str:
        """
        Extract text from an image using EasyOCR.

        Args:
            image: numpy array (H, W, C) in RGB format or grayscale

        Returns:
            Extracted text string
        """
        try:
            # EasyOCR expects RGB format
            if len(image.shape) == 3 and image.shape[2] == 3:
                # Already RGB
                pass
            elif len(image.shape) == 2:
                # Grayscale to RGB
                image = np.stack([image] * 3, axis=-1)
            else:
                raise ValueError(f"Unsupported image shape: {image.shape}")

            # Extract text
            results = self.reader.readtext(image)
            # Extract just the text, ignoring bounding boxes and confidence
            text_lines = [result[1] for result in results]
            return '\n'.join(text_lines).strip()
        except Exception as e:
            logger.error(f"[OCR] EasyOCR failed: {e}")
            return ""


def create_ocr_processor(engine: str = "tesseract", **kwargs) -> "BaseOCR":
    """
    Factory function to create an OCR processor.

    Args:
        engine: OCR engine to use ("tesseract" or "easyocr")
        **kwargs: Additional arguments passed to the OCR constructor

    Returns:
        OCR processor instance
    """
    engine = engine.lower()
    if engine == "tesseract":
        return TesseractOCR(**kwargs)
    elif engine == "easyocr":
        return EasyOCRReader(**kwargs)
    else:
        raise ValueError(f"Unsupported OCR engine: {engine}. Use 'tesseract' or 'easyocr'.")


# For backwards compatibility, expose classes at module level
BaseOCR = TesseractOCR  # Default fallback
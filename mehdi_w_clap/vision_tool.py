"""
Vision processing tools for MEHDI system.

Provides screen capture, image processing, and OCR capabilities.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import cv2
import mss
import numpy as np
import pyautogui
from PIL import Image

from .ocr_processor import create_ocr_processor

logger = logging.getLogger(__name__)


def capture_screen(region: Optional[dict] = None) -> np.ndarray:
    """
    Capture screen or region of screen.

    Args:
        region: Dictionary with keys 'left', 'top', 'width', 'height' (optional)
                If None, captures full screen

    Returns:
        numpy array in RGB format
    """
    if region is None:
        # Capture full screen
        screenshot = pyautogui.screenshot()
    else:
        # Capture specific region
        screenshot = pyautogui.screenshot(region=(
            region.get('left', 0),
            region.get('top', 0),
            region.get('width', 800),
            region.get('height', 600)
        ))

    # Convert PIL image to numpy array (RGB)
    return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)


def preprocess_image_for_ocr(image: np.ndarray) -> np.ndarray:
    """
    Preprocess image to improve OCR accuracy.

    Args:
        image: Input image in BGR format

    Returns:
        Preprocessed image in grayscale
    """
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Apply adaptive thresholding
    processed = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )

    # Noise removal
    kernel = np.ones((1, 1), np.uint8)
    processed = cv2.morphologyEx(processed, cv2.MORPH_CLOSE, kernel)
    processed = cv2.medianBlur(processed, 3)

    return processed


def process_vision_request(params: dict) -> dict:
    """
    Process a vision request based on parameters.

    Args:
        params: Dictionary containing:
            - mode: "screen", "window", "region", or "file"
            - path: file path (for mode="file")
            - region: dict with left, top, width, height (for mode="region")
            - preprocess: boolean (whether to preprocess for OCR)
            - language: string (language code for OCR)
            - engine: string ("tesseract" or "easyocr")
            - return_image: boolean (whether to return processed image)

    Returns:
        Dictionary with results:
        - text: extracted text (if OCR performed)
        - image: processed image (if return_image=True)
        - error: error message (if any)
    """
    try:
        mode = params.get("mode", "screen")
        preprocess = params.get("preprocess", False)
        language = params.get("language", "eng")
        engine = params.get("engine", "tesseract")
        return_image = params.get("return_image", False)

        # Initialize OCR processor if needed
        ocr_processor = None
        if "text" in str(params).lower() or preprocess or "ocr" in str(params).lower():
            ocr_processor = create_ocr_processor(engine=engine, lang=language)

        # Capture or load image based on mode
        if mode == "screen":
            image = capture_screen()
        elif mode == "window":
            # Get active window
            try:
                import pygetwindow as gw
                window = gw.getActiveWindow()
                if window:
                    bbox = (window.left, window.top, window.width, window.height)
                    image = capture_screen({"left": bbox[0], "top": bbox[1],
                                          "width": bbox[2], "height": bbox[3]})
                else:
                    # Fallback to screen if no active window
                    image = capture_screen()
            except ImportError:
                logger.warning("pygetwindow not available, capturing full screen")
                image = capture_screen()
        elif mode == "region":
            region = params.get("region", {})
            image = capture_screen(region)
        elif mode == "file":
            path = params.get("path")
            if not path:
                return {"error": "File path required for mode='file'"}
            image = cv2.imread(path)
            if image is None:
                return {"error": f"Could not load image from {path}"}
        else:
            return {"error": f"Unsupported mode: {mode}"}

        # Process image
        if preprocess and ocr_processor:
            processed_img = preprocess_image_for_ocr(image)
            # Convert back to 3-channel for consistency if needed
            if len(processed_img.shape) == 2:
                processed_img = cv2.cvtColor(processed_img, cv2.COLOR_GRAY2BGR)

            text = ocr_processor.extract_text(processed_img)

            result = {"text": text}
            if return_image:
                result["image"] = processed_img
            return result
        elif ocr_processor:
            # OCR without preprocessing
            text = ocr_processor.extract_text(image)
            result = {"text": text}
            if return_image:
                result["image"] = image
            return result
        else:
            # Just return the image
            result = {}
            if return_image:
                result["image"] = image
            return result

    except Exception as e:
        logger.error(f"Vision processing failed: {e}")
        return {"error": str(e)}


# Tool definition for LLM integration
VISION_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "vision",
        "description": "Capture screen, process images, and perform OCR (Optical Character Recognition)",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["screen", "window", "region", "file"],
                    "description": "What to capture/process"
                },
                "path": {
                    "type": "string",
                    "description": "File path (required for mode='file')"
                },
                "region": {
                    "type": "object",
                    "properties": {
                        "left": {"type": "integer"},
                        "top": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"}
                    },
                    "description": "Region coordinates (for mode='region')"
                },
                "preprocess": {
                    "type": "boolean",
                    "description": "Apply image preprocessing for better OCR results"
                },
                "language": {
                    "type": "string",
                    "description": "Language code for OCR (e.g., 'eng', 'fra', 'de')"
                },
                "engine": {
                    "type": "string",
                    "enum": ["tesseract", "easyocr"],
                    "description": "OCR engine to use"
                },
                "return_image": {
                    "type": "boolean",
                    "description": "Whether to return the processed image"
                }
            },
            "required": ["mode"],
            "additionalProperties": False
        }
    }
}
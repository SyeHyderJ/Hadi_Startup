# OCR Improvement Recommendations for MEHDI System

## Current State Analysis

Based on my review of the MEHDI system:

1. **Existing Image Processing Capabilities**:
   - PIL/Pillow is installed (basic image manipulation)
   - OpenCV (cv2) is installed (computer vision operations)
   - MSS is installed (screen capture)

2. **Missing OCR Capabilities**:
   - No OCR-specific libraries are currently included in the installer
   - No Tesseract OCR or similar OCR engines are configured

3. **Vision Processing Reference**:
   - The prompt.txt mentions "Vision (screen_process)" indicating the system is designed to process screen/images
   - However, there's no evidence of actual OCR text extraction functionality

## Recommended Improvements

### 1. Add OCR Dependencies to Installer

Update `mehdi_w_clap/installer.py` to include OCR packages:

**In the `_CORE` section, add:**
```python
("pytesseract", "pytesseract"),
```

**Consider adding alternative OCR engines in the STT/TTS section or as a new category:**
```python
# OCR engine packages
_OCR: dict[str, list[tuple[str, str]]] = {
    "tesseract": [("pytesseract", "pytesseract")],
    "easyocr": [("easyocr", "easyocr")],
    "paddle": [("paddleocr", "paddleocr")]
}
```

And add to the needed packages:
```python
ocr = config.get("ocr_engine", "tesseract").lower()
needed += _OCR.get(ocr, [])
```

### 2. System Requirements Documentation

Add documentation that Tesseract OCR engine must be installed separately:

**Windows**: Download from https://github.com/UB-Mannheim/tesseract/wiki
**macOS**: `brew install tesseract`
**Linux**: `sudo apt-get install tesseract-ocr` (Ubuntu/Debian) or equivalent

### 3. Create OCR Utility Module

Create a new file `mehdi_w_clap/ocr.py` with functionality similar to the existing STT/TTS modules:

```python
"""
OCR engines for MEHDI system.

Tesseract - via pytesseract (requires Tesseract OCR installed)
EasyOCR   - deep learning based OCR
PaddleOCR - another deep learning based OCR option
"""

import cv2
import numpy as np
from PIL import Image
import pytesseract

class TesseractOCREngine:
    def __init__(self, lang='eng', config=''):
        self.lang = lang
        self.config = config
        
        # Try to find tesseract executable
        try:
            pytesseract.get_tesseract_version()
        except Exception:
            raise RuntimeError(
                "Tesseract OCR not found. Please install Tesseract OCR:\n"
                "Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
                "macOS: brew install tesseract\n"
                "Linux: sudo apt-get install tesseract-ocr"
            )

    def extract_text(self, image):
        """Extract text from image (numpy array or PIL Image)."""
        if isinstance(image, np.ndarray):
            # Convert OpenCV BGR to RGB
            if len(image.shape) == 3:
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(image)
        elif not isinstance(image, Image.Image):
            image = Image.open(image)
            
        return pytesseract.image_to_string(image, lang=self.lang, config=self.config)

class EasyOCREngine:
    def __init__(self, lang_list=['en'], gpu=False):
        try:
            import easyocr
            self.reader = easyocr.Reader(lang_list, gpu=gpu)
        except ImportError:
            raise ImportError("EasyOCR not installed. Run: pip install easyocr")

    def extract_text(self, image):
        """Extract text from image."""
        if isinstance(image, str):
            return ' '.join(self.reader.readtext(image, detail=0))
        elif isinstance(image, np.ndarray):
            return ' '.join(self.reader.readtext(image, detail=0))
        else:
            # Convert PIL to numpy
            img_array = np.array(image)
            return ' '.join(self.reader.readtext(img_array, detail=0))

def create_ocr_engine(config):
    """Factory function to create OCR engine based on config."""
    engine_type = config.get("ocr_engine", "tesseract").lower()
    
    if engine_type == "easyocr":
        lang_list = config.get("ocr_languages", ["en"])
        gpu = config.get("ocr_gpu", False)
        return EasyOCREngine(lang_list=lang_list, gpu=gpu)
    else:  # Default to tesseract
        lang = config.get("ocr_language", "eng")
        config_str = config.get("ocr_config", "")
        return TesseractOCREngine(lang=lang, config=config_str)
```

### 4. Update Prompt/Training

Update the `mehdi_w_clap/prompt.txt` to include guidance on OCR usage:

Add under EXECUTION RULES:
```
OCR Processing: When processing image-based documents for text extraction,
use the appropriate OCR engine based on the document type and quality.
```

### 5. Example Usage Integration

Show how this could integrate with the existing screen_process functionality:

```python
# Example of how OCR could be used with screen processing
def process_screen_for_text():
    # 1. Capture screen (using existing mss or similar)
    # 2. Preprocess image for better OCR (using OpenCV)
    # 3. Extract text using OCR engine
    # 4. Return extracted text
    
    pass  # Implementation would go here
```

## Recommended OCR Engine Comparison

### Tesseract (pytesseract)
- Pros: Free, open-source, good for clean documents, many language packs
- Cons: Requires proper image preprocessing, struggles with complex layouts
- Best for: Scanned documents, clean screenshots, standardized forms

### EasyOCR
- Pros: Deep learning based, handles various fonts and layouts better, good multi-language support
- Cons: Larger model size, slower than Tesseract
- Best for: Complex documents, varied fonts, real-world images

### PaddleOCR
- Pros: Very accurate, good table structure recognition, multilingual
- Cons: Largest model size, most resource intensive
- Best for: Complex documents with tables, forms, mixed layouts

## Implementation Priority

1. **Short Term**: Add pytesseract to installer and document Tesseract installation requirement
2. **Medium Term**: Create the OCR utility module with Tesseract as default
3. **Long Term**: Add alternative OCR engines (EasyOCR, PaddleOCR) as configurable options

## Expected Benefits

With these improvements, the MEHDI system will be able to:
- Extract text from screenshots and screen captures
- Process scanned documents and images containing text
- Extract information from PDFs (when converted to images)
- Automate data entry from paper forms or screenshots
- Enhance the vision capabilities mentioned in the prompt

This would significantly expand the system's utility for document processing tasks while maintaining compatibility with existing functionality.
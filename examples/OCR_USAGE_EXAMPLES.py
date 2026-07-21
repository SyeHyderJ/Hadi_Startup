"""
Example usage of OCR and vision capabilities in MEHDI system.
"""

# Example 1: Basic OCR with Tesseract
"""
from mehdi_w_clap.ocr_processor import TesseractOCR
import cv2

# Initialize OCR processor
ocr = TesseractOCR(lang='eng')

# Load image (from file, screen capture, etc.)
image = cv2.imread('document.png')

# Extract text
text = ocr.extract_text(image)
print(f"Extracted text: {text}")
"""

# Example 2: Screen capture with OCR using vision tool approach
"""
from mehdi_w_clap.vision_tool import process_vision_request
import cv2

# Capture screen and extract text with preprocessing
params = {
    "mode": "screen",
    "preprocess": True,
    "language": "eng",
    "engine": "tesseract"
}

result = process_vision_request(params)
if "error" in result:
    print(f"Error: {result['error']}")
else:
    print(f"Extracted text: {result['text']}")
    # Optionally save or display the processed image
    if "image" in result:
        cv2.imwrite("processed_screen.png", result["image"])
"""

# Example 3: Process a specific image file with EasyOCR
"""
from mehdi_w_clap.vision_tool import process_vision_request

params = {
    "mode": "file",
    "path": "receipt.jpg",
    "preprocess": True,
    "language": "en",
    "engine": "easyocr"
}

result = process_vision_request(params)
if "error" in result:
    print(f"Error: {result['error']}")
else:
    print(f"Extracted text:\n{result['text']}")
"""

# Example 4: Using as a tool in LLM conversation (conceptual)
"""
# This would be handled by the LLM client's tool calling mechanism
vision_tool_call = {
    "name": "vision",
    "parameters": {
        "mode": "screen",
        "preprocess": true,
        "language": "eng"
    }
}

# The LLM would call this tool and receive results like:
# {
#   "text": "Extracted text from screen goes here...",
#   "image": <processed image data>
# }
"""

print("OCR and Vision capabilities have been added to MEHDI system!")
print("\nTo use:")
print("1. Install dependencies: Run the installer (it now includes pytesseract)")
print("2. Install Tesseract OCR separately: https://github.com/tesseract-ocr/tesseract")
print("3. Use the vision tool or OCR processors directly in your code")
print("\nKey files created/updated:")
print("- mehdi_w_clap/ocr_processor.py: OPR engine wrappers")
print("- mehdi_w_clap/installer.py: Added OCR dependencies")
print("- mehdi_w_clap/prompt.txt: Updated vision tool documentation")
print("- mehdi_w_clap/vision_tool.py: Example vision processing implementation")
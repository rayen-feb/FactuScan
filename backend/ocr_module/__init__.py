import os
import cv2
import numpy as np
from PIL import Image
import pdf2image
from paddleocr import PaddleOCR

# Singleton PaddleOCR instance (CPU, Windows-safe)
_paddle_ocr = None

def _get_ocr():
    global _paddle_ocr
    if _paddle_ocr is None:
        _paddle_ocr = PaddleOCR(
            use_angle_cls=True,
            lang="fr",
            show_log=False,
            use_gpu=False
        )
    return _paddle_ocr


class OCRProcessor:
    """CPU-only PaddleOCR wrapper for image and PDF processing."""

    def __init__(self):
        self.ocr = _get_ocr()

    def process_image(self, image_path: str) -> str:
        """Process image file and extract text."""
        try:
            result = self.ocr.ocr(image_path, cls=True)
            if not result or not result[0]:
                return ""
            texts = []
            for line in result[0]:
                if line and len(line) >= 2:
                    texts.append(str(line[1][0]))
            return "\n".join(texts)
        except Exception as e:
            print(f"[OCRProcessor] Error extracting text from image: {e}")
            return ""

    def process_pdf(self, pdf_path: str) -> str:
        """Process PDF file and extract text via pdf2image -> PaddleOCR."""
        try:
            images = pdf2image.convert_from_path(pdf_path, dpi=200)
            all_text = []
            for image in images:
                # Save to a temp file because PaddleOCR works best with file paths
                tmp_path = pdf_path + f"_temp_{id(image)}.png"
                image.save(tmp_path, "PNG")
                try:
                    page_text = self.process_image(tmp_path)
                    if page_text:
                        all_text.append(page_text)
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
            return "\n".join(all_text)
        except Exception as e:
            print(f"[OCRProcessor] Error extracting text from PDF: {e}")
            return ""

    def preprocess_image(self, image_path: str) -> str:
        """Preprocess image for better OCR results."""
        try:
            img = cv2.imread(image_path)
            if img is None:
                return image_path
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            denoised = cv2.fastNlMeansDenoising(binary)
            preprocessed_path = image_path.replace('.', '_preprocessed.')
            cv2.imwrite(preprocessed_path, denoised)
            return preprocessed_path
        except Exception as e:
            print(f"[OCRProcessor] Error preprocessing image: {e}")
            return image_path


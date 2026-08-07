# PaddleOCR PP-StructureV3 Fix - TODO

- [x] Create plan and get user approval
- [x] Fix `PPStructure()` → `PPStructureV3()` in `backend/app.py`
- [x] Fix result parsing (`item['text']` → `item['res']['text']`)
- [x] Add PaddleOCR plain OCR fallback when PPStructureV3 yields no text
- [x] Add OCR.Space fallback in `/upload` route before returning 422
- [x] Add `paddleocr` to `requirements.txt`
- [x] Verify and test

# PaddleOCR PP-StructureV3 Fix - TODO

- [x] Create plan and get user approval
- [x] Fix `PPStructure()` → `PPStructureV3()` in `backend/app.py`
- [x] Fix result parsing (`item['text']` → `item['res']['text']`)
- [x] Add PaddleOCR plain OCR fallback when PPStructureV3 yields no text
- [x] Add OCR.Space fallback in `/upload` route before returning 422
- [x] Add `paddleocr` to `requirements.txt`
- [x] Verify and test

# Security / GitHub Push - TODO

- [x] Remove hard-coded Google OAuth Client ID & Secret from `backend/app.py`
  (now loaded only from env vars GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)
- [x] Create proper `.gitignore` (ignores `.env`, `backend/.env`, *.db, uploads, etc.)
- [x] Create `.env.example` with placeholders for all required variables
- [x] Update `Dockerfile` + `.dockerignore` for leaner, reliable deploys
- [x] Lazy-load PaddleOCR models to prevent OOM (status 137) on 512MB hosts
- [x] Fix Render deploy crash: `socketio.run(..., allow_unsafe_werkzeug=True)`
      (Flask-SocketIO >= 5.x raises RuntimeError without this flag)
- [x] Define missing `extract_with_gemini()` helper (was a latent NameError)
- [ ] ABORT the in-progress interactive rebase: `git rebase --abort`
- [ ] Scrub `.env` & `backend/.env` from history with `git filter-repo` (see FINAL PUSH guide)
- [ ] Force-push clean history to GitHub
- [ ] REVOKE / rotate the leaked Google OAuth credentials in Google Cloud Console


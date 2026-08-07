# Scanner Synchronization Plan

## Information Gathered
- **scanner.html**: Extends base.html. Has upload UI, results grid, progress bar, toast notifications.
- **base.html**: Navigation lacks a link to `/scanner` for authenticated users. No active state for `/scanner`.
- **style.css**: Variables (`--acc`, `--ok`, etc.) are all defined. Layout utilities exist.

## Issues Identified
1. **No drag & drop handlers**: CSS has `.uzone.drag` but JS has no `dragover`/`dragleave`/`drop` events.
2. **Progress bar never updates**: `pfill` width and `pstatus` text are never changed during `analyze()`.
3. **Button icon lost on reset**: The analyze button uses `textContent` reset, stripping the `<i>` icon.
4. **Missing nav link**: Authenticated users have no direct nav link to the Scanner in `base.html`.
5. **Missing active state**: `/scanner` is not handled in `base.html`'s nav `active` class logic.
6. **Error handling gap**: Network/JSON errors show a toast but could provide more detail.
7. **No ICE validation display**: `validations.ice_valid` is received but never rendered in the UI.

## Plan
### File: frontend/templates/scanner.html
- Add drag & drop event listeners (`dragover`, `dragleave`, `drop`) to `#dropZone`.
- Add `updateProgress(percent, statusText)` helper function.
- Simulate progress steps during `analyze()` (Init → Upload → Processing → Done).
- Fix button reset to preserve the search icon using `innerHTML`.
- Add display for ICE validation status in `displayResults()`.
- Ensure `loadFile` clears previous state properly.

### File: frontend/templates/base.html
- Add `<a href="/scanner">Scanner</a>` to `nav-links` for authenticated non-admin users.
- Add `{% if request.path == '/scanner' %}active{% endif %}` logic to the new link.

### File: frontend/static/css/style.css
- (No changes needed; all required variables and utilities are present.)

## Follow-up Steps
- Test file upload and verify progress bar animation.
- Test drag & drop functionality.
- Verify navigation link appears and highlights correctly.


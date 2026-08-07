# AdminLTE v4.0.0-rc7 Release Notes

## Highlights

This release delivers significant JavaScript refactors to the layout and push menu plugins, fixes several bugs affecting print, pagination, modals, and animations, upgrades to Astro 6.0.0, updates all dependencies, adds complete JavaScript documentation, and introduces a new sidebar-without-hover feature.

## Bug Fixes

- **Print layout**: Sidebar and main content are now both visible in browser print preview (#5982, PR #5996 by @herley-shaori)
- **Pagination border-radius**: Synced `_bootstrap-variables.scss` calc syntax with Bootstrap 5.3, fixing grouped pagination buttons showing rounded corners on all sides (#5951, reported by @Kneemund)
- **Escape key & modals**: `handleEscapeKey()` no longer bypasses Bootstrap 5's `keyboard: false` option on modals (#5993, reported by @braytac)
- **slideDown/slideUp animation**: Fixed unreliable `setTimeout` ordering when duration is 0, which caused sidebar treeview instant-open to fail (#5964, PR by @Kneemund)
- **CSS lint**: Fixed property order in print layout rules (#5997, reported by @lfiorini)

## Refactors

- **Layout transition handling** (#5956 by @dfsmania):
  - Fixed broken `holdTransition` timer (local variable promoted to instance property)
  - Removed duplicate `resize` event listeners registered on every call
  - Consolidated layout initialization to `layout.ts` (removed duplication from `adminlte.ts`)
  - Moved `app-loaded` class application to layout Data API section

- **Push menu plugin overhaul** (#5954 by @dfsmania):
  - Single `PushMenu` instance instead of creating new instances per event handler
  - Proper separation of `setupSidebarBreakPoint()` and `updateStateByResponsiveLogic()`
  - `sidebar-open` class only added on mobile viewports (aligns with v3 behavior)
  - Configuration now readable from data attributes on sidebar element
  - Removed unused `menusClose()` method and dead constants

## New Features

- **Sidebar without hover expand**: New `sidebar-without-hover` body class prevents the collapsed mini sidebar from expanding on hover (#5837 by @WojakGra). Add both `sidebar-mini sidebar-collapse sidebar-without-hover` to `<body>`.
- **Fixed footer with layout-fixed**: Footer now stays pinned at the bottom when using `.fixed-footer` with `.layout-fixed` (#5805)
- **Mobile scroll containment**: Sidebar no longer causes page scroll chaining on mobile (#5864)

## Documentation

- **Complete JavaScript documentation**: Added doc pages for all 7 JS components — Layout, PushMenu, Treeview, Card Widget, Direct Chat, Fullscreen, and Accessibility
- **Expanded PushMenu docs**: Now includes configuration options, responsive behavior, and CSS class reference
- **CHANGELOG**: Added comprehensive rc7 entry documenting all changes

## Improvements

- **Login/register box width**: Increased from 360px to 400px for better form readability (#5963 by @dfsmania)
- **TypeScript compilation**: Added `removeComments: true` to `tsconfig.json`, reducing unminified `adminlte.js` by ~15% (#5953 by @dfsmania)

## Dependencies

**Major upgrades:**
- `astro` 5.18.0 -> 6.0.0 (includes Vite 7, Shiki 4)
- `@astrojs/mdx` 4.3.13 -> 5.0.0

**Minor/patch updates:**
- `@astrojs/check` 0.9.7, `@typescript-eslint/*` 8.57.0
- `autoprefixer` 10.4.27, `eslint` 9.39.4, `eslint-plugin-astro` 1.6.0
- `fs-extra` 11.3.4, `nodemon` 3.1.14, `postcss` 8.5.8
- `prettier` 3.8.1, `rimraf` 6.1.3, `rollup` 4.59.0
- `sass` 1.97.3, `terser` 5.46.0

## Breaking Changes

- **Sidebar persistence is now opt-in**: `enablePersistence` defaults to `false` (was `true`). To restore the previous behavior where sidebar state is remembered across page loads, add `data-enable-persistence="true"` to your sidebar element:
  ```html
  <aside class="app-sidebar" data-enable-persistence="true"></aside>
  ```

## Contributors

Thank you to everyone who contributed to this release:
- @dfsmania (Diego Smania) — layout refactor, push menu refactor, login box width, tsconfig cleanup
- @herley-shaori (Herley) — print layout fix
- @Kneemund (Moritz Mechelk) — pagination bug report, slideDown/slideUp fix
- @braytac — escape key modal bug report
- @lfiorini — CSS lint issue report
- @WojakGra — sidebar-without-hover feature

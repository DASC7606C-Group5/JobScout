# Shared UI design

## Radius conventions

The daisyUI `cupcake` theme enabled in `web/src/styles.css` owns radius values. Components in the same category share a theme token regardless of their size or page.

| Category | Theme token | Components |
| --- | --- | --- |
| Boxes | `--radius-box` | Card, modal, alert and disclosure surfaces |
| Fields | `--radius-field` | Button, input, select, tab and textarea |
| Selectors | `--radius-selector` | Checkbox, toggle and badge |

Use daisyUI component radii directly, without fixed `rounded-lg`, `rounded-xl` or similar overrides. Custom navigation, upload controls, choice surfaces and panels use `rounded-field`, `rounded-selector` or `rounded-box` as appropriate. A card's full-surface interaction target follows the card's box radius. Avatars, progress dots and circular illustration details retain `rounded-full`.

Change category radii at the theme level instead of assigning independent values to components.

## Workspace sidebar

The desktop sidebar uses a 72 px compact rail and a 288 px expanded panel. Both states keep the same 44 px icon cells, navigation row heights, logo alignment and bottom toggle target. Labels are revealed beside the icons; the toggle itself never becomes a full-width button. The panel width transition respects reduced motion, clips expanding content, and excludes the workspace from scroll anchoring so resizing cannot shift the document's scroll position.

Search history remains in the same position in both states. From the compact rail it opens the panel and focuses the current search (or the history heading). In the expanded panel it toggles only the history list. The list owns its scroll area and displays title, location, status and update date separately. Closing and reopening the list preserves loaded pages.

Mobile keeps the modal drawer behavior: the page is inert while open, Tab stays inside the drawer, Escape closes it, and focus returns to the opening control. Navigation closes the drawer after pending drafts are saved. Desktop expansion is remembered independently of the mobile drawer state.

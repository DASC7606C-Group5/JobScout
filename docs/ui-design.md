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

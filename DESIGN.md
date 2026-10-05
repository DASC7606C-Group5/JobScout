---
version: alpha
name: JobScout
description: A calm workspace for applicants to compare roles and prepare applications.
typography:
  sans:
    fontFamily: "Inter, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
omitted:
  - section: colors
    reason: "Owned by the daisyUI cupcake theme."
  - section: spacing
    reason: "Owned by shared Tailwind layouts."
  - section: rounded
    reason: "Owned by daisyUI components."
---

# JobScout design

## Overview

Help applicants compare roles and prepare applications. Put job facts, relevant evidence and clear next actions first. Use English for interface copy; preserve the language of supplied content.

## Colors

The `cupcake` theme in [styles.css](web/src/styles.css) owns the palette. Use warm surfaces, quiet borders and mint primary actions through semantic theme classes. Reserve warning and error colors for their meaning.

## Typography

Use the multilingual font stack above. Establish hierarchy with size, weight and spacing. Keep labels compact, body text readable and long titles and quotations able to wrap.

## Layout

Keep navigation in the sidebar and actions beside the content they affect. Use list/detail layouts on wide screens and one focused view on narrow screens. Preserve document scrolling; constrain long navigation lists independently.

## Elevation & Depth

Separate sections with borders and theme surfaces. Use restrained shadows; sticky controls need opaque backgrounds.

## Shapes

Use daisyUI radii and control shapes consistently. Keep icons aligned and touch targets comfortably spaced.

Use component defaults for Boxes, Fields and Selectors. Custom surfaces reference the same theme variables; see [radius conventions](docs/ui-design.md).

## Components

Reuse shared job views, `Icon` and native daisyUI controls. Give controls accessible names, visible focus and consistent states. Preserve input during errors, confirm destructive actions and respect reduced motion. Global interaction styles belong in the application stylesheet.

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
| --- | --- | --- | --- | --- |
| Select/Listbox | Native daisyUI select | Form schemas | OS popup | Keyboard flows |
| Form | Shared forms and DraftStatus | API schemas | Create/edit | Input and recovery tests |
| Scrollbar | styles.css | Theme tokens | Global baseline | UI audit |
| Toast | ScoutProvider and WorkspaceLayout | Mutation results | Status/inline error | Feedback tests |
| CRUD | Shared route and service hooks | API lifecycle | Create/edit/delete | Workflow tests |

## Do's and Don'ts

- Preserve supplied facts and exact quotations.
- Show uncertainty once, beside the affected content.
- Avoid invented scores, internal diagnostics, repeated disclaimers and empty sections.

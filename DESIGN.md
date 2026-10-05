---
version: alpha
name: JobScout
description: A calm workspace for applicants to compare roles and prepare applications.
typography:
  sans:
    fontFamily: "Inter, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
omitted:
  - section: colors
    reason: "The installed daisyUI cupcake theme is canonical; this file does not generate tokens."
  - section: spacing
    reason: "Existing Tailwind utilities in shared workspace components remain canonical."
  - section: rounded
    reason: "Existing daisyUI components and shared component utilities remain canonical."
---

# JobScout design

## Overview

Help applicants compare a short list of jobs, understand the relevant experience they already have, and choose a useful next step. Keep the existing workspace identity: warm cupcake surfaces, quiet borders, mint primary actions, and readable mixed-script content. The interface and system messages are English; supplied content retains its original language.

## Colors

[The application stylesheet](web/src/styles.css) selects daisyUI's `cupcake` theme. Use semantic theme classes for surfaces, text, focus, selection and feedback. The installed theme is the source of truth; do not introduce a second palette.

## Typography

Use the existing font stack above. Preserve current text sizes, weights and line heights. Job titles may wrap; original quotations remain readable in their original language.

## Layout

Preserve the workspace shell, padding and spacing. Shared results show a list beside details from `1100px`; narrower screens show the list or a selected role. The shared implementation is in [Results](web/src/components/results.tsx).

## Elevation & Depth

Use existing bordered cards and theme surfaces. Sticky application controls have an opaque base surface and remain in normal document flow before sticking.

## Shapes

Reuse existing daisyUI controls, card radii and component utilities. Do not copy the exploratory prototype's independent spacing or shape values.

## Components

Reuse `Results`, `JobCard`, `JobDetail`, `ResultWarnings` and `MatchingEvidence` across discovery and saved jobs. Keep familiar daisyUI buttons, native select controls, disclosures and a native modal dialog. Use the existing `Icon` component. Global focus and reduced-motion rules live in the application stylesheet.

## Do's and Don'ts

- Put job facts, a supported reason and the application action first.
- Show uncertainty once, close to the role or search it affects.
- Preserve user input, listing content and exact quotations.
- Do not display internal diagnostics, invented match percentages, repeated disclaimers or empty detail sections.

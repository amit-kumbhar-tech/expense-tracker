---
name: spendly-ui-designer
description: >
  Generates modern, production-ready UI components and pages for Spendly — a personal
  expense tracker built with Flask + Jinja2 + plain CSS. Use this skill whenever the user
  asks to design, create, build, redesign, or improve any UI for Spendly. Trigger
  automatically on phrases like "design the page", "create UI for", "build component for",
  "redesign", "improve the UI", or anything referencing Spendly pages/components.
  Also trigger when the user shares a screenshot of an existing Spendly page and asks for
  improvements. Never skip this skill for Spendly-related UI work, even if the request
  seems simple.
---

# Spendly UI Designer

Generates clean, modern, fintech-style UI for the Spendly expense tracker.
Spendly is a Flask app using Jinja2 HTML templates + plain CSS (no React/Vue).

---

## Step 0 — Gather Context

Before generating any code, confirm:

1. **What** — the exact page or component name (e.g. "Dashboard", "Add Expense modal", "Sidebar nav")
2. **Constraints** — any data, routes, or form fields that must be present
3. **Existing design** — if the user has screenshots or mentions existing pages, ask for them.
   If none are provided, apply the Spendly Design System below and note any assumptions.

If the request is clear enough to proceed, start immediately and state your assumptions inline.

---

## Spendly Design System

Apply these rules consistently across all generated UI. They define Spendly's visual identity.

### Color Palette

```css
:root {
  /* Brand */
  --color-primary:     #4F46E5;   /* Indigo 600 — CTAs, links, active states */
  --color-primary-light: #EEF2FF; /* Indigo 50  — hover backgrounds, badges */

  /* Semantic */
  --color-success:     #10B981;   /* Green — income, positive amounts */
  --color-danger:      #EF4444;   /* Red   — expenses, delete actions */
  --color-warning:     #F59E0B;   /* Amber — warnings, pending states */

  /* Neutrals */
  --color-bg:          #F9FAFB;   /* Page background */
  --color-surface:     #FFFFFF;   /* Card / panel background */
  --color-border:      #E5E7EB;   /* Subtle dividers */
  --color-text:        #111827;   /* Primary text */
  --color-muted:       #6B7280;   /* Labels, captions */

  /* Shadows */
  --shadow-card: 0 1px 3px rgba(0,0,0,0.07), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-elevated: 0 4px 12px rgba(0,0,0,0.08);
}
```

### Typography

```css
/* Import in <head> */
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">

body      { font-family: 'DM Sans', sans-serif; font-size: 15px; color: var(--color-text); }
h1        { font-size: 1.75rem; font-weight: 600; }
h2        { font-size: 1.25rem; font-weight: 600; }
.mono     { font-family: 'DM Mono', monospace; }   /* for amounts/numbers */
.caption  { font-size: 0.8125rem; color: var(--color-muted); }
```

### Spacing Grid

Use multiples of 8px for all margins, paddings, and gaps.

| Token | Value | Usage |
|-------|-------|-------|
| `--space-1` | 4px | Micro gaps |
| `--space-2` | 8px | Tight padding |
| `--space-3` | 12px | Small gaps |
| `--space-4` | 16px | Standard padding |
| `--space-6` | 24px | Section gaps |
| `--space-8` | 32px | Large sections |

### Core Components

**Cards**
```css
.card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--shadow-card);
}
```

**Buttons**
```css
.btn-primary {
  background: var(--color-primary);
  color: white;
  border: none;
  border-radius: 8px;
  padding: 10px 20px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-primary:hover { background: #4338CA; }

.btn-ghost {
  background: transparent;
  color: var(--color-primary);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 10px 20px;
}
```

**Form Inputs**
```css
.input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  font-size: 15px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.input:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(79,70,229,0.1);
  outline: none;
}
```

**Amount Display** (always use `.mono`)
```html
<span class="amount expense mono">-₹1,200</span>
<span class="amount income mono">+₹5,000</span>
```
```css
.amount.expense { color: var(--color-danger); }
.amount.income  { color: var(--color-success); }
```

**Category Badge**
```css
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 0.8125rem;
  font-weight: 500;
  background: var(--color-primary-light);
  color: var(--color-primary);
}
```

### Layout Shell

Spendly uses a two-column layout: fixed sidebar + scrollable main content.

```html
<div class="app-shell">
  <aside class="sidebar">...</aside>
  <main class="main-content">...</main>
</div>
```
```css
.app-shell {
  display: flex;
  min-height: 100vh;
  background: var(--color-bg);
}
.sidebar {
  width: 240px;
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
  padding: 24px 16px;
  position: fixed;
  height: 100vh;
}
.main-content {
  margin-left: 240px;
  flex: 1;
  padding: 32px;
}
```

### Icons

Use **Lucide Icons** (CDN, no build step needed):
```html
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
<!-- Usage: -->
<i data-lucide="wallet" class="icon"></i>
<script>lucide.createIcons();</script>
```

Preferred icons per concept:
| Concept | Icon name |
|---------|-----------|
| Dashboard | `layout-dashboard` |
| Expenses | `receipt` |
| Add | `plus-circle` |
| Income | `trending-up` |
| Budget | `piggy-bank` |
| Profile | `user-circle` |
| Logout | `log-out` |
| Filter | `sliders-horizontal` |
| Edit | `pencil` |
| Delete | `trash-2` |
| Category | `tag` |
| Search | `search` |
| Calendar | `calendar` |

---

## Output Format

Every response must include these three sections:

### 1. UI Structure
- 3–5 bullet summary of the layout and key sections
- Any important UX decisions or assumptions

### 2. Code
Provide complete, copy-paste-ready code:
- One HTML file (Jinja2 template) with embedded `<style>` block
- Use the design tokens above
- No unnecessary dependencies beyond Lucide + Google Fonts
- Modular: each card/section is a clearly delimited HTML block with a comment header

### 3. Design Notes
- 2–3 sentences on what makes this component feel polished/fintech
- Any hover states, transitions, or micro-interactions included

---

## Page-Specific Guidance

Read `references/pages.md` for per-page layout patterns:
- Dashboard summary cards, chart area, recent transactions list
- Add/Edit Expense form layout
- Login / Register auth pages
- Expense list with filters
- Profile page

---

## Design Rules (Non-Negotiable)

- **Consistency** — always use design tokens; never hardcode colors or font sizes
- **Spacing** — 8px grid; generous whitespace inside cards
- **No clutter** — each element earns its place; remove decorative noise
- **Currency** — display Indian Rupee (₹) unless told otherwise; use `.mono` class
- **Responsiveness** — sidebar collapses to top nav below 768px
- **Accessibility** — form inputs must have `<label>` elements; buttons have descriptive text

## What to Avoid

- Generic Bootstrap-style layouts with no visual personality
- Unstructured code dumps without comments
- Hardcoded hex values outside of the design token block
- Mixing multiple icon libraries
- Placeholder text like "Lorem ipsum" — use realistic expense data (Food, Transport, etc.)

---

## Consistency Rule

If the user shares screenshots of existing Spendly pages:
1. Extract the dominant color, font, and card style from the screenshot
2. Note any deviations from the design system above
3. Match the observed style, then layer in improvements

If no screenshots are provided, apply the design system above faithfully and note assumptions.
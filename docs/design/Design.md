# Design — Sentinel Review: Design System & UX Principles

| Field | Value |
| --- | --- |
| Version | v0.1 |
| Last Updated | 2026-08-06 |
| Owner | Design Lead |
| Status | In Review |

---

## 1. Design Principles

1. **Signal over noise** — findings are ranked by severity, never buried.
2. **Context-first** — every finding is line-anchored.
3. **Honest metrics** — usefulness shown with real 👍/👎 data.
4. **Dark-optimized** — dashboards designed for dark theme.
5. **Calm density** — tables and charts, minimal prose.

## 2. Brand & Visual Identity

- Voice: precise, security-minded, professional.
- Tagline: "The senior engineer who never gets tired."

## 3. Color System

| Token | Hex | Usage | Contrast (AA) |
| --- | --- | --- | --- |
| bg | `#0F172A` | dark bg | — |
| surface | `#1E293B` | cards | — |
| text | `#F1F5F9` | primary | 12:1 |
| severity-blocking | `#EF4444` | blocking | 5.5:1 |
| severity-warning | `#F59E0B` | warning | 4.8:1 |
| severity-nit | `#3B82F6` | nit | 5.8:1 |
| success | `#22C55E` | useful/ok | 5:1 |

## 4. Typography Scale

| Token | Font | Size | Weight | Line-height | Usage |
| --- | --- | --- | --- | --- | --- |
| display | sans | 28px | 700 | 1.2 | KPI numbers |
| heading | sans | 20px | 600 | 1.3 | page titles |
| body | sans | 14px | 400 | 1.5 | content |
| code | mono | 13px | 400 | 1.4 | code in comments |
| label | sans | 12px | 600 | 1.4 | severity badges |

## 5. Spacing & Grid

- Base 4px; Tailwind-compiled CSS.
- Breakpoints: 640/768/1024/1280.

## 6. Component Library

**Comment card:**

```
┌──────────────────────────────────┐
│ [blocking] [security] line 42   │
│ pickle.load() on untrusted input │
│ Suggested fix: use safe deserial │
│   👍 12   👎 1                   │
└──────────────────────────────────┘
```

**KPI card:** reviews, usefulness rate, avg latency, queue depth.

Other: repo list (HTMX), config panel (HTMX), Chart.js charts (bar, donut, line), severity filter chips, HTMX loading states.

## 7. Iconography

Inline SVG + emoji; no image assets.

## 8. Accessibility

- WCAG 2.1 AA; severity never color-only (text labels).
- HTMX with loading states + CDN fallback handlers.

## 9. Responsive

| Breakpoint | Rule |
| --- | --- |
| < 640 | Single column |
| ≥ 1024 | Sidebar + content |

## 10. Motion

- Chart transitions (300ms); reduced-motion honored.

## 11. Dark Mode

Dark-first theme.

## 12. Related Documents

| Document | Relationship |
| --- | --- |
| [AppFlow.md](AppFlow.md) | Screens |
| [PRD.md](../product/PRD.md) | UX goals |
| [TechSpec.md](../technical/TechSpec.md) | Stack |
| [Schema.md](../technical/Schema.md) | Display data |
| [ImplementationPlan.md](../project/ImplementationPlan.md) | Tasks |
| [Tracker.md](../project/Tracker.md) | Status |
| [Rules.md](../project/Rules.md) | Standards |
| [API.md](../technical/API.md) | Contracts |
| [SecurityAndCompliance.md](../technical/SecurityAndCompliance.md) | Security |
| [Testing.md](../technical/Testing.md) | UI tests |
| [Deployment.md](../technical/Deployment.md) | Deploy |
| [Glossary.md](../reference/Glossary.md) | Vocabulary |
| [RiskRegister.md](../project/RiskRegister.md) | Risks |

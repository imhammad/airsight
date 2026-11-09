# ADR 0009: Web app design

- **Status:** Accepted
- **Date:** 2026-11-09
- **Issue:** #88

## Context

The web app is where most people meet AirSight. Our user is a parent, someone with asthma, or a
runner, and they have one question: **is the air OK near me right now, and what should I do?**
They may be on a phone, outdoors, in a hurry. They are not data analysts.

Two things make this harder than a usual dashboard. First, our numbers have known limits (the
model card), and the app must be honest about them without causing alarm. Second, colour carries
meaning (the AQI categories), so the rest of the interface must stay quiet, and colour can never
be the only signal, because about 1 in 12 men has a colour vision deficiency.

## Options

1. **A data-dense dashboard** (dark theme, many charts, bright accents): impressive at a glance,
   but slow to read for our user, and colour competes with the AQI colours.
2. **A component library's default look** (such as Material): quick to build, but generic, and
   heavy to restyle.
3. **A small design system of our own**, calm and editorial: a few tokens, our own components on
   plain CSS, one decision per screen.

## Decision

Option 3. The approved preview is the reference for every screen.

### Principles

- **One answer per screen.** The map answers "where?", the detail page answers "how is it here
  and what should I do?", and the accuracy page answers "can I trust this?".
- **Words with every colour.** Each AQI colour comes with its category name and plain advice.
- **Honest by default.** Every reading shows how old it is, which value it is (corrected or
  raw) and which model made it. Where the correction is worse than raw (#94), the app shows
  raw and says so.
- **Calm.** Neutral ground, one accent, generous space. No glow, gradients, drop-shadow stacks,
  or decorative charts.

### Colour tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `ground` | `#F6F5F2` | `#111315` | page background |
| `surface` | `#FFFFFF` | `#1A1D20` | cards and sheets |
| `line` | `#E3E1DC` | `#2A2E32` | borders and dividers |
| `ink` | `#1A1C1E` | `#ECEDEE` | text (15.7:1 and 15.9:1) |
| `secondary` | `#545A61` | `#A3A9AF` | supporting text (6.4:1 and 7.9:1) |
| `accent` | `#1E5A85` | `#86B6DA` | links, buttons, the corrected series (6.7:1 and 8.6:1) |

Light is the default. Dark follows the device setting, from the same token names.

### Air quality colours

The US EPA categories, softened but recognizable. Label text passes 4.5:1 on each colour.

| Category | PM2.5 (µg/m³) | Colour | Label text |
|---|---|---|---|
| Good | up to 9.0 | `#4E9F5E` | ink |
| Moderate | 9.1 to 35.4 | `#E3BD3E` | ink |
| Unhealthy for sensitive groups | 35.5 to 55.4 | `#E88B3A` | ink |
| Unhealthy | 55.5 to 125.4 | `#C43F3A` | white |
| Very unhealthy | 125.5 to 225.4 | `#7E4E9A` | white |
| Hazardous | above 225.4 | `#6E2433` | white |

Map markers have a 2 px ring in the ground colour. A sensor showing raw readings is a white
marker with a grey ring, labelled "Raw reading" in the legend. Stale and excluded sensors are
drawn hollow and named as such in their details.

### Typography

- **Source Serif 4** (400) for page headings and the main reading. Serif figures give the one
  number that matters a calm, printed feel.
- **Inter** (400, 500, 600) for everything else, with tabular figures wherever numbers sit in
  columns.
- Body text 16 px, labels 13 px, nothing below 12 px. Fonts are self-hosted with Fontsource:
  no requests to third parties and no layout jump while fonts load.

### Motion

Motion only explains a change: something appeared, moved or updated.

- 150 to 250 ms, easing `cubic-bezier(0.2, 0, 0, 1)` (fast start, soft landing).
- The bottom sheet slides up; pages and new readings fade in; category colours cross-fade when
  they change; the 24-hour bars grow once when first shown; the map flies to a searched place
  or your location (about 800 ms).
- Never: loops, pulsing markers, numbers counting up, parallax, or motion on scroll.
- With `prefers-reduced-motion: reduce`, transitions become instant and the map jumps instead
  of flying.

### Layout and accessibility

- Phone first (390 px), then a two-column layout from 960 px with the map beside the details.
- Touch targets at least 44 px; real buttons, links and labelled inputs; visible focus rings
  in the accent colour; every chart has a text alternative.
- Goal: Lighthouse accessibility 90 or higher, checked in CI (#93).

### Libraries

| Need | Choice | Why |
|---|---|---|
| Pages | React Router | the standard for React; links work like links |
| Data | TanStack Query | caching, retries and loading states without hand-written effects |
| API types | `openapi-typescript` from `docs/openapi.json` | an API change breaks the build, not the users |
| Map | MapLibre GL with OpenFreeMap tiles | open source, no API key, a muted style we can match |
| Charts | small hand-written SVG components | one simple chart type; a chart library would add a lot of code for little |
| Styling | CSS modules with the tokens as CSS variables | no runtime cost, and dark mode is a token swap |

## Consequences

- Our own components take longer to build than a library's, but they stay small, and the look
  stays ours.
- A light theme first is unusual for data products. It suits reading outdoors and the calm,
  printed tone; dark mode costs little because components use tokens, never raw colours.
- Self-hosting fonts adds about 100 KB to the first visit, then it's cached.
- Free OpenFreeMap tiles have no uptime guarantee. If they become a problem, MapLibre can point
  at another tile source without code changes elsewhere.
- The design preview is a reference, not a pixel-perfect spec. When building reveals a better
  answer, we update this ADR in the same PR.

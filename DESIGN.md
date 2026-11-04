---
name: Battery Passport
description: Passeport numérique de batterie, rendu comme un boîtier de batterie usiné en aluminium anodisé.
colors:
  r0: "#050c14"
  r1: "#07111c"
  r2: "#0b1a29"
  r3: "#102336"
  r4: "#172f46"
  r5: "#213d58"
  r6: "#2f506e"
  r7: "#4a6a88"
  r8: "#7790a8"
  r9: "#afc0cf"
  r10: "#e6edf3"
  capgemini-anodized: "#0070ad"
  capgemini-anodized-rim: "#1a86c2"
  live-blue: "#12abdb"
  live-blue-hover: "#3cbde6"
  live-ink: "#04131d"
  titanium: "#c9d2da"
  titanium-hi: "#dde4ea"
  titanium-lo: "#aab6c1"
  titanium-ink: "#13202c"
  titanium-mute: "#33455a"
  warning-amber: "#f2b33d"
  critical-hot: "#ff6a3d"
  recycle-slate: "#2a3a4c"
typography:
  display:
    fontFamily: "Michroma, Archivo, sans-serif"
    fontSize: "clamp(2rem, 1.1rem + 3.6vw, 3.7rem)"
    fontWeight: 400
    lineHeight: 1.02
    letterSpacing: "0.02em"
  plate-id:
    fontFamily: "Michroma, Archivo, sans-serif"
    fontSize: "clamp(1.45rem, 1rem + 2.4vw, 2.8rem)"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.04em"
  readout:
    fontFamily: "Michroma, Archivo, sans-serif"
    fontSize: "clamp(1.4rem, 1rem + 2vw, 2.2rem)"
    fontWeight: 400
    lineHeight: 1.1
    letterSpacing: "0.06em"
  casing-label:
    fontFamily: "Michroma, Archivo, sans-serif"
    fontSize: "0.78rem"
    fontWeight: 400
    letterSpacing: "0.1em"
  band-headline:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(1.5rem, 1rem + 1.9vw, 2.5rem)"
    fontWeight: 650
    lineHeight: 1.08
    letterSpacing: "-0.01em"
    fontVariation: "'wdth' 125"
  title:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.2rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "0.005em"
    fontVariation: "'wdth' 118"
  gauge-value:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: 1.15
    fontVariation: "'wdth' 112"
  body:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "'tnum'"
  label:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.76rem"
    fontWeight: 600
    letterSpacing: "0.04em"
    fontVariation: "'wdth' 112"
rounded:
  chip: "2px"
  control: "3px"
  panel: "4px"
  chamfer-plate: "10px"
  chamfer-casing: "14px"
spacing:
  gutter: "16px"
  row: "14px"
  stack: "20px"
  panel: "20px"
  band: "72px"
components:
  button-primary:
    backgroundColor: "{colors.live-blue}"
    textColor: "{colors.live-ink}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
    height: "46px"
  button-primary-hover:
    backgroundColor: "{colors.live-blue-hover}"
    textColor: "{colors.live-ink}"
  button-default:
    backgroundColor: "{colors.r3}"
    textColor: "{colors.r10}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
    height: "46px"
  button-default-hover:
    backgroundColor: "{colors.r4}"
  button-on-plate:
    backgroundColor: "{colors.titanium-ink}"
    textColor: "{colors.titanium-hi}"
    rounded: "{rounded.control}"
  input:
    backgroundColor: "{colors.r1}"
    textColor: "{colors.r10}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
    height: "46px"
  badge-settled:
    backgroundColor: "{colors.titanium}"
    textColor: "{colors.titanium-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
    padding: "3px 9px"
  panel:
    backgroundColor: "{colors.r2}"
    textColor: "{colors.r10}"
    rounded: "{rounded.panel}"
    padding: "20px"
  verdict:
    backgroundColor: "{colors.capgemini-anodized}"
    textColor: "#eef7fc"
    typography: "{typography.readout}"
    rounded: "{rounded.panel}"
    padding: "22px"
  plate:
    backgroundColor: "{colors.titanium}"
    textColor: "{colors.titanium-ink}"
    padding: "22px 24px"
---

# Design System: Battery Passport

## Overview

**Creative North Star: "The Machined Module Housing"**

The site is the battery pack itself: one machined, bead-blasted anodized casing in blue-black, carrying a laser-etched titanium identity plate, five smoked-glass cell bays and a single indicator light. Every surface is a part of that housing. The passport is not a dashboard placed on a page; it is the plate riveted to the casing, and the live module data sits behind glass beside it.

Density is instrument-like. Values are tabular, every reading carries its unit and provenance, and the hierarchy is carried by material (casing, plate, glass, anodized blue panel) rather than by colour noise. Colour is reserved: one vibrant blue for what is live or can be acted on, one health progression from neutral to amber to hot orange, and Capgemini blue as an anodized surface, never as decoration.

The system refuses the SaaS hero over a row of role cards, refuses green as a success colour, and refuses nested cards. It serves a projector across the room, a tablet in a workshop and a phone on a loading dock with the same parts.

**Key Characteristics:**
- One eleven-step anodized ramp (r0 to r10) carries every neutral.
- Vibrant blue (#12ABDB) appears only on live or actionable things.
- Titanium plates with chamfered corners and flat rimmed fasteners carry identity.
- Michroma is etched lettering; Archivo (width axis) is everything that is read.
- Chamfers, 1px machined rims and 2 to 4px radii; no soft pills except switches and LEDs.
- French copy, no emoji, no em or en dashes, real drawn Lucide icons only.

## Colors

A cold, bead-blasted blue-black housing lit by one reserved blue and one heat progression.

### Primary
- **Capgemini Anodized Blue** (capgemini-anodized): the anodized surface. Fills the full "fin de vie" band on the landing, the Défi 3 verdict panel and dialog headers, rimmed with capgemini-anodized-rim. Text on it is near-white (#eef7fc to #f4fafd).

### Secondary
- **Live Signal Blue** (live-blue): reserved for live or actionable states only. Primary buttons, focus rings, caret, selection, the online device LED and its beat, the selected tab underline, the switch when on, the best-ranked option, the reception "OK" check, JSON keys in the payload. Ink on it is live-ink.

### Tertiary
- **Warning Amber** (warning-amber): the middle step of health. WARNING cells, the dashed manufacturer max line, PENDING and ORDERED badges, warning notes.
- **Critical Hot** (critical-hot): the indicator light. CRITICAL cells, Waste and REJECTED badges, danger buttons, the refused check, alert timeline nodes.

### Neutral
- **Abyss** (r0): rail, footer, deep bands, payload well.
- **Casing** (r1): page ground, inputs, table headers.
- **Casing Face** (r2): panels, dialogs, gauge tiles.
- **Raised Face** (r3): default button, notes outside panels, casing gradient top.
- **Rim** (r4) and **Rim High** (r5): 1px dividers and machined borders; meter tracks.
- **Mid Steel** (r6 to r8): ticks, placeholders (r7), secondary text (r8), icons in headings.
- **Soft Steel** (r9): soft text and the neutral (nominal) health tone.
- **Frost** (r10): primary ink.
- **Titanium** (titanium, with titanium-hi and titanium-lo): plates and settled-state badge fills. titanium-ink and titanium-mute are the engraved type on it.
- **Recycle Slate** (recycle-slate): verdict panel when the recommendation is Recycle.

### Named Rules
**The Reserved Signal Rule.** Vibrant blue #12ABDB means "live now" or "you can act here". It is never a heading colour, a decorative accent or a fill for settled states.

**The No Green Rule.** There is no green in the system. A settled state (RECEIVED, APPROVED, Reused, Remanufactured, Repurposed) is a titanium-filled badge with titanium ink. Success is shown by material, not by hue.

**The One Heat Rule.** Health has exactly one progression: neutral steel (r9) to amber (#F2B33D) to hot (#FF6A3D). Every gauge, cell, LED, legend and timeline node uses it.

**The Anodized Panel Rule.** Capgemini blue #0070AD is a surface, applied as a whole band or a whole panel (fin de vie band, verdict, dialog header). It is not used for text, borders or small accents.

## Typography

**Display Font:** Michroma (with Archivo, sans-serif)
**Body Font:** Archivo variable, width axis 62% to 125% (with Helvetica Neue, Arial, sans-serif)
**Label/Mono Font:** ui-monospace stack for code and payload only

**Character:** Michroma is the laser etching on the part; wide and mechanical, it is used only where something is stamped on the hardware. Archivo carries everything people read, and its width axis does the hierarchy work: wider for headings and readouts, normal for running text.

### Hierarchy
- **Display** (Michroma 400, clamp(2rem, 1.1rem + 3.6vw, 3.7rem), 1.02): the etched title on the landing plate. Page h1 uses Michroma at clamp(1.6rem, 1.1rem + 2.2vw, 2.6rem).
- **Plate ID** (Michroma 400, up to 2.8rem, 1): battery IDs on passport plates; smaller Michroma etched IDs in lists and outcome rows.
- **Readout** (Michroma 400, up to 2.6rem for the verdict name, up to 2.2rem for the status check): Défi 3 verdict name and the WASTE / ORIGINAL status check.
- **Casing Label** (Michroma 400, 0.78 to 0.86rem, 0.1 to 0.14em, uppercase): cell labels M1 to M5, the lid heading, the rail wordmark.
- **Band Headline** (Archivo 650, width 125%, clamp(1.5rem, 1rem + 1.9vw, 2.5rem), 1.08, -0.01em): landing band headings.
- **Title** (Archivo 600, width 118%, 1.2rem): panel h2; h3 at width 112%, 1rem; station h3 at 1.15rem, width 118%.
- **Gauge / Cell value** (Archivo 600, width 112 to 115%, 1.75rem gauges, up to 1.8rem cells): live numbers, always tabular.
- **Body** (Archivo 400, 16px, 1.5, tabular numerals, max 68ch): running text; lede 1.08rem at 44ch.
- **Label** (Archivo 600, width 112%, 0.76rem, 0.04em, uppercase): badges and table headers (0.78rem, 0.05em).

### Named Rules
**The Etched Only Rule.** Michroma appears only where text is stamped on the part: plate lettering, battery IDs, casing labels and status readouts. Band headings, panel headings and body are Archivo.

**The Width Axis Rule.** Hierarchy is made with Archivo's width axis (100% body, 108 to 112% controls and labels, 118% titles, 125% band headings) before size or colour.

## Layout

Content sits in a 1240px wrap (760px narrow) with a 16px gutter. Inside, a 20px stack rhythm, 10 to 14px row gaps and 20px panel padding. The landing hero is a 5 / 7 column split from 1020px (plate left, cell bay right); bands repeat the 5 / 7 split for head and lede from 960px, with 72px vertical padding. App pages use a 1.65fr / 1fr side grid or two equal columns from 960px.

The cell bay is five equal columns; under 640px each cell becomes a horizontal row (label, reading, horizontal fill bar). Gauges are 2 x 2 and go four across when their panel container exceeds 640px. The account table restacks as labelled rows under 560px; tabs wrap. Touch targets are at least 44px (buttons and inputs 46px).

**The Unboxed Rows Rule.** Inside a panel, callouts, requests, device strips and sub-sections are unboxed rows separated by 1px rim rules. A panel never contains another card.

## Elevation & Depth

Depth is material, not floating. Surfaces step up the anodized ramp (r1 ground, r2 face, r3 raised), each edged by a 1px rim and a faint inner top highlight. Shadows are few and structural; glow is reserved for light sources (LEDs and the primary button).

### Shadow Vocabulary
- **Rail drop** (`box-shadow: 0 1px 0 rgba(255,255,255,.03), 0 10px 30px -12px rgba(0,0,0,.6)`): the sticky top rail only.
- **Panel seat** (`box-shadow: inset 0 1px 0 rgba(255,255,255,.04), 0 18px 40px -28px rgba(0,0,0,.9)`): top-level panels.
- **Glass bay** (`box-shadow: inset 0 1px 0 rgba(255,255,255,.07), inset 0 -20px 40px -30px rgba(18,171,219,.2)`): cell bays.
- **LED glow** (`box-shadow: 0 0 0 2px rgba(0,0,0,.5), 0 0 12px 2px var(--glow)`): indicator dots, tinted by health.
- **Primary lift** (`box-shadow: 0 10px 24px -14px rgba(18,171,219,.9)`): primary button.

### Named Rules
**The Flat Titanium Rule.** The plate is a flat value shift from titanium-hi to titanium, with plain dark ink. No emboss, no text shadow, no brushed stripes.

## Shapes

Corners are machined. The casing is cut on all four corners (14px chamfer via clip-path, 1px rim from a gradient border). Plates are cut on two opposite corners (top-left and bottom-right, 10px). Controls take 3px radii, panels 4px, badges and chips 2px. Fasteners are 9px flat circles in titanium-lo with a 1px #7d8b98 rim, inset 10px from the corners. Round shapes are kept for things that are round on hardware: LEDs, fasteners, timeline and station nodes, the switch.

## Components

### Buttons
Solid, machined, confident.
- **Shape:** gently squared (3px), 46px minimum height, 56px for the big variant.
- **Primary:** live-blue with live-ink, Archivo 600 at width 110%; one per view, it is the action.
- **Hover / Focus:** lighter blue (#3cbde6) on hover, 1px press on active, 2px live-blue focus outline offset 3px. Transitions 0.2s on cubic-bezier(.16, 1, .3, 1).
- **Default:** r3 face with r5 rim, r4 on hover. **Ghost:** transparent. **Danger:** transparent with a hot rim and pale orange text.
- **On a plate:** titanium-ink fill with titanium-hi text; primary keeps live-blue.

### Badges (status)
- **Style:** 2px radius, 1px currentColor border, 6px dot, uppercase Archivo label.
- **States:** Original in soft steel; PENDING / ORDERED amber; Waste / REJECTED hot; settled states titanium-filled with titanium ink.

### Cards / Containers
- **Corner Style:** 4px panels; chamfered casing and plates.
- **Background:** r2; anodized variant in capgemini-anodized.
- **Shadow Strategy:** panel seat (see Elevation).
- **Border:** 1px r4 rim.
- **Internal Padding:** 20px; nested sections become 1px-ruled rows (Unboxed Rows Rule).

### Inputs / Fields
- **Style:** r1 well, 1px r5 rim, 3px radius, 46px, live-blue caret.
- **Focus:** rim turns live-blue with a 3px rgba(18,171,219,.22) ring.
- **On a plate:** translucent white well with #8d9aa7 rim; the passport lookup field is set in Michroma uppercase.

### Navigation
The rail is r0, sticky, 64px tall, carrying the ESILV and Capgemini reversed lockup split by a 1px rule and the Michroma wordmark. Links are soft steel, 0.9rem, 40px tall, r2 background on hover. The role tag is a 1px-rimmed label; the owner bell carries a live-blue count. Labels collapse to icons under 860px.

### Titanium Identity Plate (signature)
Titanium plate with two chamfered corners and four flat fasteners, engraved Michroma ID, serial line as 1px-outlined etched tags, facts row, and a white QR plate. On the landing it carries the title, the serial line, one sentence and the passport lookup.

### Cell Bay (signature)
Five smoked-glass bays, each with a Michroma label (M1 to M5), an LED, an Archivo readout in mΩ, a fill column against a shared ruler (full column is twice the manufacturer max, dashed amber max line), a trace and a foot line. Readouts move with weighted ballistics (damped spring k 70, c 11, slight overshoot), never jump, and heat through the One Heat progression. Reduced motion drops animation.

### Status Check and Verdict
The reception check is a 1px-rimmed block with a 44px icon and a Michroma readout: live-blue when the status allows reception, hot when refused. The Défi 3 verdict is an anodized Capgemini panel with the Michroma recommendation, its action line and translucent chips; Recycle switches to recycle-slate.

### Device Strip
The ESP32 link state: LED plus label, live-blue with a 1.6s beat when online, r7 when offline. Inside a panel or the lid it is an unboxed row under a 1px rule.

## Do's and Don'ts

### Do:
- **Do** build every neutral from the r0 to r10 ramp.
- **Do** keep live-blue (#12ABDB) for live data and actions only.
- **Do** show settled states as titanium-filled badges.
- **Do** run every health signal through r9, then #F2B33D, then #FF6A3D.
- **Do** use Capgemini blue (#0070AD) as a whole anodized band or panel.
- **Do** set plate lettering, battery IDs, casing labels and status readouts in Michroma; set everything read in Archivo.
- **Do** separate sub-sections inside a panel with 1px rules.
- **Do** use Lucide icons from the sprite at 1.15em (1.5em large), stroke 1.75.
- **Do** write copy in French, with no emoji and no em or en dashes.

### Don't:
- **Don't** use green for success, approval or reception.
- **Don't** nest cards inside a panel.
- **Don't** emboss, shade or brush the titanium plate.
- **Don't** use Michroma for band or panel headings or running text.
- **Don't** use live-blue for headings, decoration or settled states.
- **Don't** use emoji or text glyphs as icons.
- **Don't** let a reading jump; live values always move with ballistics.

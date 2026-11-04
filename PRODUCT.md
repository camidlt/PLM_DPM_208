# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

FastAPI (Python) serving server-rendered Jinja templates plus a JSON API. Graph database Neo4j, with an in-memory graph fallback so the demo runs with no install. Chosen by the team: the FastAPI app is the master; the Flask app's workflow and Défi 3 logic are ported into it.

## Users

- **Jury and visitors** of the ESILV x Capgemini Engineering hackathon "Battery to the Future": discover the project on a projector or laptop, then watch the live demo.
- **Garagiste** (tablet, in the workshop): scans the battery QR code, reads the passport and live module data, reports a battery as out of service.
- **Propriétaire du Battery Passport** (desktop, office): receives the request, moves status Original to Waste, orders the transfer to an approved sorting centre.
- **Centre de tri** (phone, on the receiving dock): scans the QR code, checks the status is Waste, confirms reception, then records the end-of-life decision (Défi 3).
- **Public** (any phone): scans the QR code and sees the restricted public passport (EU Regulation 2023/1542, Annex XIII).

## Product Purpose

A digital Battery Passport proof of concept: trace an EV battery from diagnosis to sorting centre, with role-based access to a graph of passport data. Success is a jury watching a real ESP32 push module resistance into the passport, the fault surfacing on the garagiste's screen, and the battery moving through the whole chain in about two minutes.

## Positioning

The passport is fed live by a physical BMS emulator (ESP32), every step is a node in a graph (who did what, when), and the sorting centre gets an explainable recommendation (Reuse, Remanufacture, Repurpose, Recycle) with scores, matrix and market demand.

## Operating Context

Demo on a laptop on local Wi-Fi; tablet and phone open the site through printed QR codes. Neo4j Desktop optional. The ESP32 joins the same Wi-Fi and posts readings over HTTP. French-language interface.

## Capabilities and Constraints

- Mandatory flow: diagnosis, status update, transfer, reception.
- Défi 1: telemetry for 5 modules per battery, warning and critical rules, alerts, history.
- Défi 3: decision support for the sorting centre, with centre priorities and market demand toggles.
- Only the passport owner changes status; transfers only to approved centres; reception only when status is Waste and the order targets that centre.
- Test accounts with plain passwords (PoC only).
- All companies, people, VINs and batteries are fictional.

## Brand Commitments

- Hackathon by ESILV and Capgemini Engineering: both logos shown (public-domain files from Wikimedia Commons in `static/brand/`).
- Capgemini blues: `#0070AD` and `#12ABDB` (from the official logo file).
- User-pinned: futuristic luxury feel, no emoji, real icons only, no em dashes in copy, no overused AI-default fonts.

## Evidence on Hand

- Demo dataset in `bp/seed_data.py` (7 batteries, 2 models, actors, market demands). Doc's battery is `DLR-1985`.
- ESP32 firmware (`esp32/firmware`), Wokwi sketch and Python emulator.
- No real customers, metrics, or endorsements: none may be invented.

## Product Principles

1. The fault must be visible from across the room: live data first, explanation second.
2. Every role sees only what it is entitled to, and the screen says why.
3. Every recommendation is explainable down to the criterion.
4. Works on a projector, a tablet in a workshop, and a phone on a loading dock.

## Accessibility & Inclusion

WCAG AA contrast; touch targets of at least 44px for tablet and phone use with gloves.

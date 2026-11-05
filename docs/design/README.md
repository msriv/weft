# Design screens

These are the screen designs from the Weft design canvas (live copy: https://claude.ai/artifact/89b8547d-9cb7-4858-8f53-ae76ec502c02).

They are `.dc.html` source files from a design tool, not app code. They won't render on their own (they need the tool's runtime), but the markup is plain HTML with inline styles: read them for layout, copy, hierarchy and tokens, then rebuild in the Next.js app.

All names, numbers, outlets and stories in them (Aldoria, Veymar, Kessar Strait, Ostia…) are **fictional placeholders**.

| File | Screen | Route |
| --- | --- | --- |
| `Today.dc.html` | Today: overnight changes, breaking now, blind spots, followed branches | `/` |
| `Explore.dc.html` | All stories, with filters | `/stories` |
| `Main.dc.html` | Story view: short version, network graph, selected-node panel | `/s/{id}` |
| `Mobile.dc.html` | Story view on a phone (vertical timeline, 390 px) | `/s/{id}` |
| `Live.dc.html` | Breaking story in live mode, provisional anomalies | `/s/{id}?live=1` |
| `Event.dc.html` | One event, every perspective's telling | `/s/{id}/e/{eventId}` |
| `Proceeding.dc.html` | Proceeding / official document page | `/d/{id}` |
| `Source.dc.html` | Source profile: weight, reasons, ownership, anomalies | `/sources/{id}` |
| `Actor.dc.html` | Person page: statements and how they were reported | `/people/{id}` |
| `World.dc.html` | World desk: coverage threads by country, gaps | `/world` |
| `Ask.dc.html` | Ask Weft agent with evidence panel | `/ask` |
| `Method.dc.html` | How we weigh: rules, weights, models, funding, corrections log | `/method` |
| `Onboard.dc.html` | Onboarding: regions, topics, frequency, how to read a story | `/welcome` |
| `Pipeline.dc.html` | Tech stack and data pipeline diagram | (reference only) |
| `Ideas.dc.html` | Roadmap board | (reference only) |
| `Names.dc.html` | Name options | (reference only) |

## Tokens

| Token | Value |
| --- | --- |
| Background | `#060708` |
| Text | `#E8E6E1` |
| Secondary text | `#8E939B` |
| Body secondary | `#B9BDC4` |
| Document from a party (node fill) | `#9A9FA7` |
| Independent document (node) | `#E8E6E1` with outer ring and glow |
| Anomaly | `#FF7A45` (tint `rgba(255,122,69,0.1)`, light text `#FFD3C0`) |
| Hairlines | `rgba(232,230,225,0.12)` |
| Headings | Instrument Serif |
| Body | Inter |
| Labels, numbers | IBM Plex Mono, uppercase, letter-spacing 0.12–0.2em |

## Node legend

- Grey filled circle: official document issued by a party to the story
- Bright ringed circle: official document from an independent body
- Dashed circle with a number: a group of reports; the number is how many
- Orange ring with glow: anomaly (dashed orange = provisional)
- Dashed orange line between nodes: conflicting reports

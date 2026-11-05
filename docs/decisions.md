# Decisions

Short record of what was decided and why. Add an entry before changing any of these.

## D1. Weft reports coverage, never truth
**Decided:** No label, score or answer says what is true. Labels describe coverage ("reported by all perspectives", "reports conflict on", "no source has published").
**Why:** A site that rules on truth becomes a participant in the fight it's trying to referee, and both sides will attack its verdicts. Reporting who said what is defensible.
**Consequence:** No "confirmed/contradicted" statuses. Source weights never use "was this outlet right".

## D2. Anomalies are rule-based, not AI
**Decided:** Seven deterministic rules (omission, numbers differ, silence, copied text, loaded wording, unattributed, silent edit) with thresholds in `config/rules.yaml`.
**Why:** Answers the "AI is biased" objection. Every flag can be explained and reproduced. Reduces defamation risk.

## D3. Official documents are not "the record of truth"
**Decided:** Documents are labelled by issuer and whether the issuer is a party to the story (per-story `parties` list).
**Why:** A defence ministry's report on its own conflict is that side's account.

## D4. Open-weight models, narrow roles
**Decided:** Models only extract claims, check merges, translate, and answer questions (Ask agent, digests). Never flag anomalies or score sources.
**Why:** Keeps outputs traceable to source sentences, and the "we run open models you can audit" story helps with AI pushback.

## D5. Mostly pipeline steps, only two agents
**Decided:** Claim extraction and merge checks are single structured calls. Only the Ask agent and the digest writer are agentic loops.
**Why:** Agents everywhere would cost more, give non-reproducible results, and make anomalies unexplainable.

## D6. One graph store: Neo4j with its built-in vector index
**Decided:** Neo4j (AuraDB) for graph + vectors. BigQuery for raw/logs/analytics. No separate vector DB.
**Why:** Fewer systems, nothing to keep in sync.

## D7. Hosted API first, self-host later
**Decided:** MVP calls the open-weight models (Qwen3-14B, Qwen3-8B, gpt-oss-20b) through a hosted OpenAI-compatible API. Small CPU models (BGE-M3, NLI, spaCy/GLiNER, GlotLID) run on our own Cloud Run.
**Why:** At MVP volume (est. ~360M input / ~51M output tokens a month), hosted open-weight models cost roughly $11–50/month vs ~$620/month for self-hosted L4 GPUs. Closed cheap tiers (Claude Haiku 5.5, GPT-6 Luna) are ~$60/month, but can't be pinned and get retired. Same models + same API shape means moving to self-hosted vLLM later is an endpoint change.
**Watch:** Hosted providers can change quantization silently. Log provider + model + date on every call; re-run evals if outputs drift. Revisit self-hosting when the monthly API bill clearly exceeds the cost of busy GPUs.
**Prices:** third-party figures as of Nov 2, 2026; re-check before budgeting.

## D8. Daily batch plus real-time ingest
**Decided:** Stream path attaches items within minutes (provisional). Nightly batch re-groups, extracts claims and computes anomalies and weights.
**Why:** Daily-only would leave breaking stories a day stale; real-time-only accumulates grouping errors.

## D9. Anomalies are provisional early
**Decided:** Provisional until ≥ 5 sources from ≥ 2 perspectives and 6 hours since first report. No notifications for provisional anomalies.
**Why:** First-hour coverage is thin; gaps then aren't omissions.

## D10. Live view is opt-in
**Decided:** Digest is the default. Live view is turned on per story. Notifications only for new documents and non-provisional anomalies.
**Why:** A ticking feed recreates the doomscrolling pattern Weft exists to counter.

## D11. GDELT is a discovery feed, not a source of record
**Decided:** Use GDELT to find new outlets, measure coverage gaps, and as a weak grouping signal. Never show its tone scores or event codes.
**Why:** Free, global, 15-minute, BigQuery-native; but machine-coded and noisy. Note FIPS 10-4 country codes.

## D12. Summaries, not articles
**Decided:** Store and show summaries, short quotes and links. Raw copies private, 30-day retention (pending legal review).

## D13. No ads
**Decided:** Funded by reader subscriptions and donations (exact model open). No advertising, no funding from parties covered.

## D14. Name: Weft
**Decided:** "Weft". In weaving, the warp is the fixed threads and the weft is woven across them: the record is the warp, narratives are the weft. Alternatives considered: Parallax, Sightline, Undercurrent. Trademark and domain not yet checked.

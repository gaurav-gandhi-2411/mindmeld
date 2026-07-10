# Warmer — Cricket Pack (content drop)

## Why this pack
Pack #2, and the broadest India-wedge theme — cricket cuts across every region, age, and class more universally than any other. Its vocabulary is concrete (bat, catch, boundary, victory), which embeds well in a semantic game. The pack SYSTEM already exists (built in the packs phase), so this is a content-only drop: author → GG review → bake → publish → deploy. No engineering.

Retargetable: this spec's structure applies to any future pack (Indian Food, Nature & Wild, Space & Science) — swap the theme, keep the process. Cricket is the recommendation.

## Design constraints (carried from the Bollywood pack — do not relearn these)
1. **Secrets are guessable COMMON NOUNS with good embedding neighborhoods, in vocab** (extend + eval-gate per new word, like Hinglish/Bollywood). NOT proper nouns — no Sachin, Kohli, Dhoni, IPL, World Cup, team names. Those play terribly in a semantic game (sparse neighborhoods).
2. **The theme lives in the CLUE and the curation, not the secret.** Cricket → secret `boundary`, clue "Four runs the easy way, racing along the ground."
3. **Embedding-validate every secret** (esp. romanized Hinglish): the multilingual model misreads some romanized words as other languages (Bollywood found dil→Turkish, dua→Italian). Reject those; go code-mixed English where the romanized word fails (cricket is heavily code-mixed in Indian speech anyway — wicket, over, catch are said in English mid-Hindi).
4. **Semantic-neighbor audit on clues** (beyond the exact-alias spoiler gate): a clue must not contain a strong SEMANTIC NEIGHBOR of its secret (e.g. don't put "runs" in the `boundary` clue, "throw" in the `catch` clue). Neighbors trivialize a semantic-distance game even though they pass the exact-match gate. Audit all clues both languages; reword toward the situation.
5. **~25 secrets, EN + Hinglish**, clues authored natively per language (Hinglish written for an Indian player — gully cricket, IPL, India-Pak match-day energy — not translated).
6. **Distinct visual identity** per pack — Cricket = green (reserved earlier), distinct from Bollywood's gold/crimson and the core heat-rings palette.

## Cricket-specific risks (watch these)
- **Neighborhood collisions.** Some cricket terms have a dominant non-cricket meaning that hijacks the embedding: `duck` (embeds as the animal, not zero-runs), `maiden` (embeds as woman/first, not the over), `over` (embeds as the preposition), `pitch` (sales pitch / musical pitch). Embedding-validate each — if the cricket sense doesn't drive a fair hot/cold gradient, swap the word. Prefer terms whose common meaning aligns or is neutral (bat, catch, boundary, victory, stadium, captain, umpire, six, century, trophy).
- **Cricket-specific vocab not in base vocab** (yorker, googly, bouncer, stumps, bails, crease) — add + eval-gate like Bollywood's 11 additions, and check neighborhood quality before committing; some may embed too sparsely to play well.
- **Proper-noun temptation is strong** in cricket — resist hard. Legends/tournaments belong in CLUES as flavor ("The little master made this his signature"), never as secrets.

## Quality bar (examples — sets direction; CC drafts the full 25)
| EN / hi-en secret | EN clue | Hinglish clue |
|---|---|---|
| victory / jeet | The whole nation stays up past midnight for it | India-Pak match ke baad puri gali ka shor |
| boundary / boundary | Four runs the easy way, racing along the ground | Chauka — zameen chhoo ke seedha rope ke paar |
| catch / catch | Drop it, and you'll hear about it for years | Chhoot gaya toh taane saalon tak |
| captain / captain | Reads the game, and takes the blame | Match haara toh sabse pehle isi pe ungli |
| appeal / appeal | An entire team turns and shouts one word | Gyaarah log ek saath — 'howzzat!' |
| stadium / stadium | Sixty thousand voices, one collective gasp | Ek chhakke pe saath hazaar log ek saath uchhle |

Note: several secrets will be code-mixed English (boundary, catch, captain, appeal, stadium) — verified dense in both vocabs, exactly as Bollywood found. That's correct, not a compromise.

## Scope
1. Draft ~25 Cricket secrets (common nouns, embedding-validated, in/added-to vocab + eval-gated) + Cricket-flavored clues in EN and Hinglish. None duplicating the 60 daily secrets or the 25 Bollywood secrets.
2. GG review (STOP POINT) — print all secrets + clues both languages before baking.
3. (After approval) Generate payloads via the existing pack pipeline (rival/par/maxGuesses), run: exact-alias spoiler gate + semantic-neighbor audit + size gates + byte-reproducibility (the sorted-serialization fix). Publish under the packs/ namespace.
4. Cricket visual identity (green accent + a cricket motif — ball seam or stumps), applied to the pack tile/header/puzzle accent; distinct from all existing packs.
5. Flip the Cricket "Coming soon" stub to live in the pack selector; keep Indian Food / Nature teased.

## Acceptance criteria
1. ~25 authored secrets + clues (EN + Hinglish); no proper nouns; none duplicate daily or Bollywood secrets.
2. Exact-alias spoiler gate: 0 leaks across all clues.
3. Semantic-neighbor audit run on all clues both languages; report which were reworded.
4. Every secret embedding-validated to play with a fair hot/cold gradient (collision words swapped); report any rejected + why.
5. Vocab additions eval-gated; report thinnest margin.
6. Payloads generated: rival/par/maxGuesses present, size gates pass, byte-reproducible.
7. Cricket has a distinct green identity; not a reuse of Bollywood's or the core mark.
8. Cricket tile is live (not "Coming soon") in the selector; a full Cricket puzzle plays EN + Hinglish, win + share shows "Warmer · Cricket #N".
9. All tests green; daily streak provably unaffected by Cricket pack play.
10. Live-verify on playwarmer.vercel.app via the cold-profile harness: selector shows Cricket live with its identity, a full puzzle plays in both languages, share text correct.

## Risks
- **Neighborhood collisions** (duck/maiden/over/pitch) — the main content risk; embedding-validate and swap.
- **Clue quality is the make-or-break lever** — GG review mandatory; Cricket clues should be vivid and match-day-evocative, still solvable and spoiler-free.
- **Proper-noun drift** — keep legends/tournaments in clues, never secrets.

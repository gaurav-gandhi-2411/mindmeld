# Third-party models, data and notices

The code in this repository is MIT-licensed (see `LICENSE`). The models and data below are
not ours and keep their own licences. Generated payloads (`mindmeld-payloads`) contain
similarity ranks derived from these models and word lists.

## Models (downloaded at build time, not vendored)

| Component | Used for | Licence | Source |
|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | English embeddings (pinned revision in `generator/config.py`) | Apache-2.0 | https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 |
| `l3cube-pune/indic-sentence-bert-nli` | Base model of our Hinglish fine-tune | CC-BY-4.0 | https://huggingface.co/l3cube-pune/indic-sentence-bert-nli |
| `gauravgandhi2411/hinglish-relatedness-sbert` | Hinglish embeddings (ours, fine-tuned from the l3cube base above) | CC-BY-4.0 (inherits the base's attribution terms) | https://huggingface.co/gauravgandhi2411/hinglish-relatedness-sbert |

Attribution for the base model: [L3Cube-Pune](https://huggingface.co/l3cube-pune), CC-BY-4.0
(see the base model's card for its citation).

## Data

| Component | Where | Licence | Notes |
|---|---|---|---|
| wordfreq 3.1.1 | `generator/vocab/en.txt` is generated from its English frequency list | Code Apache-2.0; **data CC-BY-SA-4.0** | `en.txt` is a derived work of wordfreq's data and is distributed under CC-BY-SA-4.0, not MIT. wordfreq's data includes Google Books Ngrams and other CC-licensed sources; see https://github.com/rspeer/wordfreq#license |
| LDNOOBW (List of Dirty, Naughty, Obscene, and Otherwise Bad Words) | `generator/vocab/blocklist_ldnoobw_en.txt`, `blocklist_ldnoobw_hi.txt` (pinned to commit `5faf2ba42d7b1c0977169ec3611df25a3c08eb13`) | CC-BY-4.0 | https://github.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words. Used only to *exclude* words. |

Curated lists written for this project (`hinglish.txt`, `secrets_*.txt`, `clues-*.txt`,
`hi-en-*.txt`, `blocklist_supplement_*.txt`) are covered by the repository's MIT licence.

## Packages

Python, Dart/Flutter and npm dependencies are installed from their registries and keep their
own licences, as pinned in `generator/uv.lock`, `app/pubspec.lock` and
`firebase-tests/package-lock.json`. None is vendored into this repository.

# Detector baseline

Does the optional Jev hook earn its place? Four detectors are scored on one labelled corpus of event windows: Jev, Claude Haiku (what a Claude Code prompt hook does by default), a cheap OpenRouter LLM, and a deterministic heuristic. All four see the same question, imported from the hook so it cannot drift.

## 1. Capture

Set `SKILL_IMPROVER_JEV_CORPUS` to a file path (relative to the project root, or absolute) in the environment of at least 3 real projects for at least 2 weeks. The hook appends one redacted `{"t", "g", "trigger", "window"}` line per `fail` or `prompt` event, file mode `0600`; `g` is an opaque hash of project and session, shared by every window that session captures. Unset, nothing is written.

## 2. Label

```bash
python3 bench/detector/label.py capture1.jsonl capture2.jsonl --labeler A
```

Dedupes by window, assigns `id = sha1(window)[:12]`, and splits `dev`/`test` by the parity of `g`, so a session's overlapping windows (successive ones share up to seven of eight events) never straddle the split. A capture line without `g` is refused. Answer `y`/`n`/`s`/`q`; `bench/detector/corpus/corpus.jsonl` is rewritten after every answer. No detector output is ever shown. Rerun to resume.

Second labeler, on a sample of already-labelled windows:

```bash
python3 bench/detector/label.py --relabel-sample 50 --labeler B   # writes corpus/labels_B.jsonl
```

## 3. Run

```bash
pip install -r bench/requirements.txt          # anthropic
python3 bench/detector/run.py --corpus bench/detector/corpus/corpus.jsonl \
  --detectors heuristic,jev,claude_haiku,openrouter_llm \
  --openrouter-model <id> --second-labels bench/detector/corpus/labels_B.jsonl \
  --out bench/detector/results/$(date -u +%F)
```

- `--detectors` defaults to `heuristic`, the only one that needs no key or network.
- `--openrouter-model` is required with `openrouter_llm`; no default is chosen.
- Keys: `OPENROUTER_API_KEY` (jev, openrouter_llm), `ANTHROPIC_API_KEY` (claude_haiku).
- `--second-labels` prints Cohen's kappa against the first labeler.

Output: `<out>/<detector>.jsonl` (raw rows) and `<out>/summary.json` (per split: n, number of session groups, P/R/F1 with 95% intervals from a bootstrap that resamples whole session groups, false nudges per 100 non-lesson windows, latency p50/p95, mean bytes out, errors; exact model ids; `date -u`). A failed call counts as a miss and is reported in `errors`. For Jev, the F1-best threshold is picked on `dev` and `test` is reported at both 0.6 (shipped) and that threshold.

## Corpus targets

At least 200 unique windows with at least 60 positives. A second labeler on a 50-window sample: kappa >= 0.6, or the labels are revisited before any result is published. Anonymise before committing: run `D.redact` again over every string and hand-scan for project names; commit only a `corpus.jsonl` that passed this.

## Decision rule (on the `test` split)

- Jev F1 >= Haiku F1 - 0.05 **and** (Jev p95 latency <= 1/2 Haiku's **or** cost <= 1/10) -> keep Jev as the detector, document why.
- Heuristic F1 >= best F1 - 0.05 -> replace Jev with the heuristic (no network) and keep Jev as an option only if it wins on false-nudge rate.
- Otherwise -> recommend a native Claude Code prompt hook, and plan Jev's removal in a follow-up.

## Result

Pending — no corpus has been labelled yet.

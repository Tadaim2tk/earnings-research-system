# Earnings Document Analysis

## Purpose

This capability converts a text-bearing Japanese earnings PDF into structured research data. It sits after the Level 2 monitor handoff and before comparison with a locked pre-event baseline.

```text
monitor handoff
  -> target document discovery
  -> temporary acquisition
  -> PDF text extraction
  -> normalized financial and narrative analysis
  -> consistency checks
  -> structured JSON
  -> pre-event comparison
```

The source PDF or HTML is used only in a temporary directory and is deleted after processing. The repository retains the source URL, SHA-256, acquisition time, page references, normalized findings, and validation results. It does not retain the raw document body.

## Supported documents

- Japanese earnings releases with extractable text and the standard summary tables used by the current ICECO proof
- Earnings presentation PDFs when they expose the same explicit table structure
- Direct PDF monitor handoffs
- Static HTML pages containing links labelled as an earnings release or earnings presentation

Non-earnings notices are excluded. Image-only, malformed, encrypted, or structurally unsupported PDFs become an explicit `unparseable` result. OCR and inferred values are not used.

## Structured result

The contract is [earnings_document_analysis.schema.json](../schemas/analysis/earnings_document_analysis.schema.json). It records:

- company, ticker, accounting period, reporting scope, announcement date, document type, source URL, hash, and acquisition time
- actual, prior-period actual, company forecast, and ERS-calculated values as separate `value_kind` values
- displayed units and normalized units together
- period scope and comparison basis for every metric
- source page and text anchor for every metric and narrative finding
- company-specific metrics as an extensible category/name/value list
- reported and calculated year-on-year changes as separate values
- calculated full-year progress with its formula and input metric names
- narrative drivers, forecast and dividend revision status, business environment, and outlook
- consistency checks and unresolved items

The parser fails closed when a required table cannot be read. Conflicting reported and calculated values are retained and marked `review_required`; they are not silently reconciled.

## ICECO proof

The repository includes [EDA-7698-20250212.json](../data/research/iceco/EDA-7698-20250212.json), produced from the official JPX disclosure PDF for ICECO's fiscal year ending March 2025 third-quarter earnings release.

The proof records the nine-month cumulative period from 2024-04-01 through 2024-12-31, the corresponding prior period, the full-year company forecast, segment figures for the frozen-food and supermarket businesses, the disclosed operating factors, and calculated progress. It contains 34 financial metrics, 4 company-specific metrics, 7 narrative findings, and 5 consistency checks. All checks passed and `raw_document_retained` is `false`.

## Commands

Analyze one known PDF:

```bash
python -m earnings_research.cli analyze-earnings-document \
  --url https://example.com/earnings.pdf \
  --title '決算短信' \
  --output .monitor/analysis/result.json
```

Consume a monitor handoff:

```bash
python -m earnings_research.cli analyze-earnings-handoff \
  .monitor/handoff/handoff.json \
  --output-dir .monitor/analysis
```

The scheduled workflow uploads the structured analysis directory as an artifact. It does not commit generated state or source documents to the repository.

## Source boundary

Document acquisition remains subject to the existing public-web policy. A direct public document may be analyzed when its location is known and access is permitted. If an IR page delegates its document listing to a source whose robots policy disallows automated access, the analyzer does not bypass that restriction. In that case the handoff records no target document until a permitted direct source is supplied.

For the ICECO historical proof, the exact public JPX disclosure URL was used. The raw PDF was not retained.

## Deferred work

- OCR for image-only documents
- layouts that do not expose the supported summary structure
- price acquisition and return calculation
- trading decisions or order execution
- multi-company rollout
- automatic modification of locked baselines

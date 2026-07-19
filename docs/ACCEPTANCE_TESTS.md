# Acceptance Tests

The initial foundation is acceptable when:

- The requested project folder structure exists.
- All initial documentation files exist and state current scope, prohibited scope, and open questions.
- JSON schema files exist for all initial CSV entities.
- Evidence/source lineage schema and samples exist.
- Generic KPI observation schema and samples exist.
- Fictional sample CSV files exist for at least three companies across at least two industries.
- Samples include SNS overheat, conservative guidance, value trap, NO_TRADE, a missing value, and an invalidated hypothesis.
- `python -m earnings_research.cli validate data/samples` succeeds on the sample set.
- `python -m earnings_research.cli validate-file path/to/file.csv` works for a known table sample.
- `python -m earnings_research.cli show-schema pre_earnings_baseline` prints schema metadata.
- Pytest covers valid samples and representative validation failures.
- Pytest covers evidence timing, score effective dates, and TSO mapping unknown-status handling.
- Pytest covers announcement sessions, accounting standards, return base price policies, and KPI evidence references.
- Pytest covers append-only KPI expected/actual row splitting, return reference price requirements, SHORT trade price ordering, extended evidence timing, and relationship consistency checks.
- TSO files and TSO schema are not modified.
- External API, scraping, trading, and backtesting are not implemented.

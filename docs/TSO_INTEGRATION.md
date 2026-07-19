# TSO Integration

Earnings Research System is currently loosely coupled with Tactical Swing OS.

## Current Contract

- TSO_LOG is treated as an external input.
- Source `signal_id` is preserved.
- TSO rows are not modified in place.
- Imports should store `source_file` and `source_row_hash`.
- TSO scores are stored as snapshots tied to an earnings event and timestamp.
- The mapping to the official TSO_LOG 28 columns is provisional and must be finalized later.

## Open Integration Issues

- How to handle multiple TSO signals at the same timestamp.
- Whether to use the latest pre-event signal, a time-window aggregate, or a human-selected signal.
- How `no_trade_flag` should interact with earnings-specific NO_TRADE logic.
- Whether future exports should use CSV, JSON, SQLite views, or a service boundary.

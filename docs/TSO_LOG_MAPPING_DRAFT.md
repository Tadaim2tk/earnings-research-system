# TSO LOG Mapping Draft

This draft is based on the current local TSO `data/signal_log.csv` header observed on 2026-07-19. It is not the formal TSO_LOG 28-column contract.

The earlier working assumption was "formal 28 columns". The current local header contains 29 columns because `origin` appears after `verified_status`. This mismatch is unresolved. `origin` must remain provisional until the TSO_LOG owner confirms whether it is an extension, a new formal column, or a local ingestion artifact.

| tso_log_column | meaning | target_table | target_column | required_or_optional | type | range_or_allowed_values | notes | mapping_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| date | Signal date | `tso_snapshot` | `as_of_datetime` | required | date | ISO date | Convert to a timestamp policy later. | likely |
| signal_id | TSO signal identifier | `tso_snapshot` | `signal_id` | required | string | non-empty | Preserve exactly. | likely |
| asset | TSO asset symbol | `tso_snapshot` | unknown | required | string | unknown | ERS company mapping is not defined. | unknown |
| side | Direction | `tso_snapshot` | unknown | required | enum | LONG, SHORT, NONE likely | ERS does not yet store side. | unknown |
| rank | TSO rank | `tso_snapshot` | `rank` | optional | string/integer conflict | A, B, NO_TRADE in TSO; integer in ERS snapshot | ERS currently uses numeric rank, so mapping is unresolved. | unknown |
| type | Setup type | `tso_snapshot` | unknown | optional | string | unknown | No target column yet. | unknown |
| entry_low | Entry lower bound | not_applicable | not_applicable | optional | decimal | price | Trading execution fields are out of ERS scope. | not_applicable |
| entry_high | Entry upper bound | not_applicable | not_applicable | optional | decimal | price | Trading execution fields are out of ERS scope. | not_applicable |
| sl | Stop loss | not_applicable | not_applicable | optional | decimal | price | Broker/trading fields are not imported into ERS. | not_applicable |
| tp1 | Take profit 1 | not_applicable | not_applicable | optional | decimal | price | Broker/trading fields are not imported into ERS. | not_applicable |
| tp2 | Take profit 2 | not_applicable | not_applicable | optional | decimal | price | Broker/trading fields are not imported into ERS. | not_applicable |
| rr | Risk/reward | `tso_snapshot` | unknown | optional | decimal | >=0 likely | Could inform context but no column exists. | unknown |
| win_prob | Win probability | `tso_snapshot` | unknown | optional | decimal | 0-1 or 0-100 unresolved | Unit must be confirmed. | unknown |
| expected_r | Expected R | `tso_snapshot` | `expected_r` | optional | decimal | provisional -10 to 10 | Unit matches ERS provisional range. | likely |
| tq_score | Timing/quality score | `tso_snapshot` | unknown | optional | decimal | 0-100 likely | No target column yet. | unknown |
| opp_score | Opportunity score | `tso_snapshot` | unknown | optional | decimal | 0-100 likely | No target column yet. | unknown |
| no_trade_score | No-trade score | `tso_snapshot` | unknown | optional | decimal | 0-100 likely | ERS has `no_trade_flag` and reason, not score. | unknown |
| risk_pct | Risk percent | not_applicable | not_applicable | optional | decimal | 0-100 likely | Position sizing is outside ERS scope. | not_applicable |
| regime | Market regime | `tso_snapshot` | `regime` | optional | string | unresolved | ERS enum may need expansion to match TSO. | likely |
| ems | EMS score | `tso_snapshot` | `ems` | optional | decimal | 0-100 provisional | Preserve source score. | likely |
| ffs | FFS score | `tso_snapshot` | unknown | optional | decimal | 0-100 likely | No ERS column yet. | unknown |
| cds | CDS score | `tso_snapshot` | unknown | optional | decimal | 0-100 likely | No ERS column yet. | unknown |
| ias | IAS score | `tso_snapshot` | unknown | optional | decimal | 0-100 likely | No ERS column yet. | unknown |
| cbs | CBS score | `tso_snapshot` | `cbs` | optional | decimal | 0-100 provisional | Preserve source score. | likely |
| mes | MES score | `tso_snapshot` | `mes` | optional | decimal | 0-100 provisional | Preserve source score. | likely |
| invalidation | Invalidation condition | `tso_snapshot` | `no_trade_reason` | optional | string | unknown | May be reason context, not identical to no-trade reason. | unknown |
| verification_target | Later verification target | `tso_snapshot` | unknown | optional | string | unknown | Could move to evidence or hypothesis later. | unknown |
| verified_status | Verification status | evidence | `verified_status` | optional | enum | TSO-specific values unresolved | Better represented as evidence status when importing. | likely |
| origin | Source origin | evidence | `source_name` | optional | string | unknown | Current local `signal_log.csv` includes this extension. | likely |

## Known Gap

The formal 28-column TSO_LOG definition is still missing. No unknown mapping should be promoted to confirmed without the official TSO contract and a test fixture.

## Minimum Candidate Fields For ERS

ERS likely needs only a small TSO context subset at first:

- `date`
- `signal_id`
- `asset`, only after a company/event mapping rule exists
- `rank`, only after the string-vs-numeric conflict is resolved
- `expected_r`
- `regime`
- `ems`
- `cbs`
- `mes`
- `verified_status`, preferably as evidence status
- `origin`, only after its formal meaning is confirmed

`side`, entry/exit levels, risk percent, and position-management fields should not be imported into ERS scoring until the research/trading boundary is explicitly approved.

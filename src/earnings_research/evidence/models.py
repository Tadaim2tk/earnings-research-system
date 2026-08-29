"""What was available to read, recorded before anyone reads it.

The retired pipeline made one call that chose eight companies, searched the
web, extracted the numbers, judged them and assigned a letter. Only the letter
survived. So its record cannot answer the question a better model would make
worth asking — what did the disclosure actually say — and no future model can
re-read those events, because nothing kept what there was to read.

This module keeps the first layer only: the population, fixed before anything
is fetched, and the evidence itself, stored with the hash of its own content.
No facts are extracted here and nothing is judged. Those can be redone from
this any number of times; this cannot be redone from them.

Two properties do the work.

**The population is fixed first, and every event it names is accounted for.**
The retired pipeline asked a model for "eight notable companies", so the
cohorts it later compared were drawn from a group the model had already
filtered — which is why one D exists in 254 records. Here the day's events are
listed, an explicit rule marks each one included or excluded, and an excluded
event stays in the manifest with the rule that excluded it. A company can be
left out, but not left out quietly.

**An evidence bundle says what happened to it.** `capture_status` is part of
the record, so a page that could not be fetched is a fetch that failed rather
than an event with less evidence. Nothing is substituted for it later: the
status is how the absence stays visible, the same way `undeclared` and
`unknown` do elsewhere in this system.
"""

import hashlib
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_POPULATION = "evidence_population_manifest_v1"
SCHEMA_BUNDLE = "evidence_bundle_v1"

# What happened when this source was fetched. Every one of these is a recorded
# outcome; none of them is a reason to quietly put something else in its place.
CaptureStatus = Literal["captured", "unavailable", "fetch_failed", "unsupported"]
CAPTURE_STATUSES = ("captured", "unavailable", "fetch_failed", "unsupported")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class EventRef(BaseModel):
    """One earnings event in the day's population."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    disclosure_kind: str = Field(min_length=1)
    listed_at: datetime

    @model_validator(mode="after")
    def validate_event(self):
        if self.listed_at.tzinfo is None:
            raise ValueError("listed_at must include timezone")
        return self


class ExcludedEvent(BaseModel):
    """An event the population rule left out, and which rule left it out.

    Kept rather than dropped. A cohort comparison over a population that
    silently lost its weakest members reports a difference between what
    survived selection, not between the categories it names.
    """

    model_config = ConfigDict(extra="forbid")

    event: EventRef
    rule: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class PopulationManifest(BaseModel):
    """The day's events, fixed before any evidence is fetched.

    Fixed first because the alternative is what the retired pipeline did: ask a
    model which companies are worth looking at, and then study the ones it
    picked. The selection cannot be separated from the finding afterwards.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence_population_manifest_v1"] = SCHEMA_POPULATION
    manifest_id: str = Field(min_length=1)
    population_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    # Where the list of the day's events came from. Not the evidence itself —
    # the roster. A population drawn from an unnamed place cannot be redrawn.
    source: str = Field(min_length=1)
    source_retrieved_at: datetime
    # The rule, as text a person can check, applied to every listed event.
    inclusion_rule: str = Field(min_length=1)
    included: List[EventRef]
    excluded: List[ExcludedEvent] = Field(default_factory=list)
    fixed_at: datetime

    @model_validator(mode="after")
    def validate_manifest(self):
        for name in ("source_retrieved_at", "fixed_at"):
            if getattr(self, name).tzinfo is None:
                raise ValueError("%s must include timezone" % name)
        if self.fixed_at < self.source_retrieved_at:
            raise ValueError("the population cannot be fixed before its source was read")
        ids = [item.event_id for item in self.included] + [
            item.event.event_id for item in self.excluded
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("an event appears twice in the population")
        if not ids:
            raise ValueError("a population with no events is not a population")
        return self

    def event_ids(self) -> List[str]:
        return [item.event_id for item in self.included]


class EvidenceBundle(BaseModel):
    """One source, as it was when it was read.

    `content_sha256` is over `content`, so the stored text can be shown to be
    the text that was hashed. Together with `retrieved_at` that is what lets a
    model years from now read the same thing rather than whatever the URL says
    by then — most of these pages are replaced, and some stop existing.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence_bundle_v1"] = SCHEMA_BUNDLE
    bundle_id: str = Field(min_length=1)
    manifest_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    published_at: Optional[datetime] = None
    retrieved_at: datetime
    capture_status: CaptureStatus
    content: Optional[str] = None
    content_sha256: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # How this source came to be fetched at all. A URL with no discovery
    # provenance cannot be re-derived, and the order matters: a model reading
    # the first three results saw a different thing from one reading all ten.
    discovery_query: Optional[str] = None
    discovery_method: str = Field(min_length=1)
    result_order: Optional[int] = Field(default=None, ge=0)
    fetch_implementation: str = Field(min_length=1)
    note: Optional[str] = None

    @model_validator(mode="after")
    def validate_bundle(self):
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must include timezone")
        if self.published_at is not None and self.published_at.tzinfo is None:
            raise ValueError("published_at must include timezone")
        if self.capture_status == "captured":
            if not self.content:
                raise ValueError("a captured bundle has to carry what it captured")
            if self.content_sha256 != sha256_text(self.content):
                raise ValueError("content_sha256 does not hash the content beside it")
        else:
            # Absence is recorded as absence. An empty string or a placeholder
            # here would read downstream as a source that said nothing, which
            # is a different fact from a source nobody could read.
            if self.content is not None or self.content_sha256 is not None:
                raise ValueError(
                    "a bundle that was not captured carries no content; its status is the record"
                )
        return self

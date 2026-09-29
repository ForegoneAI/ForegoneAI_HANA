"""
store.py

H9N Milestone 1, item 4 - Human Review and Correction.

A minimal deal store so an extracted REPEDealProfile can be looked up later
by id, corrected by a human reviewer, and re-saved. This intentionally does
NOT use a real database - it writes one JSON file per deal under a local
directory (backend/data/reviews/ by default, already excluded from git by
.gitignore's `data/` rule, since a saved deal can hold information from a
real, non-public deal package).

A production version of this would need a real database, authentication
(who is allowed to correct a deal), and an audit trail of who changed what
and when. This gives the team a working checkpoint - "can a reviewer see an
extracted deal and fix a wrong value" - without building that infrastructure
first. corrected_fields (see base_deal.py) is the audit trail for now: it
records WHICH fields a human touched, though not who or when.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from backend.app.h9n.schemas.base_deal import ReviewStatus
from backend.app.h9n.schemas.repe_deal import REPEDealProfile

DEFAULT_STORE_DIR = Path("backend/data/reviews")

# The extractor's own bookkeeping fields. Setting one of these via
# apply_corrections() is still allowed (a reviewer might want to clear a
# stale missing_information note, for example) but doesn't itself count as
# "correcting a value", so it's not added to corrected_fields.
_TRACKING_FIELDS = {
    "missing_information",
    "conflicting_information",
    "evidence",
    "uncertain_information",
    "corrected_fields",
    "review_status",
    "review_feedback",
}

# What a reviewer is actually allowed to submit through set_review_status().
# "pending" isn't included here - that's only ever the starting state a
# fresh extraction gets, not something a reviewer submits.
_SUBMITTABLE_REVIEW_STATUSES = {"approved", "rejected"}


class DealNotFoundError(KeyError):
    """Raised when a deal_id doesn't match any saved deal."""


class DealStore:
    """Saves and retrieves REPEDealProfile objects by id, on local disk."""

    def __init__(self, store_dir: Path | str = DEFAULT_STORE_DIR) -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, deal_id: str) -> Path:
        return self.store_dir / f"{deal_id}.json"

    def _pages_path_for(self, deal_id: str) -> Path:
        return self.store_dir / f"{deal_id}.pages.json"

    def save(self, deal: REPEDealProfile, deal_id: str | None = None) -> str:
        """Saves a deal profile, returning the id it was saved under (a new
        random one if deal_id isn't given, e.g. right after extraction)."""
        deal_id = deal_id or uuid.uuid4().hex
        self._path_for(deal_id).write_text(json.dumps(deal.model_dump(), indent=2))
        return deal_id

    def get(self, deal_id: str) -> REPEDealProfile:
        path = self._path_for(deal_id)
        if not path.exists():
            raise DealNotFoundError(deal_id)
        return REPEDealProfile(**json.loads(path.read_text()))

    def list_ids(self) -> list[str]:
        return sorted(
            path.stem for path in self.store_dir.glob("*.json") if not path.name.endswith(".pages.json")
        )

    def save_pages(self, deal_id: str, pages: list[dict[str, Any]]) -> None:
        """Saves the page-preserved source text a deal was extracted from
        (the same list of {"file_name", "page_number", "text"} dicts
        `read_pdf()`/`extract_repe_deal()` use), keyed to the same deal_id.

        This is what lets a later reviewer rejection go back to the actual
        document instead of only the (possibly wrong) extracted values -
        see `apply_reviewer_feedback` in repe_extractor.py. Kept in a
        sibling file rather than merged into the deal's own JSON so it
        doesn't round-trip through REPEDealProfile (which has no field for
        it) and get silently dropped on the next save().
        """
        self._pages_path_for(deal_id).write_text(json.dumps(pages, indent=2))

    def get_pages(self, deal_id: str) -> list[dict[str, Any]]:
        """Returns the pages saved for a deal via save_pages(), or raises
        DealNotFoundError if none were ever saved for that id (e.g. the deal
        predates this feature, or was created without a source document)."""
        path = self._pages_path_for(deal_id)
        if not path.exists():
            raise DealNotFoundError(deal_id)
        return json.loads(path.read_text())

    def has_pages(self, deal_id: str) -> bool:
        """Whether save_pages() has ever been called for this deal_id -
        lets a caller check before attempting a feedback-driven correction
        instead of having to catch DealNotFoundError from get_pages()."""
        return self._pages_path_for(deal_id).exists()

    def apply_corrections(self, deal_id: str, corrections: dict[str, Any]) -> REPEDealProfile:
        """Applies a reviewer's corrections (a dict of field_name -> new
        value) to a saved deal, re-saves it, and returns the updated deal.

        Each corrected field (other than the extractor's own bookkeeping
        lists) is recorded in `corrected_fields`. Field values are validated
        the same way they would be on construction (BaseDeal sets
        `validate_assignment=True`), so a bad value (wrong type, unknown
        field) raises instead of silently corrupting the saved deal.
        """
        deal = self.get(deal_id)

        for field_name, new_value in corrections.items():
            if field_name not in REPEDealProfile.model_fields:
                raise ValueError(f"{field_name!r} is not a field on REPEDealProfile.")
            setattr(deal, field_name, new_value)
            if field_name not in _TRACKING_FIELDS and field_name not in deal.corrected_fields:
                deal.corrected_fields.append(field_name)

        self.save(deal, deal_id=deal_id)
        return deal

    def set_review_status(self, deal_id: str, status: ReviewStatus) -> REPEDealProfile:
        """Records a reviewer's explicit verdict on a saved deal: "approved"
        if they've looked it over (including any corrections already applied
        via apply_corrections()) and confirm it's right, or "rejected" if
        they've looked and it still isn't. This is a separate, deliberate
        signal from apply_corrections() - fixing one field's value doesn't
        by itself mean a reviewer has looked at the whole profile and signed
        off on it.
        """
        if status not in _SUBMITTABLE_REVIEW_STATUSES:
            raise ValueError(
                f"{status!r} is not a status a reviewer can submit - expected one of "
                f"{sorted(_SUBMITTABLE_REVIEW_STATUSES)}."
            )
        deal = self.get(deal_id)
        deal.review_status = status
        self.save(deal, deal_id=deal_id)
        return deal

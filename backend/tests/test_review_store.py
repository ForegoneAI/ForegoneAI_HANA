"""
Automated tests for DealStore (Milestone 1, item 4 - Human Review and
Correction). These write only to pytest's tmp_path, never to the real
backend/data/reviews/ directory.
"""

import pytest

from backend.app.h9n.review.store import DealNotFoundError, DealStore
from backend.app.h9n.schemas.repe_deal import REPEDealProfile


def test_save_and_get_round_trips_a_deal(tmp_path):
    store = DealStore(tmp_path)
    deal = REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000)

    deal_id = store.save(deal)
    fetched = store.get(deal_id)

    assert fetched.deal_name == "Fixture Deal"
    assert fetched.asking_price == 1_000_000


def test_get_raises_for_an_unknown_id(tmp_path):
    store = DealStore(tmp_path)

    with pytest.raises(DealNotFoundError):
        store.get("does-not-exist")


def test_apply_corrections_updates_the_value_and_records_it(tmp_path):
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000))

    corrected = store.apply_corrections(deal_id, {"asking_price": 950_000})

    assert corrected.asking_price == 950_000
    assert corrected.corrected_fields == ["asking_price"]
    # The correction should have been persisted, not just returned in memory.
    assert store.get(deal_id).asking_price == 950_000


def test_apply_corrections_does_not_double_record_the_same_field(tmp_path):
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(asking_price=1_000_000))

    store.apply_corrections(deal_id, {"asking_price": 950_000})
    corrected = store.apply_corrections(deal_id, {"asking_price": 900_000})

    assert corrected.asking_price == 900_000
    assert corrected.corrected_fields == ["asking_price"]


def test_apply_corrections_rejects_an_unknown_field(tmp_path):
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(deal_name="Fixture Deal"))

    with pytest.raises(ValueError):
        store.apply_corrections(deal_id, {"not_a_real_field": 123})


def test_apply_corrections_rejects_a_bad_type_for_a_typed_field(tmp_path):
    # BaseDeal sets validate_assignment=True specifically so this fails
    # loudly instead of silently corrupting the saved deal.
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(asking_price=1_000_000))

    with pytest.raises(Exception):
        store.apply_corrections(deal_id, {"asking_price": "not a number"})


def test_apply_corrections_on_a_tracking_field_does_not_mark_it_corrected(tmp_path):
    # Clearing a stale missing_information note is a housekeeping edit, not
    # "correcting a value", so it shouldn't show up in corrected_fields.
    store = DealStore(tmp_path)
    deal_id = store.save(
        REPEDealProfile(deal_name="Fixture Deal", missing_information=["cap_rate not stated"])
    )

    corrected = store.apply_corrections(deal_id, {"missing_information": []})

    assert corrected.missing_information == []
    assert corrected.corrected_fields == []


def test_list_ids_returns_every_saved_deal(tmp_path):
    store = DealStore(tmp_path)
    id_one = store.save(REPEDealProfile(deal_name="Deal One"))
    id_two = store.save(REPEDealProfile(deal_name="Deal Two"))

    assert sorted(store.list_ids()) == sorted([id_one, id_two])


def test_new_deal_starts_with_pending_review_status(tmp_path):
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(deal_name="Fixture Deal"))

    assert store.get(deal_id).review_status == "pending"


def test_set_review_status_approves_a_deal_and_persists_it(tmp_path):
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(deal_name="Fixture Deal"))

    reviewed = store.set_review_status(deal_id, "approved")

    assert reviewed.review_status == "approved"
    assert store.get(deal_id).review_status == "approved"


def test_set_review_status_can_reject_a_deal(tmp_path):
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(deal_name="Fixture Deal"))

    reviewed = store.set_review_status(deal_id, "rejected")

    assert reviewed.review_status == "rejected"


def test_set_review_status_rejects_pending_as_a_submitted_status(tmp_path):
    # "pending" is only ever the starting state a fresh extraction gets -
    # a reviewer can't submit it as their own verdict.
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(deal_name="Fixture Deal"))

    with pytest.raises(ValueError):
        store.set_review_status(deal_id, "pending")


def test_set_review_status_raises_for_an_unknown_id(tmp_path):
    store = DealStore(tmp_path)

    with pytest.raises(DealNotFoundError):
        store.set_review_status("does-not-exist", "approved")


def test_apply_corrections_on_review_status_does_not_mark_it_corrected(tmp_path):
    # review_status is bookkeeping (see set_review_status), not a "corrected
    # value" - PATCH-ing it directly shouldn't add it to corrected_fields.
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(deal_name="Fixture Deal"))

    corrected = store.apply_corrections(deal_id, {"review_status": "approved"})

    assert corrected.review_status == "approved"
    assert corrected.corrected_fields == []


def test_apply_corrections_on_review_feedback_does_not_mark_it_corrected(tmp_path):
    # Like review_status, review_feedback is the reviewer's own commentary,
    # not a corrected deal value - it shouldn't show up in corrected_fields.
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(deal_name="Fixture Deal"))

    corrected = store.apply_corrections(deal_id, {"review_feedback": "asking price looks wrong"})

    assert corrected.review_feedback == "asking price looks wrong"
    assert corrected.corrected_fields == []


def test_save_pages_and_get_pages_round_trip(tmp_path):
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(deal_name="Fixture Deal"))
    pages = [{"file_name": "fixture.pdf", "page_number": 1, "text": "Asking Price: $950,000."}]

    store.save_pages(deal_id, pages)

    assert store.get_pages(deal_id) == pages


def test_has_pages_is_false_until_save_pages_is_called(tmp_path):
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(deal_name="Fixture Deal"))

    assert store.has_pages(deal_id) is False

    store.save_pages(deal_id, [{"file_name": "fixture.pdf", "page_number": 1, "text": "hello"}])

    assert store.has_pages(deal_id) is True


def test_get_pages_raises_for_a_deal_with_no_saved_pages(tmp_path):
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(deal_name="Fixture Deal"))

    with pytest.raises(DealNotFoundError):
        store.get_pages(deal_id)


def test_list_ids_does_not_count_a_pages_file_as_a_separate_deal(tmp_path):
    store = DealStore(tmp_path)
    deal_id = store.save(REPEDealProfile(deal_name="Fixture Deal"))
    store.save_pages(deal_id, [{"file_name": "fixture.pdf", "page_number": 1, "text": "hello"}])

    assert store.list_ids() == [deal_id]

"""M6 Task 2: canonical ledger serialisation, SHA-256 hashing and chain verification."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest
from bcs_gs.ledger.canonical import (
    GENESIS_PREV,
    canonical_json,
    fmt_frac,
    fmt_pct,
    fmt_tco2e,
    record_hash,
)
from bcs_gs.ledger.chain import StoredRecord, verify

AT = "2026-10-13T00:00:00Z"


def make_record(index: int, previous_hash: str) -> StoredRecord:
    content = {
        "chain_index": index,
        "previous_hash": previous_hash,
        "record_id": f"BC-2026-{index + 1:05d}",
        "quantity": fmt_tco2e(Decimal("12.5")),
    }
    canonical = canonical_json(content)
    return StoredRecord(
        chain_index=index,
        canonical=canonical,
        hash=record_hash(canonical),
        previous_hash=previous_hash,
    )


def build_chain(n: int) -> list[StoredRecord]:
    records: list[StoredRecord] = []
    prev = GENESIS_PREV
    for i in range(n):
        rec = make_record(i, prev)
        records.append(rec)
        prev = rec.hash
    return records


def test_canonical_sorts_keys_and_has_no_whitespace():
    assert canonical_json({"b": "1.000", "a": 1, "c": {"z": True, "y": None}}) == (
        '{"a":1,"b":"1.000","c":{"y":null,"z":true}}'
    )


def test_floats_are_refused():
    with pytest.raises(TypeError):
        canonical_json({"q": 1.5})


def test_nested_floats_are_refused():
    with pytest.raises(TypeError):
        canonical_json({"outer": [{"inner": 0.25}]})


def test_decimal_objects_are_refused():
    # Callers pass fmt_* strings; a Decimal would hide the formatting choice.
    with pytest.raises(TypeError):
        canonical_json({"q": Decimal("1.5")})


def test_non_ascii_is_kept_unescaped():
    assert canonical_json({"name": "Kuala Selangor — zone"}) == '{"name":"Kuala Selangor — zone"}'


def test_known_sha256_vector():
    assert record_hash('{"a":1}') == "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"


def test_verify_detects_first_broken_link():
    chain = build_chain(3)  # helper building valid StoredRecords from contents
    assert verify(chain).intact is True
    bad = chain[:]
    bad[1] = replace(bad[1], canonical=bad[1].canonical.replace('"12.500"', '"99.500"'))
    v = verify(bad)
    assert v.intact is False and v.first_broken_index == 1


def test_genesis_previous_hash_is_64_zeros():
    assert build_chain(1)[0].previous_hash == "0" * 64


def test_empty_chain_is_intact_with_nothing_checked():
    v = verify([], at=AT)
    assert v.intact is True
    assert v.checked == 0
    assert v.first_broken_index is None
    assert v.at == AT


def test_intact_chain_reports_every_record_checked():
    v = verify(build_chain(4), at=AT)
    assert (v.intact, v.checked, v.first_broken_index) == (True, 4, None)


def test_index_gap_is_detected_at_the_missing_index():
    chain = build_chain(3)
    v = verify([chain[0], chain[2]], at=AT)
    assert v.intact is False and v.first_broken_index == 1


def test_out_of_order_indices_are_detected():
    chain = build_chain(3)
    v = verify([chain[0], chain[2], chain[1]], at=AT)
    assert v.intact is False and v.first_broken_index == 1


def test_non_canonical_text_is_detected_even_when_rehashed():
    chain = build_chain(3)
    loose = json.dumps(json.loads(chain[1].canonical), indent=1)  # parses, but not canonical
    bad = chain[:]
    bad[1] = replace(bad[1], canonical=loose, hash=record_hash(loose))
    v = verify(bad, at=AT)
    assert v.intact is False and v.first_broken_index == 1


def test_hash_mismatch_is_detected():
    chain = build_chain(3)
    bad = chain[:]
    bad[1] = replace(bad[1], hash="0" * 64)
    v = verify(bad, at=AT)
    assert v.intact is False and v.first_broken_index == 1


def test_previous_hash_mismatch_is_detected_at_the_linked_record():
    chain = build_chain(3)
    forged = make_record(2, "f" * 64)  # internally consistent, but does not link to record 1
    v = verify([chain[0], chain[1], forged], at=AT)
    assert v.intact is False and v.first_broken_index == 2


def test_fmt_helpers_use_fixed_places_and_round_half_up():
    assert fmt_tco2e(Decimal("12.5")) == "12.500"
    assert fmt_tco2e(Decimal("0.0005")) == "0.001"
    assert fmt_frac(Decimal("0.8")) == "0.8000"
    assert fmt_pct(Decimal("3.456")) == "3.46"


def test_fmt_helpers_refuse_floats():
    with pytest.raises(TypeError):
        fmt_tco2e(1.5)  # type: ignore[arg-type]


# ---- final review: crafted rows never raise, display columns are checked -----------------------------
def _crafted(chain: list[StoredRecord], index: int, canonical: str | bytes) -> list[StoredRecord]:
    bad = chain[:]
    bad[index] = replace(bad[index], canonical=canonical)
    return bad


@pytest.mark.parametrize(
    "canonical",
    [
        "[" * 200_000 + "]" * 200_000,  # deep nesting: json.loads raises RecursionError
        "not json at all",
        b"\xff\xfe{}",  # invalid UTF-8 bytes (read as a BLOB)
        b'{"chain_index":1,"x":"\xed\xa0\x80"}',  # a CESU-8 lone surrogate: invalid UTF-8
    ],
    ids=["deep-nesting", "unparseable", "invalid-utf8", "cesu8-surrogate"],
)
def test_crafted_canonical_is_a_broken_record_not_an_exception(canonical):
    v = verify(_crafted(build_chain(3), 1, canonical), at=AT)
    assert (v.intact, v.first_broken_index, v.checked) == (False, 1, 1)


def test_lone_surrogate_text_is_a_broken_record_not_an_exception():
    chain = build_chain(3)
    text = canonical_json({"chain_index": 1, "previous_hash": chain[0].hash, "x": "\ud800"})
    v = verify(_crafted(chain, 1, text), at=AT)  # its UTF-8 hash cannot even be computed
    assert (v.intact, v.first_broken_index) == (False, 1)


def test_valid_utf8_bytes_verify_like_text():
    chain = [replace(r, canonical=r.canonical.encode("utf-8")) for r in build_chain(3)]
    assert verify(chain, at=AT).intact is True


def test_content_index_or_previous_hash_disagreeing_with_the_row_is_broken():
    chain = build_chain(3)
    other = canonical_json({**json.loads(chain[1].canonical), "chain_index": 7})
    assert verify(_crafted(chain, 1, other), at=AT).first_broken_index == 1
    other = canonical_json({**json.loads(chain[1].canonical), "previous_hash": "a" * 64})
    assert verify(_crafted(chain, 1, other), at=AT).first_broken_index == 1


def _with_columns(rec: StoredRecord, **over: object) -> StoredRecord:
    content = json.loads(rec.canonical)
    cols = {"record_id": content["record_id"], "quantity_tco2e": None, "zone_ids": None, **over}
    return replace(rec, columns=cols)


def test_display_columns_must_equal_the_canonical_fields():
    chain = build_chain(3)
    ok = [_with_columns(r) for r in chain]
    assert verify(ok, at=AT).intact is True
    bad = ok[:]
    bad[1] = _with_columns(chain[1], record_id="BC-2026-99999")
    v = verify(bad, at=AT)
    assert (v.intact, v.first_broken_index, v.checked) == (False, 1, 1)
    bad[1] = _with_columns(chain[1], quantity_tco2e="99.000")  # the content has no such field
    assert verify(bad, at=AT).first_broken_index == 1


def test_json_display_columns_compare_by_value_not_key_order():
    content = {"chain_index": 0, "previous_hash": GENESIS_PREV, "zone_ids": ["KSL-B3"],
               "evidence": {"plan_id": "p", "captures": []}}  # fmt: skip
    canonical = canonical_json(content)
    rec = StoredRecord(0, canonical, record_hash(canonical), GENESIS_PREV,
                       columns={"zone_ids": '["KSL-B3"]', "evidence": b'{"captures":[],"plan_id":"p"}'})  # fmt: skip
    assert verify([rec], at=AT).intact is True
    for tampered in ('["KSL-B4"]', "not json", b"\xff"):
        v = verify([replace(rec, columns={"zone_ids": tampered})], at=AT)
        assert (v.intact, v.first_broken_index) == (False, 0)

import pytest

from typedmem import Source


def test_minimal_source():
    s = Source(document_id="doc1")
    assert s.document_id == "doc1"
    assert s.authority == 1.0
    assert s.chunk_id is None and s.span is None


def test_key_uses_document_chunk_span():
    a = Source(document_id="d", chunk_id="c", span=(0, 10))
    b = Source(document_id="d", chunk_id="c", span=(0, 10))
    c = Source(document_id="d", chunk_id="c", span=(0, 11))
    d = Source(document_id="d", chunk_id="other", span=(0, 10))
    assert a.key() == b.key()
    assert a.key() != c.key()
    assert a.key() != d.key()


def test_round_trip_via_dict():
    s = Source(document_id="d", chunk_id="c", span=(2, 8), authority=0.6, uri="https://x")
    d = s.to_dict()
    back = Source.from_dict(d)
    assert back == s


def test_from_any_lifts_string():
    s = Source.from_any("legacy")
    assert s is not None
    assert s.document_id == "legacy"


def test_from_any_passthrough_source():
    s = Source(document_id="d")
    assert Source.from_any(s) is s


def test_from_any_handles_none_and_empty():
    assert Source.from_any(None) is None
    assert Source.from_any("") is None


def test_empty_document_id_rejected():
    with pytest.raises(ValueError):
        Source(document_id="")


def test_bad_span_rejected():
    with pytest.raises(ValueError):
        Source(document_id="d", span=(1, 2, 3))  # type: ignore[arg-type]


def test_negative_authority_rejected():
    with pytest.raises(ValueError):
        Source(document_id="d", authority=-0.1)

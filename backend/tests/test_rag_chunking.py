"""Unit tests for deterministic, source-page-preserving RAG chunking."""

from backend.app.h9n.rag.chunking import build_page_chunks
from backend.app.h9n.rag.schemas import PageText


def test_chunking_preserves_page_numbers_and_never_crosses_pages():
    pages = [
        PageText(page_number=3, text="Alpha sentence. " * 18),
        PageText(page_number=4, text="Beta sentence. " * 18),
    ]

    chunks = build_page_chunks(pages, max_characters=80, overlap_characters=20)

    assert len(chunks) > 2
    assert {chunk.page_number for chunk in chunks} == {3, 4}
    assert all(len(chunk.content) <= 80 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(not ("Alpha" in chunk.content and "Beta" in chunk.content) for chunk in chunks)


def test_chunking_rejects_an_invalid_overlap():
    pages = [PageText(page_number=1, text="A valid page of deal text.")]

    try:
        build_page_chunks(pages, max_characters=50, overlap_characters=50)
    except ValueError as exc:
        assert "overlap" in str(exc).lower()
    else:
        raise AssertionError("Expected invalid overlap to be rejected.")

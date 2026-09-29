"""Deterministic, page-preserving chunking for the RAG embedding index."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import PageText


@dataclass(frozen=True)
class PreparedChunk:
    """A chunk ready for embeddings, with the original page still attached."""

    page_number: int
    chunk_index: int
    content: str


def _normalize_page_text(text: str) -> str:
    """Remove extraction noise without joining unrelated words or paragraphs."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _find_break_point(text: str, start: int, proposed_end: int, minimum_size: int) -> int:
    """Prefer a paragraph or sentence boundary near the configured chunk size."""
    if proposed_end >= len(text):
        return len(text)

    # A boundary too close to the start creates tiny chunks, so only consider
    # breaks in the final 40% of the proposed range.
    lower_bound = start + minimum_size
    candidates = [
        text.rfind("\n\n", lower_bound, proposed_end),
        text.rfind(". ", lower_bound, proposed_end),
        text.rfind("? ", lower_bound, proposed_end),
        text.rfind("! ", lower_bound, proposed_end),
        text.rfind(" ", lower_bound, proposed_end),
    ]
    boundary = max(candidates)
    if boundary < lower_bound:
        return proposed_end

    # Include the delimiter in this chunk. The following chunk's configured
    # overlap still retains enough nearby context for semantic retrieval.
    return boundary + 1


def build_page_chunks(
    pages: list[PageText], *, max_characters: int, overlap_characters: int
) -> list[PreparedChunk]:
    """Split pages into bounded chunks while preserving their source page number.

    Chunks never cross page boundaries. That makes each retrieval result easy
    to cite and avoids accidental evidence claims across two distinct pages.
    """
    if max_characters <= 0 or overlap_characters < 0 or overlap_characters >= max_characters:
        raise ValueError("Chunk size must be positive and overlap must be smaller than the chunk size.")

    chunks: list[PreparedChunk] = []
    next_chunk_index = 0

    for page in pages:
        text = _normalize_page_text(page.text)
        start = 0
        while start < len(text):
            proposed_end = min(start + max_characters, len(text))
            end = _find_break_point(
                text,
                start,
                proposed_end,
                minimum_size=max_characters * 3 // 5,
            )
            content = text[start:end].strip()
            if content:
                chunks.append(
                    PreparedChunk(
                        page_number=page.page_number,
                        chunk_index=next_chunk_index,
                        content=content,
                    )
                )
                next_chunk_index += 1

            if end >= len(text):
                break
            # Move forward by less than a full chunk to retain contextual
            # overlap, but always advance at least one character.
            start = max(start + 1, end - overlap_characters)

    return chunks

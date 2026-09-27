"""Split documents into retrievable chunks.

Chunking looks like a formatting detail and is actually the thing that decides
whether grounding works. Two failures matter:

**A chunk cut mid-claim cannot ground anything.** Fixed-width splitting
produces chunks ending "...reduced support workload by" — the number lands in
the next chunk. Retrieved alone, that text supports no claim, and an LLM asked
to write from it will either omit the fact or invent the missing figure. So
splits happen on paragraph, then sentence boundaries, and only fall back to a
hard cut for text with no boundaries at all.

**A claim spanning two chunks is lost by both.** "CityCare reduced workload by
35%." followed by "That saved 12 support hours a week." — split between them,
neither chunk carries the whole story. `OVERLAP_CHARS` repeats the tail of each
chunk at the head of the next so a claim near a boundary survives in at least
one.

Sizes are in characters, not tokens. A tokeniser would be more precise, but it
means shipping the model's vocabulary to compute a number used only to bound a
chunk — the ~4 chars/token approximation is close enough for a limit that is
itself a heuristic.
"""

import re

MAX_CHUNK_CHARS = 1200
"""~300 tokens. Small enough that a retrieved chunk is mostly relevant text
rather than padding, large enough to hold a complete claim with its context."""

MIN_CHUNK_CHARS = 120
"""Below this a chunk is a fragment — a heading, a stray line — that will
match queries on keyword coincidence and ground nothing. Merged forward
instead."""

OVERLAP_CHARS = 150

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
# Sentence end followed by whitespace and a capital/quote. Deliberately simple:
# an abbreviation like "Inc." occasionally splits early, which costs a little
# context, whereas a heavier NLP dependency costs an install.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")


def _split_long(text: str) -> list[str]:
    """Break a too-long block on sentence boundaries, then hard-cut if needed."""

    sentences = _SENTENCE_END.split(text)
    pieces: list[str] = []
    current = ""

    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= MAX_CHUNK_CHARS:
            current = candidate
            continue
        if current:
            pieces.append(current)
        # A single sentence longer than the limit (a table, a wall of text with
        # no punctuation) has no good split point; cut it rather than emit an
        # oversized chunk the embedding model would truncate silently.
        while len(sentence) > MAX_CHUNK_CHARS:
            pieces.append(sentence[:MAX_CHUNK_CHARS])
            sentence = sentence[MAX_CHUNK_CHARS:]
        current = sentence

    if current:
        pieces.append(current)
    return pieces


def _merge_small(pieces: list[str]) -> list[str]:
    """Fold fragments into their neighbour so no chunk is too small to ground."""

    merged: list[str] = []
    for piece in pieces:
        if merged and len(piece) < MIN_CHUNK_CHARS:
            candidate = f"{merged[-1]}\n\n{piece}"
            if len(candidate) <= MAX_CHUNK_CHARS:
                merged[-1] = candidate
                continue
        merged.append(piece)

    # A leading fragment has no previous neighbour, so fold it forward instead.
    if len(merged) > 1 and len(merged[0]) < MIN_CHUNK_CHARS:
        candidate = f"{merged[0]}\n\n{merged[1]}"
        if len(candidate) <= MAX_CHUNK_CHARS:
            merged = [candidate, *merged[2:]]
    return merged


def _add_overlap(pieces: list[str]) -> list[str]:
    """Repeat the tail of each chunk at the head of the next.

    Without this, a claim split across a boundary is absent from both chunks
    and cannot be retrieved by either.
    """

    if len(pieces) < 2 or OVERLAP_CHARS <= 0:
        return pieces

    overlapped = [pieces[0]]
    for previous, piece in zip(pieces[:-1], pieces[1:], strict=True):
        tail = previous[-OVERLAP_CHARS:]
        # Start the overlap at a word boundary; half a word helps nobody.
        space = tail.find(" ")
        if space != -1:
            tail = tail[space + 1 :]
        combined = f"{tail} {piece}".strip() if tail else piece
        # Hard cap. Text with no whitespace (a table, a base64 blob) yields a
        # full-length tail plus a full-length piece, and an oversized chunk is
        # silently truncated by the embedding model — losing the end of the
        # text with no error anywhere.
        overlapped.append(combined[: MAX_CHUNK_CHARS + OVERLAP_CHARS])
    return overlapped


def chunk_text(text: str) -> list[str]:
    """Split a document into overlapping, boundary-aligned chunks."""

    cleaned = (text or "").strip()
    if not cleaned:
        return []

    blocks: list[str] = []
    for paragraph in _PARAGRAPH_BREAK.split(cleaned):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= MAX_CHUNK_CHARS:
            blocks.append(paragraph)
        else:
            blocks.extend(_split_long(paragraph))

    return _add_overlap(_merge_small(blocks))


def estimate_tokens(text: str) -> int:
    """Rough token count for `KnowledgeChunk.token_count`. ~4 chars/token."""

    return max(1, len(text) // 4)

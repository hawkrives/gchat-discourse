# ABOUTME: Tests for thread title generation from Google Chat messages
# ABOUTME: Verifies title extraction, cleaning, and truncation logic

from __future__ import annotations

from gchat_mirror.exporters.discourse.thread_title import ThreadTitleGenerator


def test_thread_title_from_simple_message() -> None:
    """Test title generation from simple message."""
    generator = ThreadTitleGenerator()

    title = generator.generate_title(
        "Hey everyone, let's discuss the new feature", "Engineering", "thread123"
    )

    assert title == "Hey everyone, let's discuss the new feature"


def test_thread_title_first_sentence() -> None:
    """Test extracting first sentence."""
    generator = ThreadTitleGenerator()

    title = generator.generate_title(
        "This is the first sentence. This is the second.", "Engineering", "thread123"
    )

    assert title == "This is the first sentence."


def test_thread_title_first_line() -> None:
    """Test extracting first line."""
    generator = ThreadTitleGenerator()

    title = generator.generate_title(
        "First line\nSecond line\nThird line", "Engineering", "thread123"
    )

    assert title == "First line"


def test_thread_title_removes_markdown() -> None:
    """Test markdown removal."""
    generator = ThreadTitleGenerator()

    title = generator.generate_title(
        "This is **bold** and *italic* and `code`", "Engineering", "thread123"
    )

    assert title == "This is bold and italic and code"


def test_thread_title_removes_mentions() -> None:
    """Test mention removal."""
    generator = ThreadTitleGenerator()

    title = generator.generate_title(
        "<users/123456> can you review this?", "Engineering", "thread123"
    )

    assert title == "can you review this?"


def test_thread_title_removes_urls() -> None:
    """Test URL removal."""
    generator = ThreadTitleGenerator()

    title = generator.generate_title(
        "Check out https://example.com for more info", "Engineering", "thread123"
    )

    # Whitespace is normalized after URL removal
    assert title == "Check out for more info"


def test_thread_title_fallback_empty() -> None:
    """Test fallback for empty message."""
    generator = ThreadTitleGenerator()

    title = generator.generate_title("", "Engineering", "thread123")

    assert title == "Engineering - thread12"


def test_thread_title_fallback_none() -> None:
    """Test fallback for None message."""
    generator = ThreadTitleGenerator()

    title = generator.generate_title(None, "Engineering", "thread123")

    assert "Engineering" in title
    assert "thread12" in title


def test_thread_title_truncation() -> None:
    """Test title truncation at max length."""
    generator = ThreadTitleGenerator()

    long_text = "A" * 300
    title = generator.generate_title(long_text, "Engineering", "thread123")

    assert len(title) <= 255
    assert title.endswith("...")


def test_thread_title_question_mark() -> None:
    """Test first sentence with question mark."""
    generator = ThreadTitleGenerator()

    title = generator.generate_title(
        "What do you think? I want to know your opinion.", "Engineering", "thread123"
    )

    assert title == "What do you think?"


def test_thread_title_exclamation() -> None:
    """Test first sentence with exclamation."""
    generator = ThreadTitleGenerator()

    title = generator.generate_title("Great work! Keep it up.", "Engineering", "thread123")

    assert title == "Great work!"


def test_thread_title_normalizes_whitespace() -> None:
    """Test whitespace normalization."""
    generator = ThreadTitleGenerator()

    title = generator.generate_title(
        "This   has    too     much    whitespace", "Engineering", "thread123"
    )

    assert "    " not in title
    assert "  " not in title


def test_thread_title_removes_strikethrough() -> None:
    """Test strikethrough removal."""
    generator = ThreadTitleGenerator()

    title = generator.generate_title("This is ~~wrong~~ correct", "Engineering", "thread123")

    assert title == "This is wrong correct"


def test_thread_title_truncation_at_word_boundary() -> None:
    """Test that truncation happens at word boundaries."""
    generator = ThreadTitleGenerator()

    # Create a message that's just over the limit
    words = ["word"] * 60
    long_text = " ".join(words)

    title = generator.generate_title(long_text, "Engineering", "thread123")

    assert len(title) <= 255
    assert title.endswith("...")
    # Should not end with partial word before ellipsis
    assert not title[:-3].endswith("wor")

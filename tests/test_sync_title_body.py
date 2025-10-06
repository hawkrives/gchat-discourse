from gchat_discourse.sync_gchat_to_discourse import make_title_and_body


def test_title_from_first_non_empty_line():
    text = "\n\nTitle line\nThis is the body\nMore body"
    title, body = make_title_and_body(text)
    assert title == "Title line"
    assert body.startswith("Title line\n\n")
    assert "This is the body" in body


def test_title_truncation_long_first_line():
    long_line = "A" * 300
    text = long_line + "\nrest of message"
    title, body = make_title_and_body(text)
    assert len(title) == 255
    assert title.endswith("...")
    assert body.startswith(title + "\n\n")
    assert "rest of message" in body


def test_empty_text_returns_empty_title_and_body():
    title, body = make_title_and_body("")
    assert title == ""
    assert body == ""


def test_whitespace_only_lines():
    text = "\n   \n\t\n"
    title, body = make_title_and_body(text)
    # title should be empty string; body should contain the original whitespace prefixed by two newlines
    assert title == ""
    assert body == "\n\n" + text

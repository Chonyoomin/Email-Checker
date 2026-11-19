from email.message import EmailMessage

from bad_email_check.config import Settings
from bad_email_check.extraction import extract_eml, extract_paste, preview


def test_p2_f1_conflicting_href_destinations_preserved_browser_first():
    raw = (
        b"Subject: Example\nContent-Type: text/html\n\n"
        b'<a href="https://evil.example" href="https://good.example">Bank</a>'
    )
    evidence = extract_eml(raw, Settings(_env_file=None))
    assert [link.hostname for link in evidence.links] == ["evil.example", "good.example"]
    assert preview(evidence).status == "needs_review"
    assert any("Repeated link destinations" in warning for warning in evidence.warnings)


def mixed_message():
    message = EmailMessage()
    message["Subject"] = "Example"
    message.make_mixed()
    for text in ("abc", "def"):
        part = EmailMessage()
        part.set_type("text/plain")
        part.set_payload(text)
        message.attach(part)
    return message.as_bytes()


def test_p2_f2_separator_loss_is_not_silently_complete():
    evidence = extract_eml(mixed_message(), Settings(_env_file=None, max_body_characters=6))
    assert evidence.body_text == "abc"
    assert evidence.truncated
    assert preview(evidence).status == "needs_review"


def test_p2_f2_exact_separator_boundary_is_complete():
    evidence = extract_eml(mixed_message(), Settings(_env_file=None, max_body_characters=8))
    assert evidence.body_text == "abc\n\ndef"
    assert not evidence.truncated
    assert preview(evidence).status == "complete"


def test_p2_f3_headers_detected_after_transport_and_custom_headers():
    text = (
        "Received: from mx.example\nX-Custom: value\nFrom: sender@example.org\n"
        "Subject: Notice\n\nBody"
    )
    evidence = extract_paste(text, Settings(_env_file=None))
    assert evidence.sender == "sender@example.org"
    assert evidence.subject == "Notice"
    assert evidence.body_text == "Body"


def test_p2_f4_unsupported_transfer_encoding_cannot_be_complete():
    raw = b"Subject: Notice\nContent-Transfer-Encoding: rot13\n\nFrperg grkg"
    evidence = extract_eml(raw, Settings(_env_file=None))
    assert preview(evidence).status == "failed"
    assert any("Unsupported MIME transfer encoding" in warning for warning in evidence.warnings)
    assert "Frperg" not in evidence.body_text


def test_invalid_unicode_is_explicit_failed_input():
    evidence = extract_paste("bad\ud800text", Settings(_env_file=None))
    assert preview(evidence).status == "failed"
    assert any("Unicode" in warning for warning in evidence.warnings)


def test_unclosed_script_cannot_silently_hide_body():
    raw = b"Subject: Notice\nContent-Type: text/html\n\n<p>Visible</p><script>hidden rest"
    evidence = extract_eml(raw, Settings(_env_file=None))
    assert evidence.body_text == "Visible"
    assert preview(evidence).status == "needs_review"

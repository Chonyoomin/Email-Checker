from email.message import EmailMessage

import pytest

from bad_email_check.config import Settings
from bad_email_check.extraction import extract_eml, extract_paste, preview, with_context_coverage


@pytest.fixture
def settings():
    return Settings(_env_file=None, mode="test")


def eml(body="Example message", subtype="plain", charset="utf-8"):
    message = EmailMessage()
    message["From"] = "Support <support@example.org>"
    message["Reply-To"] = "help@example.org"
    message["Subject"] = "Example"
    message.set_content(body, subtype=subtype, charset=charset)
    return message


def test_body_only_paste_records_unknown_headers(settings):
    evidence = extract_paste("An ordinary message", settings)
    assert evidence.body_text == "An ordinary message"
    assert evidence.extraction_status == "complete"
    assert evidence.sender is None
    assert {"sender", "subject", "authentication"}.issubset(evidence.missing_fields)
    assert all("failed" not in warning for warning in evidence.warnings)


def test_paste_headers_and_encoded_subject(settings):
    text = "From: sender@example.org\nSubject: =?utf-8?b?SGVsbG8g4pyT?=\n\nMessage"
    evidence = extract_paste(text, settings)
    assert evidence.sender == "sender@example.org"
    assert evidence.subject == "Hello ✓"
    assert evidence.body_text == "Message"


@pytest.mark.parametrize("body", ["", "  ", "\x00bad"])
def test_empty_or_unsupported_paste_fails(settings, body):
    result = preview(extract_paste(body, settings))
    assert result.status == "failed"
    assert "score" not in result.model_dump()


def test_multipart_alternative_prefers_html_without_duplicate_body(settings):
    message = eml("Plain alternative that must not be duplicated")
    message.add_alternative(
        '<p>HTML alternative <a href="https://evil.example/login">Bank</a></p>', subtype="html"
    )
    evidence = extract_eml(message.as_bytes(), settings)
    assert evidence.extraction_status == "complete"
    assert "Plain alternative" not in evidence.body_text
    assert evidence.body_text.count("HTML alternative") == 1
    assert evidence.links[0].hostname == "evil.example"


def test_mixed_keeps_inline_text_but_never_attachment_body(settings):
    message = eml("Main message")
    extra = EmailMessage()
    extra.set_content("Additional inline text")
    message.make_mixed()
    message.attach(extra)
    message.add_attachment(
        b"PRIVATE_ATTACHMENT_CONTENT", maintype="application", subtype="pdf", filename="invoice.pdf"
    )
    evidence = extract_eml(message.as_bytes(), settings)
    assert "Main message" in evidence.body_text
    assert "Additional inline text" in evidence.body_text
    assert "PRIVATE_ATTACHMENT_CONTENT" not in evidence.body_text
    assert evidence.attachments[0].name == "invoice.pdf"
    assert evidence.attachments[0].content_type == "application/pdf"


@pytest.mark.parametrize("charset", ["utf-8", "iso-8859-1", "windows-1252"])
def test_common_charsets(settings, charset):
    evidence = extract_eml(eml("Café", charset=charset).as_bytes(), settings)
    assert "Café" in evidence.body_text
    assert evidence.extraction_status == "complete"


def test_invalid_charset_is_explicitly_incomplete(settings):
    raw = b'Subject: Example\nContent-Type: text/plain; charset="not-a-charset"\n\nExample'
    evidence = extract_eml(raw, settings)
    assert evidence.extraction_status == "incomplete"
    assert any("charset" in warning for warning in evidence.warnings)


def test_import_decodes_encoded_headers_and_attachment_filename(settings):
    message = eml("Message body")
    message.replace_header("From", "Équipe <sender@example.org>")
    message.replace_header("Subject", "Café ✓")
    message.add_attachment(
        b"not inspected", maintype="application", subtype="pdf", filename="résumé.pdf"
    )
    evidence = extract_eml(message.as_bytes(), settings)
    assert evidence.subject == "Café ✓"
    assert "Équipe" in evidence.sender
    assert evidence.attachments[0].name == "résumé.pdf"


def test_malformed_multipart_boundary_marks_recovery_incomplete(settings):
    raw = (
        b'Subject: Example\nContent-Type: multipart/mixed; boundary="part"\n\n'
        b"--part\nContent-Type: text/plain\n\nBody without closing boundary"
    )
    evidence = extract_eml(raw, settings)
    assert "Body without closing boundary" in evidence.body_text
    assert preview(evidence).status == "needs_review"


def test_attached_message_body_is_not_extracted(settings):
    message = eml("Outer message")
    message.add_attachment(eml("Private attached message"), filename="forwarded.eml")
    evidence = extract_eml(message.as_bytes(), settings)
    assert "Outer message" in evidence.body_text
    assert "Private attached message" not in evidence.body_text
    assert evidence.attachments[0].name == "forwarded.eml"


def test_html_links_malformed_urls_and_non_http_schemes(settings):
    html = (
        '<a href="https://attacker.example/account">paypal.com</a>'
        '<a href="javascript:alert(1)">Click</a><a href="http://[broken">Broken</a>'
    )
    evidence = extract_eml(eml(html, subtype="html").as_bytes(), settings)
    assert evidence.links[0].displayed_text == "paypal.com"
    assert evidence.links[0].hostname == "attacker.example"
    assert evidence.links[1].destination == "javascript:alert(1)"
    assert evidence.links[1].hostname is None
    assert evidence.links[2].hostname is None
    assert evidence.warnings


def test_html_scripts_images_and_entities_become_inert_evidence(settings):
    html = (
        "<p>Hello &amp; welcome</p><script>window.stolen = true</script>"
        '<img src="https://network-check.invalid/pixel" onerror="alert(1)" alt="Image text">'
        '<a href="https://evil.example/?q=&quot;x&quot;">&lt;b&gt;Bank&lt;/b&gt;</a>'
    )
    evidence = extract_eml(eml(html, subtype="html").as_bytes(), settings)
    assert "Hello & welcome" in evidence.body_text
    assert "window.stolen" not in evidence.body_text
    assert "Image text" in evidence.body_text
    assert "<b>Bank</b>" in evidence.body_text
    assert evidence.links[0].displayed_text == "<b>Bank</b>"
    assert "network-check.invalid" not in evidence.body_text


def test_imported_and_pasted_auth_claims_are_unverified(settings):
    message = eml()
    message["Authentication-Results"] = "mx.example.org; spf=pass; dkim=pass; dmarc=pass"
    message["Received-SPF"] = "pass"
    message["DKIM-Signature"] = "v=1; a=rsa-sha256; b=example"
    raw = message.as_bytes()
    imported = extract_eml(raw, settings)
    pasted = extract_paste(raw.decode(), settings)
    assert len(imported.authentication) == 3
    assert all(
        item.provenance == "imported_header" and not item.independently_verified
        for item in imported.authentication
    )
    assert all(item.provenance == "pasted_header" for item in pasted.authentication)


@pytest.mark.parametrize("raw", [b"", b"not a valid email", b"\x00", b"Subject: No body\n\n"])
def test_empty_malformed_import_is_clear_failure(settings, raw):
    assert preview(extract_eml(raw, settings)).status == "failed"


def test_stable_fingerprint_and_version(settings):
    a = extract_paste("First", settings)
    assert a.fingerprint == extract_paste("First", settings).fingerprint
    assert a.fingerprint != extract_paste("Second", settings).fingerprint
    assert a.parser_version == "2.0.0"


def test_upload_limit_checked_before_mime_parsing(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Parser must not run for oversized input")

    monkeypatch.setattr("bad_email_check.extraction.BytesParser", forbidden)
    evidence = extract_eml(b"x" * 11, Settings(_env_file=None, max_upload_bytes=10))
    assert evidence.extraction_status == "failed"
    assert any("byte limit" in warning for warning in evidence.warnings)


def test_decoded_body_limit_checked_before_html_parsing(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("HTML parser must not run for oversized decoded body")

    monkeypatch.setattr("bad_email_check.extraction.html_to_text", forbidden)
    evidence = extract_eml(
        eml("<p>too large</p>", subtype="html").as_bytes(),
        Settings(_env_file=None, max_body_characters=5),
    )
    assert preview(evidence).status == "failed"
    assert evidence.truncated
    assert any("character limit" in warning for warning in evidence.warnings)


def test_plain_body_and_link_limits_are_explicit(settings):
    body = extract_paste("x" * 100_001, settings)
    assert body.extraction_status == "failed"
    assert body.truncated
    links = " ".join(f"https://example.org/{index}" for index in range(201))
    evidence = extract_paste(links, settings)
    assert len(evidence.links) == 200
    assert evidence.truncated
    assert preview(evidence).status == "needs_review"


def test_html_link_limit_stops_with_warning():
    body = '<a href="https://example.org">Example</a>' * 3
    evidence = extract_eml(
        eml(body, subtype="html").as_bytes(), Settings(_env_file=None, max_links=2)
    )
    assert len(evidence.links) == 2
    assert preview(evidence).status == "needs_review"
    assert evidence.truncated


def test_context_counts_full_input_including_question_overhead(settings):
    evidence = extract_paste("body", settings)
    complete_input = "question and metadata plus body"
    calls = []

    def count(text):
        calls.append(text)
        return len(text.split())

    result = with_context_coverage(evidence, complete_input, count, 2)
    assert calls == [complete_input]
    assert result.context_limit_exceeded
    assert result.model_input_tokens == 5
    assert preview(result).status == "needs_review"
    assert evidence.model_input_tokens is None
    assert "score" not in preview(result).model_dump()


def test_context_exact_boundary_is_complete(settings):
    result = with_context_coverage(extract_paste("body", settings), "full input", lambda _: 2, 2)
    assert result.extraction_status == "complete"
    assert not result.context_limit_exceeded


@pytest.mark.parametrize("count", [-1, True, float("nan")])
def test_invalid_context_count_needs_review(settings, count):
    result = with_context_coverage(extract_paste("body", settings), "input", lambda _: count, 20)
    assert result.extraction_status == "incomplete"
    assert result.model_input_tokens is None


def test_tokenizer_failure_and_missing_context_never_claim_coverage(settings):
    evidence = extract_paste("body", settings)
    assert evidence.model_input_tokens is None
    assert "has not been checked" in preview(evidence).coverage_statement

    def unavailable(_):
        raise RuntimeError("Tokenizer missing")

    result = with_context_coverage(evidence, "full input", unavailable, 20)
    assert result.extraction_status == "incomplete"
    assert any("could not be measured" in warning for warning in result.warnings)

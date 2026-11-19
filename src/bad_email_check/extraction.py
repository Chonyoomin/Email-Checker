import hashlib
import re
from collections.abc import Callable
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

from .config import Settings
from .contracts import AttachmentInfo, AuthMetadata, EmailEvidence, EmailPreview, LinkInfo

PARSER_VERSION = "2.0.0"
HEADER_START = re.compile(r"^(from|to|subject|reply-to|date|mime-version|content-type):", re.I)
HEADER_LINE = re.compile(r"^([!-9;-~]+):")
PLAIN_URL = re.compile(r"\b(?:https?|ftp|mailto|javascript|data):[^\s<>\"']+", re.I)
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "section", "h1", "h2", "h3", "blockquote"}
AUTH_HEADERS = {
    "authentication-results",
    "received-spf",
    "dkim-signature",
    "arc-authentication-results",
}


class ExtractionLimit(ValueError):
    pass


class EvidenceBuilder:
    def __init__(self, raw: bytes, source: Literal["paste", "eml"], settings: Settings):
        self.settings = settings
        self.values = {
            "source": source,
            "body_text": "",
            "extraction_status": "complete",
            "parser_version": PARSER_VERSION,
            "fingerprint": hashlib.sha256(raw).hexdigest(),
        }
        self.links = []
        self.warnings = []
        self.missing = []
        self.truncated = False

    def warn(self, message: str, incomplete: bool = False):
        if message not in self.warnings and len(self.warnings) < 100:
            self.warnings.append(message)
        if incomplete:
            self.values["extraction_status"] = "incomplete"

    def bounded(self, value: str, limit: int) -> str:
        if len(value) > limit:
            self.truncated = True
            self.warn("An evidence field exceeds its supported size and was truncated.", True)
        return value[:limit]

    def link(self, text: str, destination: str):
        limit = min(self.settings.max_links, 200)
        if len(self.links) >= limit:
            self.truncated = True
            self.warn(
                "Link count exceeds the configured limit; some destinations are missing.", True
            )
            raise ExtractionLimit
        hostname = None
        try:
            parsed = urlsplit(destination)
            if any(c.isspace() or ord(c) < 32 for c in destination) or "\\" in destination:
                raise ValueError
            if parsed.scheme.lower() not in {"http", "https"} and not destination.startswith("//"):
                raise ValueError
            hostname = parsed.hostname
            if not hostname:
                raise ValueError
            _ = parsed.port
            hostname = hostname.encode("idna").decode("ascii").lower()
            if ":" in hostname:
                ip_address(hostname)
            elif not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", hostname):
                raise ValueError
            if len(hostname) > 253:
                raise ValueError
        except ValueError, UnicodeError:
            hostname = None
            self.warn("A link has an unsupported, relative, or malformed destination.")
        self.links.append(
            LinkInfo(
                displayed_text=self.bounded(text, 5_000),
                destination=self.bounded(destination, 8_192),
                hostname=hostname,
            )
        )

    def finish(self) -> EmailEvidence:
        if not self.values["body_text"].strip():
            self.values["extraction_status"] = "failed"
            if "body_text" not in self.missing:
                self.missing.append("body_text")
            self.warn("No readable message body was extracted.")
        for field in ("sender", "reply_to", "subject"):
            if not self.values.get(field) and field not in self.missing:
                self.missing.append(field)
        if not self.values.get("authentication"):
            self.missing.append("authentication")
            self.warn("Authentication evidence is unavailable; its status is unknown.")
        return EmailEvidence(
            **self.values,
            links=self.links,
            warnings=self.warnings,
            missing_fields=self.missing,
            truncated=self.truncated,
        )


class TextHTMLParser(HTMLParser):
    def __init__(self, builder: EvidenceBuilder):
        super().__init__(convert_charrefs=True)
        self.builder = builder
        self.text = []
        self.anchor = None
        self.anchor_text = []
        self.ignored = []

    def finish_anchor(self):
        if self.anchor is not None:
            for destination in self.anchor:
                self.builder.link("".join(self.anchor_text).strip(), destination)
        self.anchor = None
        self.anchor_text = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.ignored.append(tag)
            return
        if self.ignored:
            return
        values = dict(reversed(attrs))
        if tag in BLOCK_TAGS:
            self.text.append("\n")
        if tag == "a":
            self.finish_anchor()
            if "href" in values:
                destinations = [value or "" for name, value in attrs if name == "href"]
                self.anchor = list(dict.fromkeys(destinations))
                if len(destinations) > 1:
                    self.builder.warn(
                        "Repeated link destinations in one HTML element need review.", True
                    )
        if tag == "img" and values.get("alt"):
            self.handle_data(values["alt"])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag == "a":
            self.finish_anchor()
        if tag in BLOCK_TAGS:
            self.text.append("\n")

    def handle_data(self, data):
        if not self.ignored:
            self.text.append(data)
            if self.anchor is not None:
                self.anchor_text.append(data)


def html_to_text(body: str, builder: EvidenceBuilder) -> str:
    parser = TextHTMLParser(builder)
    try:
        parser.feed(body)
        parser.close()
        parser.finish_anchor()
    except ExtractionLimit:
        pass
    if parser.ignored:
        builder.warn("An unclosed HTML element may hide message text.", True)
    text = "".join(parser.text)
    text = re.sub(r"[^\S\n]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def plain_text(body: str, builder: EvidenceBuilder) -> str:
    try:
        for match in PLAIN_URL.finditer(body):
            destination = match.group().rstrip(".,;!?)")
            builder.link(destination, destination)
    except ExtractionLimit:
        pass
    return body.strip()


def decode_part(part, builder: EvidenceBuilder) -> str:
    encoding = str(part.get("Content-Transfer-Encoding", "7bit")).strip().lower()
    if encoding not in {"7bit", "8bit", "binary", "base64", "quoted-printable"}:
        builder.warn("Unsupported MIME transfer encoding; body decoding is incomplete.", True)
        return ""
    data = part.get_payload(decode=True)
    if not isinstance(data, bytes):
        builder.warn("A MIME body part could not be decoded.", True)
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return data.decode(charset, errors="strict")
    except LookupError, UnicodeError:
        builder.warn(
            "Unknown charset or invalid text encoding; replacement decoding was used.", True
        )
        return data.decode("utf-8", errors="replace")


def select_body_parts(part, builder: EvidenceBuilder, attachments: list, depth: int = 0):
    if depth > 30:
        builder.warn("MIME nesting exceeds the supported limit.", True)
        builder.truncated = True
        return []
    if (
        part.is_attachment()
        or part.get_filename() is not None
        or part.get_content_type() == "message/rfc822"
    ):
        if len(attachments) < 100:
            attachments.append(
                AttachmentInfo(
                    name=builder.bounded(part.get_filename() or "unnamed", 1_000),
                    content_type=part.get_content_type()[:255],
                )
            )
        else:
            builder.truncated = True
            builder.warn("Attachment metadata exceeds the supported count.", True)
        return []
    if part.is_multipart():
        children = list(part.iter_parts())
        if part.get_content_subtype() == "alternative":
            choices = [
                select_body_parts(child, builder, attachments, depth + 1) for child in children
            ]
            for content_type in ("text/html", "text/plain"):
                for choice in reversed(choices):
                    if any(item.get_content_type() == content_type for item in choice):
                        return choice
            return []
        if part.get_content_subtype() == "related":
            start = part.get_param("start")
            root = next(
                (child for child in children if child.get("Content-ID") == start),
                children[0] if children else None,
            )
            for child in children:
                if child is not root and (
                    child.is_attachment() or child.get_filename() is not None
                ):
                    select_body_parts(child, builder, attachments, depth + 1)
            return select_body_parts(root, builder, attachments, depth + 1) if root else []
        return [
            body
            for child in children
            for body in select_body_parts(child, builder, attachments, depth + 1)
        ]
    if part.get_content_type() in {"text/plain", "text/html"}:
        return [part]
    builder.warn("A non-text MIME part was not inspected.")
    return []


def parse_message(raw: bytes, builder: EvidenceBuilder):
    split = re.search(rb"\r?\n\r?\n", raw)
    if (split.start() if split else len(raw)) > 65_536:
        builder.values["extraction_status"] = "failed"
        builder.warn("Message headers exceed the supported size.")
        return
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
        parts = []
        for part in message.walk():
            parts.append(part)
            if len(parts) > 200:
                builder.truncated = True
                builder.warn("MIME part count exceeds the supported limit.", True)
                return
        if not message.keys():
            builder.values["extraction_status"] = "failed"
            builder.warn("The imported message has no recognizable headers.")
            return
        for field, name in (("sender", "From"), ("reply_to", "Reply-To"), ("subject", "Subject")):
            headers = message.get_all(name, [])
            if headers:
                builder.values[field] = builder.bounded(str(headers[0]), 1_000)
            if len(headers) > 1:
                builder.warn("Conflicting repeated message headers need review.", True)
        provenance = "imported_header" if builder.values["source"] == "eml" else "pasted_header"
        auth = []
        for name, value in message.items():
            if name.lower() in AUTH_HEADERS:
                if len(auth) == 100:
                    builder.truncated = True
                    builder.warn("Authentication header count exceeds the supported limit.", True)
                    break
                auth.append(
                    AuthMetadata(
                        name=name, value=builder.bounded(str(value), 8_192), provenance=provenance
                    )
                )
        builder.values["authentication"] = auth
        attachments = []
        bodies = select_body_parts(message, builder, attachments)
        builder.values["attachments"] = attachments
        chunks = []
        remaining = min(builder.settings.max_body_characters, 100_000)
        for part in bodies:
            body = decode_part(part, builder)
            needed = len(body) + (2 if chunks else 0)
            if needed > remaining:
                builder.truncated = True
                builder.warn("Decoded body exceeds the configured character limit.", True)
                break
            remaining -= needed
            chunks.append(
                html_to_text(body, builder)
                if part.get_content_type() == "text/html"
                else plain_text(body, builder)
            )
        builder.values["body_text"] = "\n\n".join(chunks)[
            : min(builder.settings.max_body_characters, 100_000)
        ]
        if any(
            part.defects or any(getattr(value, "defects", ()) for _, value in part.items())
            for part in parts
        ):
            builder.warn("Malformed MIME or headers were recovered; evidence needs review.", True)
    except ValueError, LookupError, RecursionError, UnicodeError:
        builder.values["extraction_status"] = "failed"
        builder.warn("The message could not be parsed within supported limits.")


def has_header_block(text: str) -> bool:
    lines = text.replace("\r\n", "\n").partition("\n\n")[0].splitlines()
    known = False
    seen_header = False
    for line in lines:
        if line[:1] in {" ", "\t"} and seen_header:
            continue
        match = HEADER_LINE.match(line)
        if not match:
            return False
        seen_header = True
        name = match.group(1).lower()
        known = (
            known
            or bool(HEADER_START.match(line))
            or name in AUTH_HEADERS
            or name
            in {
                "received",
                "return-path",
                "delivered-to",
                "message-id",
            }
        )
    return known


def extract_paste(text: str, settings: Settings) -> EmailEvidence:
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError:
        builder = EvidenceBuilder(text.encode("utf-8", errors="replace"), "paste", settings)
        builder.warn("Input contains unsupported Unicode characters.")
        return builder.finish()
    builder = EvidenceBuilder(raw, "paste", settings)
    if len(raw) > settings.max_upload_bytes:
        builder.warn("Input exceeds the configured byte limit.")
    elif not text.strip() or "\x00" in text:
        builder.warn("Input is empty or contains unsupported null characters.")
    elif has_header_block(text):
        parse_message(raw, builder)
    elif len(text) > min(settings.max_body_characters, 100_000):
        builder.truncated = True
        builder.warn("Body exceeds the configured character limit.", True)
    else:
        builder.values["body_text"] = plain_text(text.replace("\r\n", "\n"), builder)
    return builder.finish()


def extract_eml(raw: bytes, settings: Settings) -> EmailEvidence:
    builder = EvidenceBuilder(raw, "eml", settings)
    if len(raw) > settings.max_upload_bytes:
        builder.warn("Input exceeds the configured byte limit.")
    elif not raw.strip() or b"\x00" in raw:
        builder.warn("Input is empty or contains unsupported null characters.")
    else:
        parse_message(raw, builder)
    return builder.finish()


def preview(evidence: EmailEvidence) -> EmailPreview:
    return EmailPreview(
        evidence=evidence,
        status={
            "complete": "complete",
            "incomplete": "needs_review",
            "failed": "failed",
        }[evidence.extraction_status],
    )


def with_context_coverage(
    evidence: EmailEvidence,
    complete_model_input: str,
    count_tokens: Callable[[str], int],
    context_limit: int,
) -> EmailEvidence:
    if type(context_limit) is not int or context_limit < 1:
        raise ValueError("Context limit must be a positive integer")
    values = evidence.model_dump()
    try:
        count = count_tokens(complete_model_input)
        if type(count) is not int or count < 0:
            raise ValueError("Invalid token count")
    except Exception:
        values.update(
            model_input_tokens=None,
            context_limit_tokens=context_limit,
            context_limit_exceeded=False,
        )
        if values["extraction_status"] != "failed":
            values["extraction_status"] = "incomplete"
        values["warnings"] = (values["warnings"] + ["Model input coverage could not be measured."])[
            -100:
        ]
    else:
        values.update(
            model_input_tokens=count,
            context_limit_tokens=context_limit,
            context_limit_exceeded=count > context_limit,
        )
        if count > context_limit:
            if values["extraction_status"] != "failed":
                values["extraction_status"] = "incomplete"
            values["warnings"] = (
                values["warnings"] + ["Complete model input exceeds the context limit."]
            )[-100:]
    return EmailEvidence.model_validate(values)

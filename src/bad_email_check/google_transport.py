import socket
import ssl
import threading
import time
from http.client import HTTPSConnection
from urllib.parse import urlsplit

import httplib2


class GoogleResponseTooLarge(Exception):
    pass


class SingleAttemptHttp:
    def __init__(self, timeout, max_response_bytes=32 * 1024 * 1024):
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        parsed = urlsplit(uri)
        if (
            parsed.scheme != "https"
            or parsed.hostname
            not in {"gmail.googleapis.com", "www.googleapis.com", "oauth2.googleapis.com"}
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Unsupported Google transport endpoint")
        deadline = time.monotonic() + self.timeout
        connection = HTTPSConnection(
            parsed.hostname, timeout=self.timeout, context=ssl.create_default_context()
        )
        owned_socket = None
        expired = threading.Event()

        def abort():
            expired.set()
            current_socket = owned_socket if owned_socket is not None else connection.sock
            if current_socket is not None:
                try:
                    current_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        def remaining():
            value = deadline - time.monotonic()
            if expired.is_set() or value <= 0:
                raise TimeoutError
            return value

        timer = threading.Timer(max(0, deadline - time.monotonic()), abort)
        timer.daemon = True
        timer.start()
        try:
            connection.timeout = remaining()
            connection.connect()
            owned_socket = connection.sock
            owned_socket.settimeout(remaining())
            request_headers = {
                k: v for k, v in (headers or {}).items() if k.lower() != "accept-encoding"
            }
            request_headers["Accept-Encoding"] = "identity"
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request(method, path, body=body, headers=request_headers)
            owned_socket.settimeout(remaining())
            with connection.getresponse() as response:
                declared = response.getheader("content-length", "")
                if declared.isdigit() and int(declared) > self.max_response_bytes:
                    raise GoogleResponseTooLarge
                if response.getheader("content-encoding", "identity").lower() != "identity":
                    raise ValueError("Unsupported Google response encoding")
                content = bytearray()
                while True:
                    owned_socket.settimeout(remaining())
                    chunk = response.read1(min(65_536, self.max_response_bytes - len(content) + 1))
                    remaining()
                    if not chunk:
                        break
                    if len(content) + len(chunk) > self.max_response_bytes:
                        raise GoogleResponseTooLarge
                    content.extend(chunk)
                result = httplib2.Response(
                    {**dict(response.getheaders()), "status": str(response.status)}
                )
                result.reason = response.reason
                return result, bytes(content)
        except Exception:
            if expired.is_set():
                raise TimeoutError from None
            raise
        finally:
            timer.cancel()
            connection.close()

    def close(self):
        pass

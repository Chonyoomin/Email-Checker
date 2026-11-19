import hashlib
import sys
import threading

from keyring.errors import PasswordDeleteError


class CredentialStoreError(Exception):
    code = "credential_store_failed"


class CredentialStoreUnavailable(CredentialStoreError):
    code = "credential_store_unavailable"


def native_keyring():
    try:
        if sys.platform == "win32":
            from keyring.backends.Windows import WinVaultKeyring

            backend = WinVaultKeyring()
        elif sys.platform == "darwin":
            from keyring.backends.macOS import Keyring

            backend = Keyring()
        elif sys.platform.startswith("linux"):
            from keyring.backends.SecretService import Keyring

            backend = Keyring()
        else:
            raise RuntimeError
        if backend.priority <= 0:
            raise RuntimeError
        return backend
    except Exception:
        raise CredentialStoreUnavailable(
            "Protected OS credential storage is unavailable. "
            "Enable the native credential service; no file fallback is permitted."
        ) from None


def credential_service(account_scope: str) -> str:
    if not isinstance(account_scope, str) or not account_scope.strip() or len(account_scope) > 256:
        raise ValueError("A nonempty account scope of at most 256 characters is required.")
    try:
        digest = hashlib.sha256(account_scope.encode("utf-8")).hexdigest()
    except UnicodeError:
        raise ValueError("Account scope must contain valid Unicode text.") from None
    return f"bad-email-check.gmail.refresh.v1.{digest}"


def validate_refresh_token(token: str) -> str:
    if not isinstance(token, str) or not token.strip():
        raise ValueError("A nonempty refresh token within the credential size limit is required.")
    try:
        length = len(token.encode("utf-16-le"))
    except UnicodeError:
        raise ValueError("Refresh token must contain valid Unicode text.") from None
    if length > 2048:
        raise ValueError("Refresh token exceeds the protected credential size limit.")
    return token


class RefreshTokenStore:
    def __init__(self):
        self._backend = native_keyring()
        self._lock = threading.Lock()

    def save(self, account_scope: str, refresh_token: str) -> None:
        service = credential_service(account_scope)
        token = validate_refresh_token(refresh_token)
        with self._lock:
            try:
                self._backend.set_password(service, "refresh-token", token)
            except Exception:
                raise CredentialStoreError(
                    "Could not save the Gmail connection securely."
                ) from None

    def load(self, account_scope: str) -> str | None:
        service = credential_service(account_scope)
        with self._lock:
            try:
                token = self._backend.get_password(service, "refresh-token")
                return validate_refresh_token(token) if token is not None else None
            except Exception:
                raise CredentialStoreError(
                    "Could not read the protected Gmail connection."
                ) from None

    def delete(self, account_scope: str) -> None:
        service = credential_service(account_scope)
        with self._lock:
            try:
                if self._backend.get_password(service, "refresh-token") is None:
                    return
                try:
                    self._backend.delete_password(service, "refresh-token")
                except PasswordDeleteError:
                    if self._backend.get_password(service, "refresh-token") is not None:
                        raise
            except Exception:
                raise CredentialStoreError(
                    "Could not remove the protected Gmail connection."
                ) from None

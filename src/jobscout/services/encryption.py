"""Application-layer encryption for durable applicant documents."""

from __future__ import annotations

from collections.abc import Sequence

from cryptography.fernet import Fernet, InvalidToken

from jobscout.schemas.job import SourceDocument

_CIPHERTEXT_PREFIX = "enc:v1:"


class ProfileDocumentCipher:
    """Encrypts profile document text with the deployment's Fernet credentials key."""

    def __init__(self, credentials_key: str) -> None:
        if not credentials_key:
            raise ValueError("CREDENTIALS_KEY is required to store applicant data.")
        self._fernet = Fernet(credentials_key.encode())

    def encrypt(self, text: str) -> str:
        return _CIPHERTEXT_PREFIX + self._fernet.encrypt(text.encode()).decode()

    def decrypt(self, text: str) -> str:
        if not text.startswith(_CIPHERTEXT_PREFIX):
            return text
        try:
            return self._fernet.decrypt(text[len(_CIPHERTEXT_PREFIX) :].encode()).decode()
        except InvalidToken as error:
            raise ValueError(
                "Stored resume text cannot be decrypted with the current key."
            ) from error

    def encrypt_bytes(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt_bytes(self, ciphertext: bytes) -> bytes:
        return self._fernet.decrypt(ciphertext)


def encrypt_documents(
    cipher: ProfileDocumentCipher, documents: Sequence[SourceDocument]
) -> list[SourceDocument]:
    return [
        document.model_copy(update={"text": cipher.encrypt(document.text)})
        for document in documents
    ]


def decrypt_documents(
    cipher: ProfileDocumentCipher, documents: Sequence[SourceDocument]
) -> list[SourceDocument]:
    return [
        document.model_copy(update={"text": cipher.decrypt(document.text)})
        for document in documents
    ]

"""An in-memory stand-in for the private bucket deal PDFs are kept in (Milestone 2.3)."""


class FakeDealFileStore:
    def __init__(self, *, fail_upload: bool = False, fail_sign: bool = False):
        self.files: dict[str, bytes] = {}
        self.removed: list[str] = []
        self.signed: list[tuple[str, int]] = []
        self.fail_upload = fail_upload
        self.fail_sign = fail_sign

    def upload(self, path: str, content: bytes) -> None:
        if self.fail_upload:
            raise RuntimeError("storage detail that must not leak")
        self.files[path] = content

    def remove(self, path: str) -> None:
        self.removed.append(path)
        self.files.pop(path, None)

    def signed_url(self, path: str, expires_in: int) -> str:
        if self.fail_sign:
            raise RuntimeError("storage detail that must not leak")
        self.signed.append((path, expires_in))
        return f"https://storage.example/{path}?token=signed"

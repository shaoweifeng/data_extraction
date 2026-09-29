"""Stable machine-readable errors for screening import APIs and workers."""


class ScreeningImportError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}

    def as_dict(self) -> dict:
        payload = {'code': self.code, 'message': self.message}
        if self.details:
            payload['details'] = self.details
        return payload

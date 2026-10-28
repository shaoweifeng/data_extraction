"""Stable failures shared by private assets and safe network acquisition."""
class FulltextError(ValueError):
    def __init__(self, code, message, *, status=400):
        super().__init__(message)
        self.code, self.status = code, status

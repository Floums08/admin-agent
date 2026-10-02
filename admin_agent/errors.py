"""Expected errors safe to return to the local API client."""


class AppError(Exception):
    def __init__(self, message, status=400, code="invalid_request"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code

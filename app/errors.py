class PlayerError(Exception):
    def __init__(self, message, code="unavailable"):
        super().__init__(message)
        self.code = code

"""INDUSTRIA-X email service — stub. Email-based authentication has been removed.
All registration uses direct password-based login without email verification."""

class EmailError(Exception):
    pass


class EmailNotConfigured(EmailError):
    pass

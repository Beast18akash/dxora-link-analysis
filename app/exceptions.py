"""Domain-specific exceptions mapped to HTTP error responses."""


class LinkAnalysisError(Exception):
    """Base exception for expected application failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 500,
        error_code: str = "INTERNAL_ERROR",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


class InvalidURLError(LinkAnalysisError):
    """Raised when the submitted URL is malformed or uses a disallowed scheme."""

    def __init__(self, message: str = "Invalid website URL.") -> None:
        super().__init__(message, status_code=400, error_code="INVALID_URL")


class SSRFBlockedError(LinkAnalysisError):
    """Raised when a URL resolves to a private, local, or otherwise restricted address."""

    def __init__(
        self,
        message: str = "Access to the requested network address is blocked for security reasons.",
    ) -> None:
        super().__init__(message, status_code=403, error_code="SSRF_BLOCKED")


class WebsiteFetchError(LinkAnalysisError):
    """Raised when fetching the target website fails, times out, or violates size/type limits."""

    def __init__(
        self,
        message: str = "Unable to fetch the target website.",
        *,
        status_code: int = 502,
        error_code: str = "WEBSITE_FETCH_ERROR",
    ) -> None:
        super().__init__(message, status_code=status_code, error_code=error_code)


class ContentExtractionError(LinkAnalysisError):
    """Raised when meaningful readable content cannot be extracted from the fetched HTML."""

    def __init__(
        self,
        message: str = "Unable to extract meaningful content from the website.",
    ) -> None:
        super().__init__(message, status_code=422, error_code="CONTENT_EXTRACTION_ERROR")


class LLMServiceError(LinkAnalysisError):
    """Raised when the Gemini API is unconfigured, unavailable, or returns an invalid payload."""

    def __init__(
        self,
        message: str = "AI analysis service failed to process the request.",
        *,
        status_code: int = 502,
        error_code: str = "LLM_SERVICE_ERROR",
    ) -> None:
        super().__init__(message, status_code=status_code, error_code=error_code)

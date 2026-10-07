"""Retry transient source failures while preserving permanent HTTP rejections."""

import httpx
from tenacity import retry_if_exception


def transient_source_failure(error: BaseException) -> bool:
    return isinstance(error, (httpx.RequestError, TimeoutError, OSError)) or (
        isinstance(error, httpx.HTTPStatusError) and error.response.status_code >= 500
    )


source_retry = retry_if_exception(transient_source_failure)

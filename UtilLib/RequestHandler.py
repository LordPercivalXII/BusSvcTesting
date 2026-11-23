import json
import time
import urllib.request, urllib.parse
from urllib.error import HTTPError


RETRY_STATUS = {429, 500, 502, 503, 504}


class RequestError(Exception):
    def __init__(self, message, status=None, url=None):
        super().__init__(message)
        self.status = status   # HTTP code, or None for network/parse errors
        self.url = url         # no API key in here, since it goes in the header

class RequestHandler:
    def __init__(self, url, method="GET", headers=None, params=None, timeout=10, retries=2, backoff=1.0):
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, safe='$')}"
        self.url = url
        self.request = urllib.request.Request(url, method=method, headers=headers or {})
        self.timeout, self.retries, self.backoff = timeout, retries, backoff

    def urlopen(self):
        return urllib.request.urlopen(self.request, timeout=self.timeout)

    def get_json(self):
        last = None
        for attempt in range(self.retries + 1):
            try:
                with self.urlopen() as r:
                    return json.loads(r.read().decode("utf-8"))
            except HTTPError as e:                      # must come before OSError (it's a subclass)
                last = RequestError(f"HTTP {e.code} {e.reason}", status=e.code, url=self.url)
                if e.code not in RETRY_STATUS:          # 401/403/404 won't fix themselves
                    raise last from e
            except OSError as e:                        # URLError, timeouts, connection reset
                last = RequestError(f"Network error: {getattr(e, 'reason', e)}", url=self.url)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise RequestError(f"Bad response body: {e}", url=self.url) from e
            if attempt < self.retries:
                time.sleep(self.backoff * 2 ** attempt)  # 1s, 2s
        raise last

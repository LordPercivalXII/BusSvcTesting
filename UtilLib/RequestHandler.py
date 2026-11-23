import urllib.request


class RequestHandler:
    def __init__(self, url, method, headers=None):
        self.url = url
        self.method = method
        self.headers = headers
        self.request = urllib.request.Request(self.url, method=self.method, headers=self.headers or {})

    def urlopen(self):
        return urllib.request.urlopen(self.request, timeout=10)


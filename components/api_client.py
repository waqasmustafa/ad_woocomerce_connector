import logging
import socket
import urllib.error

import requests
from woocommerce import API

_logger = logging.getLogger(__name__)

RETRYABLE_HTTP_CODES = {502, 503, 504}
ERROR_HTTP_CODES = {400, 401, 403, 404, 405, 500}

class WooConnectionError(Exception):
    pass

class WooAPIError(Exception):
    pass

class WooStoreLocation:

    def __init__(self, url, consumer_key, consumer_secret, version="wc/v3"):
        self.url = url.rstrip("/")
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.version = version

    def __repr__(self):
        return f"<WooStoreLocation url={self.url} version={self.version}>"

class WooRESTClient:

    def __init__(self, location: WooStoreLocation):
        self._location = location
        self._api = None

    @property
    def api(self) -> API:
        if self._api is None:
            self._api = API(
                url=self._location.url,
                consumer_key=self._location.consumer_key,
                consumer_secret=self._location.consumer_secret,
                version=self._location.version,
                wp_api=True,
                timeout=30,
            )
        return self._api

    def get(self, endpoint: str, params: dict = None) -> dict:
        return self._call("get", endpoint, params=params or {})

    def post(self, endpoint: str, payload: dict) -> dict:
        return self._call("post", endpoint, payload=payload)

    def put(self, endpoint: str, payload: dict) -> dict:
        return self._call("put", endpoint, payload=payload)

    def delete(self, endpoint: str, params: dict = None) -> dict:
        return self._call("delete", endpoint, params=params or {})

    def get_all_pages(self, endpoint: str, params: dict = None, per_page: int = 100):
        params = dict(params or {})
        params.setdefault("per_page", per_page)
        page = params.pop("page", 1)

        while True:
            params["page"] = page
            result = self.get(endpoint, params)
            records = result.get("data", [])
            if not records:
                break
            yield records
            total = int(result.get("total", 0))
            fetched = (page - 1) * per_page + len(records)
            if fetched >= total:
                break
            page += 1

    def test_connection(self) -> bool:
        try:
            result = self.get("system_status")
            return bool(result.get("data"))
        except Exception as exc:
            _logger.warning("WooCommerce connection test failed: %s", exc)
            return False

    def _call(self, method: str, endpoint: str, params: dict = None, payload: dict = None) -> dict:
        try:
            if method == "get":
                response = self.api.get(endpoint, params=params)
            elif method == "post":
                response = self.api.post(endpoint, payload)
            elif method == "put":
                response = self.api.put(endpoint, payload)
            elif method == "delete":
                response = self.api.delete(endpoint, params=params)
            else:
                raise ValueError("Unsupported HTTP method: %s" % method)

            return self._parse_response(response)

        except (OSError, socket.gaierror, socket.timeout) as exc:
            raise WooConnectionError(
                "Network error while calling WooCommerce API: %s" % exc
            ) from exc
        except urllib.error.HTTPError as exc:
            if exc.code in RETRYABLE_HTTP_CODES:
                raise WooConnectionError(
                    "Temporary server error (HTTP %s): %s" % (exc.code, exc.reason)
                ) from exc
            raise

    def _parse_response(self, response: requests.Response) -> dict:
        status = response.status_code

        if status == 201:
            return {"data": response.json(), "total": 1}

        if status == 200:
            body = response.json()
            total = response.headers.get("X-WP-Total", None)
            total_pages = response.headers.get("X-WP-TotalPages", None)
            return {
                "data": body,
                "total": int(total) if total else (len(body) if isinstance(body, list) else 1),
                "total_pages": int(total_pages) if total_pages else 1,
            }

        if status == 204:
            return {"data": {}, "total": 0}

        if status in ERROR_HTTP_CODES:
            try:
                error_body = response.json()
            except Exception:
                error_body = response.text
            raise WooAPIError(
                "WooCommerce API error (HTTP %s): %s" % (status, error_body)
            )

        if status in RETRYABLE_HTTP_CODES:
            raise WooConnectionError(
                "Temporary WooCommerce server error (HTTP %s)" % status
            )

        response.raise_for_status()
        return {"data": response.json(), "total": 1}

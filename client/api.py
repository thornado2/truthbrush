from email.generator import Generator
from time import sleep
from typing import Any, Iterator, List
from loguru import logger
from requests.sessions import HTTPAdapter
from dateutil import parser as date_parse
import requests
from datetime import datetime, timezone

from urllib3 import Retry

BASE_URL = "https://truthsocial.com/api"
USER_AGENT = "TruthSocial/54 CFNetwork/1331 Darwin/21.4.0"


class Api:
    def __init__(self, auth_id):
        self.auth_id = auth_id
        self.ratelimit_max = 300
        self.ratelimit_remaining = None
        self.ratelimit_reset = None

    def _make_session(self):
        s = requests.Session()
        retries = Retry(
            total=10,
            backoff_factor=0.5,
            status_forcelist=[413, 429, 503, 403, 500, 503],
        )
        s.mount("http://", HTTPAdapter(max_retries=retries))
        s.mount("https://", HTTPAdapter(max_retries=retries))
        return s

    def _check_ratelimit(self, resp):
        if resp.headers.get("x-ratelimit-limit") is not None:
            self.ratelimit_max = int(resp.headers.get("x-ratelimit-limit"))
        if resp.headers.get("x-ratelimit-remaining") is not None:
            self.ratelimit_remaining = int(resp.headers.get("x-ratelimit-remaining"))
        if resp.headers.get("x-ratelimit-reset") is not None:
            self.ratelimit_reset = date_parse.parse(
                resp.headers.get("x-ratelimit-reset")
            )

        if (
            self.ratelimit_remaining is not None and self.ratelimit_remaining <= 50
        ):  # We do 50 to be safe; their tracking is a bit stochastic... it can jump down quickly
            now = datetime.utcnow().replace(tzinfo=timezone.utc)
            time_to_sleep = (
                self.ratelimit_reset.replace(tzinfo=timezone.utc) - now
            ).total_seconds()
            logger.warning(
                f"Approaching rate limit; sleeping for {time_to_sleep} seconds..."
            )
            sleep(time_to_sleep)

    def _get(self, url: str, params: dict = None) -> Any:
        resp = self._make_session().get(
            BASE_URL + url,
            params=params,
            headers={
                "authorization": "Bearer " + self.auth_id,
                "user-agent": USER_AGENT,
            },
        )

        # Will also sleep
        self._check_ratelimit(resp)

        return resp.json()

    def _get_paginated(self, url: str, params: dict = None) -> Any:
        next_link = BASE_URL + url
        while next_link is not None:
            resp = self._make_session().get(
                next_link,
                params=params,
                headers={
                    "authorization": "Bearer " + self.auth_id,
                    "user-agent": USER_AGENT,
                },
            )

            next_link = resp.links.get("next", {}).get("url")
            logger.info(f"Next: {next_link}, resp: {resp}, headers: {resp.headers}")
            yield resp.json()

            # Will also sleep
            self._check_ratelimit(resp)

    def lookup(self, user_handle: str = None) -> dict:
        """Lookup a user's information."""

        assert user_handle is not None
        return self._get("/v1/accounts/lookup", params=dict(acct=user_handle))

    def trending(self):
        """Return trending truths."""

        return self._get("/v1/truth/trending/truths")

    def tags(self):
        """Return trending tags."""

        return self._get("/v1/trends")

    def suggested(self, maximum: int = 50) -> dict:
        """Lookup a user's information."""

        return self._get(f"/v2/suggestions?limit={maximum}")

    def user_followers(
        self, user_handle: str = None, user_id: str = None, maximum: int = 1000
    ) -> Iterator[dict]:
        assert user_handle is not None or user_id is not None
        user_id = user_id if user_id is not None else self.lookup(user_handle)["id"]

        n_output = 0
        for followers_batch in self._get_paginated(f"/v1/accounts/{user_id}/followers"):
            for f in followers_batch:
                yield f
                n_output += 1
                if maximum is not None and n_output >= maximum:
                    return

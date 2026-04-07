"""Librus Synergia API client."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import (
    LIBRUS_API_BASE,
    LIBRUS_CLIENT_ID,
    LIBRUS_LOGIN_URL,
    LIBRUS_OAUTH_2FA_URL,
    LIBRUS_OAUTH_URL,
    TOKEN_LIFETIME,
)

_LOGGER = logging.getLogger(__name__)


class LibrusAuthError(Exception):
    """Authentication failed."""


class LibrusApiError(Exception):
    """API request failed."""


class LibrusAPI:
    """Librus Synergia API client using OAuth Authorization Code flow."""

    def __init__(self, username: str, password: str) -> None:
        """Initialize."""
        self._username = username
        self._password = password
        self._session: aiohttp.ClientSession | None = None
        self._token: str | None = None
        self._token_time: float = 0
        self._auth_lock = asyncio.Lock()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            # unsafe=True needed for cross-domain cookies between
            # api.librus.pl and synergia.librus.pl
            jar = aiohttp.CookieJar(unsafe=True)
            self._session = aiohttp.ClientSession(cookie_jar=jar)
        return self._session

    @property
    def _token_valid(self) -> bool:
        """Check if current token is still valid."""
        return (
            self._token is not None
            and (time.monotonic() - self._token_time) < TOKEN_LIFETIME
        )

    async def authenticate(self) -> str:
        """Perform full OAuth Authorization Code flow with retry.

        Uses a dedicated session for auth to avoid disrupting
        any in-flight API requests on the main session.
        Returns the oauth_token.
        Raises LibrusAuthError on failure.
        """
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                token = await self._do_authenticate()
                return token
            except LibrusAuthError as err:
                last_err = err
                _LOGGER.warning(
                    "Librus auth attempt %d/3 failed: %s", attempt + 1, err
                )
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))

        raise LibrusAuthError(
            f"Authentication failed after 3 attempts: {last_err}"
        )

    async def _do_authenticate(self) -> str:
        """Single authentication attempt using a dedicated session."""
        # Use a fresh dedicated session for auth — never touch self._session
        jar = aiohttp.CookieJar(unsafe=True)
        auth_session = aiohttp.ClientSession(cookie_jar=jar)

        try:
            # Step 1: Initialize session - GET login portal (follow redirects)
            _LOGGER.debug("Librus auth step 1: init session")
            async with auth_session.get(
                LIBRUS_LOGIN_URL,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                await resp.read()

            # Step 2: POST login credentials
            _LOGGER.debug("Librus auth step 2: login")
            login_url = f"{LIBRUS_OAUTH_URL}?client_id={LIBRUS_CLIENT_ID}"
            login_data = {
                "action": "login",
                "login": self._username,
                "pass": self._password,
            }
            headers = {"X-Requested-With": "XMLHttpRequest"}

            async with auth_session.post(
                login_url,
                data=login_data,
                headers=headers,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp_json = await resp.json(content_type=None)
                if resp_json.get("status") != "ok":
                    err_msg = resp_json.get("errors", {}).get(
                        "login", ["Unknown login error"]
                    )
                    raise LibrusAuthError(
                        f"Login failed: {err_msg}"
                    )

            # Step 3: Follow 2FA redirect to get oauth_token cookie
            _LOGGER.debug("Librus auth step 3: 2FA redirect")
            twofa_url = f"{LIBRUS_OAUTH_2FA_URL}?client_id={LIBRUS_CLIENT_ID}"
            async with auth_session.get(
                twofa_url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                await resp.read()

            # Extract oauth_token from cookies
            token = None
            for cookie in auth_session.cookie_jar:
                if cookie.key == "oauth_token":
                    token = cookie.value
                    break

            if not token:
                raise LibrusAuthError("No oauth_token cookie received after login")

            self._token = token
            self._token_time = time.monotonic()
            _LOGGER.debug("Librus auth successful, token obtained")
            return token

        except aiohttp.ClientError as err:
            raise LibrusAuthError(f"Connection error during auth: {err}") from err
        finally:
            await auth_session.close()

    async def _ensure_token(self) -> str:
        """Ensure we have a valid token, re-authenticate if needed.

        Uses a lock to prevent multiple concurrent re-authentications
        when parallel API calls all detect an expired token.
        """
        async with self._auth_lock:
            if not self._token_valid:
                await self.authenticate()
        assert self._token is not None
        return self._token

    async def api_get(self, endpoint: str) -> dict[str, Any]:
        """Make an authenticated GET request to the Librus API.

        Args:
            endpoint: API endpoint path (e.g., "Me", "Grades", "Subjects")

        Returns:
            Parsed JSON response as dict.
        """
        token = await self._ensure_token()
        session = await self._ensure_session()

        url = f"{LIBRUS_API_BASE}/{endpoint}"
        cookies = {"oauth_token": token}

        try:
            async with session.get(
                url,
                cookies=cookies,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 401:
                    # Token expired, re-authenticate and retry once
                    # Use lock so only one call triggers re-auth
                    _LOGGER.debug("Token expired for %s, re-authenticating", endpoint)
                    async with self._auth_lock:
                        if not self._token_valid or self._token == token:
                            self._token = None
                            await self.authenticate()
                    token = self._token
                    cookies = {"oauth_token": token}
                    session = await self._ensure_session()
                    async with session.get(
                        url,
                        cookies=cookies,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as retry_resp:
                        if retry_resp.status != 200:
                            raise LibrusApiError(
                                f"API error {retry_resp.status} for {endpoint}"
                            )
                        return await retry_resp.json(content_type=None)

                if resp.status != 200:
                    raise LibrusApiError(
                        f"API error {resp.status} for {endpoint}"
                    )
                return await resp.json(content_type=None)

        except aiohttp.ClientError as err:
            raise LibrusApiError(
                f"Connection error for {endpoint}: {err}"
            ) from err

    async def get_me(self) -> dict[str, Any]:
        """Get current user info."""
        return await self.api_get("Me")

    async def get_grades(self) -> dict[str, Any]:
        """Get all grades."""
        return await self.api_get("Grades")

    async def get_subjects(self) -> dict[str, Any]:
        """Get all subjects."""
        return await self.api_get("Subjects")

    async def get_grade_categories(self) -> dict[str, Any]:
        """Get grade categories."""
        return await self.api_get("Grades/Categories")

    async def get_grade_comments(self) -> dict[str, Any]:
        """Get grade comments."""
        return await self.api_get("Grades/Comments")

    async def get_classes(self) -> dict[str, Any]:
        """Get class info (including semester dates)."""
        return await self.api_get("Classes")

    async def get_lucky_number(self) -> dict[str, Any]:
        """Get today's lucky number."""
        return await self.api_get("LuckyNumbers")

    async def get_school_notices(self) -> dict[str, Any]:
        """Get school announcements."""
        return await self.api_get("SchoolNotices")

    async def get_behaviour_grades(self) -> dict[str, Any]:
        """Get behaviour/conduct grades."""
        return await self.api_get("BehaviourGrades")

    async def get_behaviour_types(self) -> dict[str, Any]:
        """Get behaviour grade type names."""
        return await self.api_get("BehaviourGrades/Types")

    async def get_parent_teacher_conferences(self) -> dict[str, Any]:
        """Get parent-teacher conferences (zebrania/wywiadówki)."""
        return await self.api_get("ParentTeacherConferences")

    async def get_homeworks(self) -> dict[str, Any]:
        """Get homework assignments (sprawdziany, kartkówki)."""
        return await self.api_get("HomeWorks")

    async def get_school_free_days(self) -> dict[str, Any]:
        """Get school free days."""
        return await self.api_get("SchoolFreeDays")

    async def get_substitutions(self) -> dict[str, Any]:
        """Get lesson substitutions and cancellations."""
        return await self.api_get("Calendars/Substitutions")

    async def get_attendances(self) -> dict[str, Any]:
        """Get attendances."""
        return await self.api_get("Attendances")

    async def get_timetables(self) -> dict[str, Any]:
        """Get timetables (current week only)."""
        return await self.api_get("Timetables")

    async def get_lessons(self) -> dict[str, Any]:
        """Get lesson definitions (subject+teacher+class mapping)."""
        return await self.api_get("Lessons")

    async def get_timetable_entries(self) -> dict[str, Any]:
        """Get permanent timetable entries (base schedule for the whole year)."""
        return await self.api_get("TimetableEntries")

    async def get_teachers(self) -> dict[str, Any]:
        """Get teachers/users."""
        return await self.api_get("Users")

    async def close(self) -> None:
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def test_connection(self) -> dict[str, Any]:
        """Test connection by authenticating and fetching Me endpoint.

        Returns Me data on success, raises on failure.
        """
        await self.authenticate()
        return await self.get_me()

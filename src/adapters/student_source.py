from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
from typing import Dict, Optional

import requests


@dataclass
class StudentProfile:
    display_name: str
    github_username: str = ""
    email: str = ""
    student_id: str = ""


class StudentSourceAdapter:
    """Adapter interface for student profile sources."""

    def get_profile(self, trello_member: dict) -> Optional[StudentProfile]:
        raise NotImplementedError()


class NullStudentSourceAdapter(StudentSourceAdapter):
    def get_profile(self, trello_member: dict) -> Optional[StudentProfile]:
        return None


class GoogleFormCsvStudentSourceAdapter(StudentSourceAdapter):
    """Loads student metadata from a published Google Form CSV endpoint.

    Expected columns (case-insensitive, any subset):
    - name / full_name / student_name
    - github / github_username
    - email
    - student_id / id
    """

    def __init__(self, csv_url: str, timeout: int = 30) -> None:
        self.csv_url = csv_url
        self.timeout = timeout
        self._name_index: Dict[str, StudentProfile] = {}
        self._email_index: Dict[str, StudentProfile] = {}
        self._loaded = False

    @staticmethod
    def _norm(value: str) -> str:
        return (value or "").strip().lower()

    def _pick(self, row: dict, *keys: str) -> str:
        lowered = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
        for k in keys:
            if lowered.get(k):
                return lowered[k]
        return ""

    def _load(self) -> None:
        if self._loaded:
            return

        resp = requests.get(self.csv_url, timeout=self.timeout)
        resp.raise_for_status()

        reader = csv.DictReader(StringIO(resp.text))
        for row in reader:
            display_name = self._pick(row, "name", "full_name", "student_name")
            if not display_name:
                continue
            profile = StudentProfile(
                display_name=display_name,
                github_username=self._pick(row, "github", "github_username"),
                email=self._pick(row, "email"),
                student_id=self._pick(row, "student_id", "id"),
            )

            self._name_index[self._norm(display_name)] = profile
            if profile.email:
                self._email_index[self._norm(profile.email)] = profile

        self._loaded = True

    def get_profile(self, trello_member: dict) -> Optional[StudentProfile]:
        self._load()

        full_name = self._norm((trello_member or {}).get("fullName", ""))
        username = self._norm((trello_member or {}).get("username", ""))

        if full_name and full_name in self._name_index:
            return self._name_index[full_name]
        if username and username in self._name_index:
            return self._name_index[username]

        # Trello member may have email in custom fields in future extensions.
        email = self._norm((trello_member or {}).get("email", ""))
        if email and email in self._email_index:
            return self._email_index[email]

        return None


def build_student_source(config: dict) -> StudentSourceAdapter:
    src_cfg = (config or {}).get("students", {})
    source_type = str(src_cfg.get("source", "none")).strip().lower()

    if source_type == "google_form_csv":
        csv_url = (src_cfg.get("google_form_csv_url") or "").strip()
        if csv_url:
            return GoogleFormCsvStudentSourceAdapter(csv_url=csv_url)

    return NullStudentSourceAdapter()

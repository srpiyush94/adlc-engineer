"""Shared state passed between ADLC Engineer graph nodes."""

from typing import TypedDict


class ADLCState(TypedDict):
    repo_path: str
    repo_display_name: str
    evidence: dict
    architecture_model: dict
    modernization: dict
    report_markdown: str

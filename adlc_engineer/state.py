"""Shared state passed between ADLC Engineer graph nodes."""

from typing import TypedDict


class ADLCState(TypedDict):
    repo_path: str
    repo_display_name: str
    evidence: dict
    architecture_model: dict
    modernization: dict
    report_markdown: str

    # --- Architecture Challenger (opt-in) ---
    run_challenger: bool
    security_review: dict
    scalability_review: dict
    cost_review: dict
    reliability_review: dict
    implementation_review: dict
    challenger_summary: dict

    # --- Spec-Driven Development (opt-in) ---
    requirement_text: str
    specification: dict

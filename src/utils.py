"""
General utility functions for text, markdown, and path processing.
"""

import os
from pathlib import Path


def clean_markdown_wrapper(md_content: str) -> str:
    """
    Strips surrounding markdown code blocks (e.g. ```markdown ... ```) if present.

    Args:
        md_content: The raw markdown content string to clean.

    Returns:
        The cleaned markdown content string without the code block wrapper.
    """
    cleaned = md_content.strip()
    lines = cleaned.splitlines()
    if len(lines) >= 2:
        first_line = lines[0].strip()
        last_line = lines[-1].strip()
        if (
            first_line.startswith("```markdown")
            or first_line.startswith("```md")
            or first_line == "```"
        ) and last_line == "```":
            return "\n".join(lines[1:-1]).strip()
    return cleaned


def validate_path(path: Path | str) -> Path:
    """
    Validates and canonicalizes file paths to prevent traversal and security risks.

    Args:
        path: The file path to validate.

    Returns:
        The validated Path object.

    Raises:
        ValueError: If path traversal or escape outside user home directory is detected.
    """
    base_dir = os.path.realpath(os.path.expanduser("~")) + os.sep
    canonical_path = os.path.realpath(os.path.abspath(path))
    if not canonical_path.startswith(base_dir):
        raise ValueError(f"Security Warning: Path traversal or escape detected: {path}")
    return Path(canonical_path)

"""Shared source media suffix groups."""

VIDEO_SUFFIXES = frozenset(
    {
        ".mp4",
        ".mkv",
        ".mov",
        ".avi",
        ".webm",
        ".flv",
        ".wmv",
        ".m4v",
    }
)
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"})
TEXT_SUFFIXES = frozenset({".txt", ".md", ".json"})
SUPPORTED_SOURCE_SUFFIXES = VIDEO_SUFFIXES | IMAGE_SUFFIXES | TEXT_SUFFIXES

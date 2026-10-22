"""Structured Image agent output, and the verified manifest the download step
(tools/image_download.py) produces from it."""

from pydantic import BaseModel, Field


class FoundImage(BaseModel):
    stop_name: str = Field(description="the itinerary stop this image is for")
    local_path: str = Field(description="e.g. 'images/berat-castle.jpg'")
    commons_filename: str = Field(
        description="Wikimedia Commons file title without the 'File:' prefix, "
        "e.g. 'Berat, Mangalem quarter, Albania.JPG'"
    )
    license: str = Field(description="e.g. 'CC BY-SA 4.0', 'Public domain'")
    author: str | None = Field(default=None, description="creator/Artist as shown on Commons")
    source_url: str | None = Field(default=None, description="the Commons file page URL")
    # Set only by the download step, never by the agent: bytes actually saved.
    size_bytes: int | None = None


class ImageResults(BaseModel):
    images: list[FoundImage]
    # Filled by the download step: stop -> reason, for images that were dropped.
    skipped: dict[str, str] = Field(default_factory=dict)

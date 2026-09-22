"""Structured Image agent output, used to fill in fetch-images.yml's file list."""

from pydantic import BaseModel, Field


class FoundImage(BaseModel):
    stop_name: str = Field(description="the itinerary stop this image is for")
    local_path: str = Field(description="e.g. 'images/berat-castle.jpg'")
    commons_filename: str = Field(
        description="Wikimedia Commons file title without the 'File:' prefix, "
        "URL-encoded the way the Commons API expects it, e.g. "
        "'Berat%2C_Mangalem_quarter%2C_Albania.JPG'"
    )
    license: str = Field(description="e.g. 'CC BY-SA 4.0', 'Public domain'")


class ImageResults(BaseModel):
    images: list[FoundImage]

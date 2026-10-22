"""Packing Planner output. The checklist HTML (checkboxes + localStorage) is
rendered from this by code (tools/packing_html.py), not by the Page Designer."""

from pydantic import BaseModel, Field


class PackingItem(BaseModel):
    name: str = Field(description="the item, in the trip's language, e.g. 'Lengva neperšlampama striukė'")
    note: str = Field(default="", description="short reason or quantity, e.g. 'lietus 2-3 dieną'")


class PackingCategory(BaseModel):
    name: str = Field(description="e.g. 'Drabužiai', 'Dokumentai', 'Vairavimui'")
    items: list[PackingItem]


class PackingList(BaseModel):
    baggage: str = Field(description="baggage assumption in plain words, e.g. 'Tik rankinis bagažas (~10 kg)'")
    tips: list[str] = Field(default_factory=list, description="a few packing tips, e.g. liquids rule")
    categories: list[PackingCategory]

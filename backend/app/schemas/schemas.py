from datetime import datetime
from pydantic import BaseModel


class StoreOut(BaseModel):
    id: int
    name: str
    model_config = {"from_attributes": True}


class RailOut(BaseModel):
    id: int
    store_id: int
    label: str
    length_cm: float
    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: int
    store_id: int
    ticket_code: str
    garment_name: str
    length_cm: float
    status: str
    due_at: datetime
    hung_at: datetime | None
    model_config = {"from_attributes": True}


class OverdueOrderOut(OrderOut):
    occupying: bool


class HangRequest(BaseModel):
    order_id: int
    rail_id: int | None = None


class PickupRequest(BaseModel):
    ticket_code: str


class ForceRemoveRequest(BaseModel):
    order_id: int


class ReleasedPlacement(BaseModel):
    rail_id: int
    rail_label: str
    start_cm: float
    end_cm: float


class ForceRemoveOut(BaseModel):
    order: OrderOut
    released: list[ReleasedPlacement]


class OccupancySeg(BaseModel):
    order_id: int
    ticket_code: str
    garment_name: str
    start_cm: float
    end_cm: float


class OccupancyOut(BaseModel):
    rail_id: int
    label: str
    length_cm: float
    segments: list[OccupancySeg]

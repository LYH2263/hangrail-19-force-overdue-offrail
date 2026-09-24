from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import HangRail, RailPlacement, Store, WorkOrder
from app.schemas.schemas import (
    ForceRemoveOut,
    ForceRemoveRequest,
    HangRequest,
    OccupancyOut,
    OccupancySeg,
    OrderOut,
    OverdueOrderOut,
    PickupRequest,
    RailOut,
    ReleasedPlacement,
    StoreOut,
)
from app.services.rail_engine import Segment, first_fit

api_router = APIRouter()


@api_router.get("/health")
def health():
    return {"status": "ok"}


@api_router.get("/stores", response_model=list[StoreOut])
def stores(db: Session = Depends(get_db)):
    return db.scalars(select(Store).order_by(Store.id)).all()


@api_router.get("/rails", response_model=list[RailOut])
def rails(db: Session = Depends(get_db)):
    return db.scalars(select(HangRail).order_by(HangRail.id)).all()


@api_router.get("/orders", response_model=list[OrderOut])
def orders(db: Session = Depends(get_db)):
    return db.scalars(select(WorkOrder).order_by(WorkOrder.id.desc())).all()


@api_router.get("/occupancy/{rail_id}", response_model=OccupancyOut)
def occupancy(rail_id: int, db: Session = Depends(get_db)):
    rail = db.get(HangRail, rail_id)
    if not rail:
        raise HTTPException(404, "挂杆不存在")
    placements = db.scalars(
        select(RailPlacement).where(RailPlacement.rail_id == rail_id, RailPlacement.active == 1)
    ).all()
    segs = []
    for p in placements:
        order = db.get(WorkOrder, p.order_id)
        if not order:
            continue
        segs.append(
            OccupancySeg(
                order_id=order.id,
                ticket_code=order.ticket_code,
                garment_name=order.garment_name,
                start_cm=p.start_cm,
                end_cm=p.end_cm,
            )
        )
    segs.sort(key=lambda s: s.start_cm)
    return OccupancyOut(rail_id=rail.id, label=rail.label, length_cm=rail.length_cm, segments=segs)


@api_router.post("/hang", response_model=OrderOut)
def hang(body: HangRequest, db: Session = Depends(get_db)):
    order = db.get(WorkOrder, body.order_id)
    if not order:
        raise HTTPException(404, "工单不存在")
    if order.status not in ("ready", "overdue"):
        raise HTTPException(400, "工单状态不可上杆")
    rail_q = select(HangRail).where(HangRail.store_id == order.store_id)
    if body.rail_id:
        rail_q = rail_q.where(HangRail.id == body.rail_id)
    rails = db.scalars(rail_q.order_by(HangRail.id)).all()
    if not rails:
        raise HTTPException(404, "无可用挂杆")

    for rail in rails:
        active = db.scalars(
            select(RailPlacement).where(RailPlacement.rail_id == rail.id, RailPlacement.active == 1)
        ).all()
        occupied = [Segment(p.start_cm, p.end_cm) for p in active]
        place = first_fit(rail.length_cm, occupied, order.length_cm)
        if place is None:
            continue
        db.add(
            RailPlacement(
                rail_id=rail.id,
                order_id=order.id,
                start_cm=place.start_cm,
                end_cm=place.end_cm,
            )
        )
        order.status = "hung"
        order.hung_at = datetime.utcnow()
        db.commit()
        db.refresh(order)
        return order

    raise HTTPException(409, "挂杆空间不足")


@api_router.post("/pickup", response_model=OrderOut)
def pickup(body: PickupRequest, db: Session = Depends(get_db)):
    order = db.scalar(select(WorkOrder).where(WorkOrder.ticket_code == body.ticket_code))
    if not order:
        raise HTTPException(404, "取件码无效")
    if order.status != "hung":
        raise HTTPException(400, "工单未在挂杆上")
    placements = db.scalars(
        select(RailPlacement).where(RailPlacement.order_id == order.id, RailPlacement.active == 1)
    ).all()
    for p in placements:
        p.active = 0
    order.status = "picked"
    db.commit()
    db.refresh(order)
    return order


@api_router.post("/overdue/scan", response_model=list[OrderOut])
def overdue_scan(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    hung = db.scalars(select(WorkOrder).where(WorkOrder.status == "hung")).all()
    marked = []
    for o in hung:
        if o.due_at < now:
            o.status = "overdue"
            marked.append(o)
    ready = db.scalars(select(WorkOrder).where(WorkOrder.status == "ready")).all()
    for o in ready:
        if o.due_at < now:
            o.status = "overdue"
            marked.append(o)
    db.commit()
    return marked


@api_router.get("/overdue", response_model=list[OverdueOrderOut])
def overdue_list(db: Session = Depends(get_db)):
    overdue = db.scalars(
        select(WorkOrder).where(WorkOrder.status == "overdue").order_by(WorkOrder.due_at)
    ).all()
    occupying_ids = set(
        db.scalars(select(RailPlacement.order_id).where(RailPlacement.active == 1)).all()
    )
    return [
        OverdueOrderOut(
            id=o.id,
            store_id=o.store_id,
            ticket_code=o.ticket_code,
            garment_name=o.garment_name,
            length_cm=o.length_cm,
            status=o.status,
            due_at=o.due_at,
            hung_at=o.hung_at,
            occupying=o.id in occupying_ids,
        )
        for o in overdue
    ]


@api_router.post("/overdue/force-remove", response_model=ForceRemoveOut)
def overdue_force_remove(body: ForceRemoveRequest, db: Session = Depends(get_db)):
    """店员清杆用的强制出杆：不验取件码，仅限已到期且仍占用挂杆的 hung/overdue 工单。"""
    order = db.get(WorkOrder, body.order_id)
    if not order:
        raise HTTPException(404, "工单不存在")
    if order.due_at >= datetime.utcnow():
        raise HTTPException(400, "工单未到期，不可强制出杆")
    if order.status not in ("hung", "overdue"):
        raise HTTPException(400, "工单状态不可强制出杆")
    placements = db.scalars(
        select(RailPlacement).where(RailPlacement.order_id == order.id, RailPlacement.active == 1)
    ).all()
    if not placements:
        raise HTTPException(400, "工单未占用挂杆，无需出杆")

    released: list[ReleasedPlacement] = []
    for p in placements:
        rail = db.get(HangRail, p.rail_id)
        released.append(
            ReleasedPlacement(
                rail_id=p.rail_id,
                rail_label=rail.label if rail else "",
                start_cm=p.start_cm,
                end_cm=p.end_cm,
            )
        )
        p.active = 0
    order.status = "overdue"
    db.commit()
    db.refresh(order)
    return ForceRemoveOut(order=order, released=released)

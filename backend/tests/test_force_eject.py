from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.database import Base, get_db
from app.models.models import HangRail, RailPlacement, Store, WorkOrder
from fastapi import FastAPI


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False)
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


@pytest.fixture()
def seeded(db_session):
    now = datetime.utcnow()
    store = Store(name="测试店")
    db_session.add(store)
    db_session.flush()
    rail = HangRail(store_id=store.id, label="A 杆", length_cm=200)
    db_session.add(rail)
    db_session.flush()
    # 已到期、仍占杆的 hung 工单（店员需清杆的对象）
    expired = WorkOrder(
        store_id=store.id,
        ticket_code="HR-EXPIRED",
        garment_name="风衣",
        length_cm=40,
        status="hung",
        due_at=now - timedelta(hours=12),
        hung_at=now - timedelta(days=3),
    )
    # 未到期 hung 工单（不得强制出杆）
    pending = WorkOrder(
        store_id=store.id,
        ticket_code="HR-PENDING",
        garment_name="大衣",
        length_cm=45,
        status="hung",
        due_at=now + timedelta(days=1),
        hung_at=now - timedelta(hours=5),
    )
    db_session.add_all([expired, pending])
    db_session.flush()
    db_session.add_all(
        [
            RailPlacement(rail_id=rail.id, order_id=expired.id, start_cm=0, end_cm=40),
            RailPlacement(rail_id=rail.id, order_id=pending.id, start_cm=40, end_cm=85),
        ]
    )
    db_session.commit()
    return {"rail_id": rail.id, "expired_id": expired.id, "pending_id": pending.id}


def test_force_eject_releases_active_and_marks_overdue(client, db_session, seeded):
    resp = client.post(f"/api/orders/{seeded['expired_id']}/force-eject")
    assert resp.status_code == 200
    data = resp.json()
    # 响应含被释放的杆编号与原起止区间，便于对账
    assert data["status"] == "overdue"
    assert data["rail_id"] == seeded["rail_id"]
    assert data["rail_label"] == "A 杆"
    assert data["start_cm"] == 0
    assert data["end_cm"] == 40

    order = db_session.get(WorkOrder, seeded["expired_id"])
    assert order.status == "overdue"
    placements = db_session.scalars(
        select(RailPlacement).where(RailPlacement.order_id == order.id)
    ).all()
    assert all(p.active == 0 for p in placements)
    assert not db_session.scalars(
        select(RailPlacement).where(
            RailPlacement.order_id == order.id, RailPlacement.active == 1
        )
    ).all()


def test_force_eject_rejects_unexpired_hung(client, seeded):
    resp = client.post(f"/api/orders/{seeded['pending_id']}/force-eject")
    assert resp.status_code == 400
    # 被拒绝后占位仍在
    resp_get = client.get("/api/occupancy/%d" % seeded["rail_id"])
    tickets = {s["ticket_code"] for s in resp_get.json()["segments"]}
    assert "HR-PENDING" in tickets


def test_force_eject_allows_overdue_still_occupying(client, db_session, seeded):
    """扫描后状态已 overdue 但仍占杆的工单，同样可强制出杆。"""
    oid = seeded["expired_id"]
    order = db_session.get(WorkOrder, oid)
    order.status = "overdue"
    db_session.commit()

    resp = client.post(f"/api/orders/{oid}/force-eject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "overdue"
    assert not db_session.scalars(
        select(RailPlacement).where(
            RailPlacement.order_id == oid, RailPlacement.active == 1
        )
    ).all()


def test_force_eject_distinct_from_pickup(client, seeded):
    """强制出杆按工单号走路径参数、不核验取件码；
    普通取件入口 /pickup 必须携带 ticket_code，空体应被校验拒绝。"""
    resp = client.post(f"/api/orders/{seeded['expired_id']}/force-eject", json={})
    assert resp.status_code == 200

    bad_pickup = client.post("/api/pickup", json={})
    assert bad_pickup.status_code == 422

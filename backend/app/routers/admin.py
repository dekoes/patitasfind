from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.dependencies import get_current_user, require_admin
from app.database import get_db
from app.models import (
    BotInteraction,
    Donation,
    Order,
    Dog,
    FosterHome,
    LostReport,
    Match,
    AdoptionApplication,
    Product,
    Refuge,
    User,
)
from app.schemas import (
    AdoptionApplicationOut,
    AdminStats,
    BotInteractionOut,
    DogOut,
    DogUpdateStatus,
    FosterHomeOut,
    LostReportAdminOut,
    AdminOrderOut,
    AdminDonationOut,
    MatchWithApplicationOut,
    ProductOut,
    RefugeOut,
    User as UserSchema,
    UserRoleUpdate,
)
from app.utils.notifications import create_notification

router = APIRouter(tags=["admin"])

VALID_ROLES = {"user", "refuge", "admin", "superadmin", "foster"}


class RejectPayload(BaseModel):
    reason: str | None = None


@router.get("/admin/stats", response_model=AdminStats)
def get_stats(
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total_users = db.query(User).count()
    total_dogs = db.query(Dog).count()
    pending_matches = db.query(Match).filter(Match.status == "pending_application").count()
    pending_refuges = db.query(Refuge).filter(Refuge.status == "pending").count()
    total_products = db.query(Product).count()
    total_lost_reports = db.query(LostReport).count()

    return AdminStats(
        total_users=total_users,
        total_dogs=total_dogs,
        pending_matches=pending_matches,
        pending_refuges=pending_refuges,
        total_products=total_products,
        total_lost_reports=total_lost_reports,
    )


@router.get("/admin/dashboard")
def get_dashboard(
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    last_7 = now - timedelta(days=7)
    last_30 = now - timedelta(days=30)

    total_users = db.query(User).count()
    total_dogs = db.query(Dog).count()
    pending_matches = db.query(Match).filter(Match.status == "pending_application").count()
    pending_refuges = db.query(Refuge).filter(Refuge.status == "pending").count()
    total_products = db.query(Product).count()
    total_lost_reports = db.query(LostReport).count()

    users_week = db.query(User).filter(User.created_at >= last_7).count()
    users_month = db.query(User).filter(User.created_at >= last_30).count()
    dogs_week = db.query(Dog).filter(Dog.created_at >= last_7).count()
    matches_week = db.query(Match).filter(Match.created_at >= last_7).count()

    by_city = (
        db.query(User.city, func.count(User.id).label("count"))
        .filter(User.city.isnot(None))
        .group_by(User.city)
        .order_by(func.count(User.id).desc())
        .limit(10)
        .all()
    )

    by_status = {
        "available": db.query(Dog).filter(Dog.status == "available").count(),
        "adopted": db.query(Dog).filter(Dog.status == "adopted").count(),
        "in_foster": db.query(Dog).filter(Dog.status == "in_foster").count(),
        "unavailable": db.query(Dog).filter(Dog.status == "unavailable").count(),
        "in_process": db.query(Dog).filter(Dog.status == "in_process").count(),
    }

    return {
        "totals": {
            "users": total_users,
            "dogs": total_dogs,
            "matches": db.query(Match).count(),
            "pending_matches": pending_matches,
            "pending_refuges": pending_refuges,
            "pending_foster_homes": db.query(FosterHome).filter(FosterHome.status == "pending").count(),
            "products": total_products,
            "lost_reports": total_lost_reports,
            "orders_paid": db.query(Order).filter(Order.status == "paid").count(),
            "donations_approved": db.query(Donation).filter(Donation.status == "approved").count(),
            "donations_total": float(
                db.query(func.coalesce(func.sum(Donation.amount), 0)).filter(Donation.status == "approved").scalar() or 0
            ),
        },
        "recent": {
            "users_week": users_week,
            "users_month": users_month,
            "dogs_week": dogs_week,
            "matches_week": matches_week,
        },
        "by_city": [{"city": c, "count": n} for c, n in by_city],
        "dogs_by_status": by_status,
    }


@router.get("/admin/users", response_model=list[UserSchema])
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return (
        db.query(User)
        .order_by(User.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.patch("/admin/users/{id}/role", response_model=UserSchema)
def update_user_role(
    id: int,
    payload: UserRoleUpdate,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rol inválido. Usa: {', '.join(sorted(VALID_ROLES))}.",
        )

    user = db.query(User).filter(User.id == id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese usuario.")

    user.role = payload.role
    db.commit()
    db.refresh(user)
    return user


@router.get("/admin/dogs", response_model=list[DogOut])
def list_all_dogs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    city: str | None = Query(None),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Dog)
    if status:
        query = query.filter(Dog.status == status)
    if city:
        query = query.filter(Dog.city.ilike(f"%{city}%"))
    return query.order_by(Dog.created_at.desc()).offset(skip).limit(limit).all()


@router.patch("/admin/dogs/{id}/status", response_model=DogOut)
def update_dog_status_admin(
    id: int,
    payload: DogUpdateStatus,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    dog = db.query(Dog).filter(Dog.id == id).first()
    if not dog:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese perrito.")
    from app.routers.dogs import VALID_STATUSES

    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Usa: {', '.join(sorted(VALID_STATUSES))}.")
    dog.status = payload.status
    db.commit()
    db.refresh(dog)
    return dog


@router.get("/admin/matches", response_model=list[MatchWithApplicationOut])
def list_all_matches(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Match).options(joinedload(Match.application))
    if status:
        query = query.filter(Match.status == status)
    return query.order_by(Match.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/admin/applications/{id}", response_model=AdoptionApplicationOut)
def get_application(
    id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    application = db.query(AdoptionApplication).filter(AdoptionApplication.id == id).first()
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese cuestionario.")
    return application


@router.get("/admin/refuges/pending", response_model=list[RefugeOut])
def list_pending_refuges(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return (
        db.query(Refuge)
        .filter(Refuge.status == "pending")
        .order_by(Refuge.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/admin/refuges/{id}/documents")
def get_refuge_documents(
    id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    refuge = db.query(Refuge).filter(Refuge.id == id).first()
    if not refuge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese refugio.")
    return {"documents": refuge.documents or []}


@router.post("/admin/refuges/{id}/approve", response_model=RefugeOut)
def approve_refuge(
    id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    refuge = db.query(Refuge).filter(Refuge.id == id).first()
    if not refuge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese refugio.")
    if refuge.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El refugio ya tiene estado: {refuge.status}.",
        )

    refuge.status = "approved"
    db.commit()
    db.refresh(refuge)

    create_notification(
        db,
        user_id=refuge.user_id,
        type="refuge_approved",
        title="Refugio aprobado",
        body=f"Tu refugio '{refuge.name}' fue aprobado. Ya puedes registrar rescates, adopciones y productos.",
    )

    return refuge


@router.post("/admin/refuges/{id}/reject", response_model=RefugeOut)
def reject_refuge(
    id: int,
    payload: RejectPayload | None = None,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    refuge = db.query(Refuge).filter(Refuge.id == id).first()
    if not refuge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese refugio.")
    if refuge.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El refugio ya tiene estado: {refuge.status}.",
        )

    refuge.status = "rejected"
    db.commit()
    db.refresh(refuge)

    reason_text = f" Motivo: {payload.reason}" if payload and payload.reason else ""
    create_notification(
        db,
        user_id=refuge.user_id,
        type="refuge_rejected",
        title="Refugio rechazado",
        body=f"Tu refugio '{refuge.name}' no fue aprobado.{reason_text}",
    )

    return refuge


@router.get("/admin/products", response_model=list[ProductOut])
def list_all_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return db.query(Product).order_by(Product.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/admin/lost-reports", response_model=list[LostReportAdminOut])
def list_lost_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    source: str | None = Query(None),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(LostReport)
    if status:
        query = query.filter(LostReport.status == status)
    if source:
        query = query.filter(LostReport.source == source)
    return query.order_by(LostReport.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/admin/bot-interactions", response_model=list[BotInteractionOut])
def list_bot_interactions(
    limit: int = Query(100, ge=1, le=500),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return db.query(BotInteraction).order_by(BotInteraction.updated_at.desc()).limit(limit).all()


@router.get("/admin/orders", response_model=list[AdminOrderOut])
def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Order)
    if status:
        query = query.filter(Order.status == status)
    return query.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/admin/donations", response_model=list[AdminDonationOut])
def list_donations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Donation)
    if status:
        query = query.filter(Donation.status == status)
    rows = query.order_by(Donation.created_at.desc()).offset(skip).limit(limit).all()
    out = []
    for d in rows:
        item = AdminDonationOut.model_validate(d).model_dump()
        item["refuge_name"] = d.refuge.name if d.refuge else None
        out.append(item)
    return out


@router.get("/admin/foster-homes/pending", response_model=list[FosterHomeOut])
def list_pending_foster_homes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return (
        db.query(FosterHome)
        .filter(FosterHome.status == "pending")
        .order_by(FosterHome.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.post("/admin/foster-homes/{id}/approve", response_model=FosterHomeOut)
def approve_foster_home(
    id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    foster_home = db.query(FosterHome).filter(FosterHome.id == id).first()
    if not foster_home:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos esa casa de paso.")
    if foster_home.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La casa de paso ya tiene estado: {foster_home.status}.",
        )

    foster_home.status = "approved"
    db.commit()
    db.refresh(foster_home)

    create_notification(
        db,
        user_id=foster_home.user_id,
        type="foster_home_approved",
        title="Casa de paso aprobada",
        body="Tu casa de paso fue aprobada. Los refugios ya pueden asignarte perros.",
    )

    return foster_home


@router.post("/admin/foster-homes/{id}/reject", response_model=FosterHomeOut)
def reject_foster_home(
    id: int,
    payload: RejectPayload | None = None,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    foster_home = db.query(FosterHome).filter(FosterHome.id == id).first()
    if not foster_home:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos esa casa de paso.")
    if foster_home.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La casa de paso ya tiene estado: {foster_home.status}.",
        )

    foster_home.status = "rejected"
    db.commit()
    db.refresh(foster_home)

    reason_text = f" Motivo: {payload.reason}" if payload and payload.reason else ""
    create_notification(
        db,
        user_id=foster_home.user_id,
        type="foster_home_rejected",
        title="Casa de paso rechazada",
        body=f"Tu casa de paso no fue aprobada.{reason_text}",
    )

    return foster_home

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_verified_user
from app.models import Order, User
from app.schemas import OrderCheckoutOut, OrderCreate, OrderOut
from app.services.payment_flow import create_order_checkout

router = APIRouter(tags=["orders"])


@router.post("/orders", response_model=OrderCheckoutOut, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    if not payload.shipping_address or not payload.shipping_address.strip():
        raise HTTPException(status_code=400, detail="Escribe la dirección de envío.")
    order, checkout_url, simulated = create_order_checkout(db, current_user, payload.items, payload.shipping_address.strip())
    out = OrderCheckoutOut.model_validate(order).model_dump()
    out.update({"checkout_url": checkout_url, "simulated": simulated})
    return out


@router.get("/orders", response_model=list[OrderOut])
def list_my_orders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Order).filter(Order.user_id == current_user.id).order_by(Order.created_at.desc()).all()


@router.get("/orders/{id}", response_model=OrderOut)
def get_order(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == id).first()
    if not order:
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    if order.user_id != current_user.id and current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="No tienes acceso a este pedido.")
    return order

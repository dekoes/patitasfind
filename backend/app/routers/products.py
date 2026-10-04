from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_verified_user
from app.models import Product, Refuge, User
from app.schemas import ProductCreate, ProductOut, ProductUpdate

router = APIRouter(tags=["products"])


def _get_approved_refuge_for_user(current_user: User, db: Session) -> Refuge:
    refuge = db.query(Refuge).filter(Refuge.user_id == current_user.id).first()
    if not refuge:
        raise HTTPException(status_code=403, detail="Necesitas registrar un refugio para vender productos.")
    if refuge.status != "approved":
        raise HTTPException(status_code=403, detail="Tu refugio todavía no está aprobado.")
    return refuge


def _owned_product(db: Session, product_id: int, user: User) -> Product:
    refuge = _get_approved_refuge_for_user(user, db)
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="No encontramos ese producto.")
    if product.refuge_id != refuge.id:
        raise HTTPException(status_code=403, detail="Este producto no pertenece a tu refugio.")
    return product


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    refuge = _get_approved_refuge_for_user(current_user, db)
    if payload.price <= 0:
        raise HTTPException(status_code=400, detail="El precio debe ser mayor a 0.")
    product = Product(
        refuge_id=refuge.id, name=payload.name, description=payload.description, price=payload.price,
        stock=payload.stock or 0, photos=payload.photos or [], is_active=True,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/products", response_model=list[ProductOut])
def list_products(refuge_id: int | None = Query(None), db: Session = Depends(get_db)):
    query = db.query(Product).filter(Product.is_active == True)  # noqa: E712
    if refuge_id:
        query = query.filter(Product.refuge_id == refuge_id)
    return query.order_by(Product.created_at.desc()).all()


@router.get("/products/{id}", response_model=ProductOut)
def get_product(id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == id, Product.is_active == True).first()  # noqa: E712
    if not product:
        raise HTTPException(status_code=404, detail="No encontramos ese producto.")
    return product


@router.patch("/products/{id}", response_model=ProductOut)
def update_product(id: int, payload: ProductUpdate, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    product = _owned_product(db, id, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "price" in data and (data["price"] is None or data["price"] <= 0):
        raise HTTPException(status_code=400, detail="El precio debe ser mayor a 0.")
    if "stock" in data and (data["stock"] is None or data["stock"] < 0):
        raise HTTPException(status_code=400, detail="El inventario no puede ser negativo.")
    for field, value in data.items():
        if field == "photos":
            value = value or []
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


@router.delete("/products/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(id: int, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    product = _owned_product(db, id, current_user)
    product.is_active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

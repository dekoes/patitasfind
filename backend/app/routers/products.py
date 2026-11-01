from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.dependencies import get_optional_user, get_verified_user
from app.models import Order, Product, Refuge, User
from app.schemas import ProductCreate, ProductOut, ProductUpdate
from app.services import legal_acceptance, ratelimit, reglas
from app.services.audit import record_admin_action
from app.services.payment_flow import ADMIN_ROLES, shop_guard

# Campos de contenido: al cambiar se vuelve a revisar la lista de productos prohibidos (services/reglas.py)
CONTENT_FIELDS = ("name", "description", "category", "warranty_text", "warranty_days", "photos", "is_perishable")

# Con SHOP_ENABLED=false todo /products responde 404 (salvo para admins)
router = APIRouter(tags=["products"], dependencies=[Depends(shop_guard)])


def _get_approved_refuge_for_user(current_user: User, db: Session) -> Refuge:
    refuge = db.query(Refuge).filter(Refuge.user_id == current_user.id).first()
    if not refuge:
        raise HTTPException(status_code=403, detail="Necesitas registrar un refugio para vender productos.")
    if refuge.status != "approved":
        raise HTTPException(status_code=403, detail="Tu refugio todavía no está aprobado.")
    return refuge


def _owned_product(db: Session, product_id: int, user: User) -> tuple[Product, bool]:
    """Producto del refugio del usuario. Los admins pueden editar cualquiera (devuelve as_admin=True)."""
    if user.role in ADMIN_ROLES:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="No encontramos ese producto.")
        own = db.query(Refuge.id).filter(Refuge.id == product.refuge_id, Refuge.user_id == user.id).first()
        return product, own is None
    refuge = _get_approved_refuge_for_user(user, db)
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="No encontramos ese producto.")
    if product.refuge_id != refuge.id:
        raise HTTPException(status_code=403, detail="Este producto no pertenece a tu refugio.")
    return product, False


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, request: Request, current_user: User = Depends(get_verified_user),
                   db: Session = Depends(get_db)):
    refuge = _get_approved_refuge_for_user(current_user, db)
    # Términos para vendedores (casilla separada al publicar el primer producto, o al cambiar de versión)
    legal_acceptance.accept_annex(db, current_user, "vendedor", payload.accepted_annex, request,
                                  context={"refuge_id": refuge.id})
    if payload.price <= 0:
        raise HTTPException(status_code=400, detail="El precio debe ser mayor a 0.")
    if payload.stock is not None and payload.stock < 0:
        raise HTTPException(status_code=400, detail="El inventario no puede ser negativo.")
    # Categoría y garantía obligatorias (consumidor-ecommerce-04 y 12)
    warranty = reglas.validate_product_fields(payload.category, payload.warranty_text, payload.warranty_days)
    product = Product(
        refuge_id=refuge.id, name=payload.name, description=payload.description, price=payload.price,
        stock=payload.stock or 0, photos=payload.photos or [], is_active=True,
        shipping_cost=payload.shipping_cost, ships_nationwide=payload.ships_nationwide,
        ships_states=payload.ships_states if not payload.ships_nationwide else None, handling_days=payload.handling_days,
        category=payload.category, warranty_text=warranty, warranty_days=payload.warranty_days,
        is_perishable=payload.is_perishable,
    )
    db.add(product)
    db.flush()
    # Lista de productos prohibidos: lo que coincide queda oculto y en revisión humana (productos-prohibidos §11)
    reason, terms = reglas.product_review(product.category, product.name, product.description, product.warranty_text)
    if reason:
        reglas.check_hold(db, "product", product, reason, terms, force=True)
    db.commit()
    db.refresh(product)
    return product


SELLER_IDENTITY_PER_HOUR = 60


@router.get("/products/sellers/{refuge_id}/identity")
def seller_identity(refuge_id: int, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    """Identidad y datos fiscales del refugio vendedor para «Revisa tu pedido» (terminos-tienda 1.3).

    Solo para quien puede comprar (cuenta verificada, como el checkout) y solo de un refugio que hoy vende algo
    (un producto activo, visible y con existencias) o al que esa persona ya le hizo un pedido: nombre o razón social,
    RFC, ciudad y si la venta causa IVA. Con límite por hora para que no se pueda recorrer el directorio.
    """
    ratelimit.check(f"seller-identity:{current_user.id}", SELLER_IDENTITY_PER_HOUR, 3600,
                    detail="Consultaste muchos vendedores seguidos. Inténtalo de nuevo en una hora.")
    not_found = HTTPException(status_code=404, detail="No encontramos ese refugio vendedor.")
    refuge = db.query(Refuge).filter(Refuge.id == refuge_id, Refuge.status == "approved").first()
    if not refuge:
        raise not_found
    sells = db.query(Product.id).filter(
        Product.refuge_id == refuge.id, Product.is_active == True, Product.is_hidden == False,  # noqa: E712
        Product.stock > 0).first()
    bought = sells or db.query(Order.id).filter(Order.refuge_id == refuge.id, Order.user_id == current_user.id).first()
    if not bought:
        raise not_found
    return reglas.seller_identity(refuge)


@router.get("/products", response_model=list[ProductOut])
def list_products(
    refuge_id: int | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = (db.query(Product).options(selectinload(Product.refuge))  # seller_payments_ready sin N+1
             .filter(Product.is_active == True, Product.is_hidden == False))  # noqa: E712
    if refuge_id:
        query = query.filter(Product.refuge_id == refuge_id)
    return query.order_by(Product.created_at.desc(), Product.id.desc()).offset(skip).limit(limit).all()


@router.get("/products/{id}", response_model=ProductOut)
def get_product(id: int, current_user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == id).first()
    visible = product is not None and product.is_active and not product.is_hidden
    if product is not None and not visible and current_user is not None:
        # El refugio dueño y los admins sí ven productos ocultos o desactivados
        visible = current_user.role in ADMIN_ROLES or db.query(Refuge.id).filter(
            Refuge.id == product.refuge_id, Refuge.user_id == current_user.id).first() is not None
    if not visible:
        raise HTTPException(status_code=404, detail="No encontramos ese producto.")
    return product


@router.patch("/products/{id}", response_model=ProductOut)
def update_product(id: int, payload: ProductUpdate, request: Request, current_user: User = Depends(get_verified_user),
                   db: Session = Depends(get_db)):
    product, as_admin = _owned_product(db, id, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "price" in data and (data["price"] is None or data["price"] <= 0):
        raise HTTPException(status_code=400, detail="El precio debe ser mayor a 0.")
    if "stock" in data and (data["stock"] is None or data["stock"] < 0):
        raise HTTPException(status_code=400, detail="El inventario no puede ser negativo.")
    for field in ("shipping_cost", "ships_nationwide", "handling_days", "is_perishable", "category"):
        if field in data and data[field] is None:
            data.pop(field)  # null no borra la configuración de envío ni la categoría
    content_changed = any(f in data for f in CONTENT_FIELDS)
    if content_changed:
        # Categoría y garantía obligatorias también al editar (los productos anteriores las completan aquí)
        days = data["warranty_days"] if "warranty_days" in data else product.warranty_days
        text = data["warranty_text"] if "warranty_text" in data else product.warranty_text
        data["warranty_text"] = reglas.validate_product_fields(data.get("category", product.category), text, days)
    nationwide = data.get("ships_nationwide", product.ships_nationwide)
    states = data["ships_states"] if "ships_states" in data else product.ships_states
    if not nationwide and not states:
        raise HTTPException(status_code=400, detail="Elige al menos un estado al que envías o marca «Envío a todo el país».")
    if nationwide:
        data["ships_states"] = None
    for field, value in data.items():
        if field == "photos":
            value = value or []
        if field == "is_active" and value and reglas.review_status(product):
            continue  # reactivar no saca un producto de revisión: sigue oculto hasta que el equipo decida
        setattr(product, field, value)
    if as_admin:
        record_admin_action(db, current_user, "product_update", "product", product.id,
                            details={"fields": sorted(data)}, request=request)
    elif content_changed:
        reason, terms = reglas.product_review(product.category, product.name, product.description,
                                              product.warranty_text)
        reglas.check_hold(db, "product", product, reason, terms)
    db.commit()
    db.refresh(product)
    return product


@router.delete("/products/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(id: int, request: Request, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    product, as_admin = _owned_product(db, id, current_user)
    product.is_active = False
    if as_admin:
        record_admin_action(db, current_user, "product_deactivate", "product", product.id, request=request)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

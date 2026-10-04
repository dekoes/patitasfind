import random
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta

from app.config import settings
from app.database import SessionLocal
from app.main import run_startup_migrations
from app.models import (
    User, Dog, DogPass, Match, AdoptionApplication, Conversation, Message,
    Refuge, Product, LostReport, FosterHome, Notification, Reminder,
    Order, OrderItem, PointLog, Donation, BotInteraction,
)
from app.auth import get_password_hash
from app.services import images
from app.services.vision import signature_for_urls

UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

NAMES = [
    ("Lucía Martínez", "lucia@patitas.com", "+525511111111"),
    ("Carlos Ruiz", "carlos@patitas.com", "+525522222222"),
    ("Ana Gómez", "ana@patitas.com", "+525533333333"),
    ("Pedro Hernández", "pedro@patitas.com", "+525544444444"),
    ("María López", "maria@patitas.com", "+525555555555"),
    ("Jorge Sánchez", "jorge@patitas.com", "+525566666666"),
    ("Diana Flores", "diana@patitas.com", "+525577777777"),
    ("Roberto Torres", "roberto@patitas.com", "+525588888888"),
    ("Sofía Vargas", "sofia@patitas.com", "+525599999999"),
    ("Andrés Castillo", "andres@patitas.com", "+525500000000"),
]

CITIES = [
    ("Ciudad de México", "México", 19.4326, -99.1332),
    ("Guadalajara", "México", 20.6597, -103.3496),
    ("Monterrey", "México", 25.6866, -100.3161),
    ("Puebla", "México", 19.0414, -98.2063),
    ("Tijuana", "México", 32.5149, -117.0382),
]

BREEDS = ["Mestizo", "Labrador", "French Poodle", "Chihuahua", "Golden Retriever", "Bulldog", "Beagle", "Pastor Alemán"]
SIZES = ["Pequeño", "Mediano", "Grande"]
COLORS = ["Café", "Negro", "Blanco", "Gris", "Manchado", "Dorado", "Tricolor"]

DOG_TEMPLATES = [
    ("Canela", "Canela es juguetona, le encanta correr en el parque y es muy cariñosa con los niños."),
    ("Rocky", "Rocky es guardián y leal. Necesita espacio y paseos diarios."),
    ("Luna", "Luna es tranquila, perfecta para departamento. Le gusta dormir todo el día."),
    ("Max", "Max es enérgico y sociable. Se lleva bien con otros perros."),
    ("Mía", "Mía es una consentida que busca un hogar donde la apapachen mucho."),
    ("Toby", "Toby es curioso y cariñoso. Ya está esterilizado y vacunado."),
    ("Bella", "Bella fue rescatada de la calle. Ahora confía y busca una familia."),
    ("Thor", "Thor es grande pero de corazón noble. Ideal para casa con jardín."),
    ("Coco", "Coco es pequeño, travieso y muy inteligente. Aprende rápido."),
    ("Nala", "Nala es dulce y protectora. Le encanta jugar con pelotas."),
    ("Bruno", "Bruno es tranquilo y obediente. Buen compañero para adultos mayores."),
    ("Daisy", "Daisy es alegre y sociable. Le encanta la playa."),
    ("Zeus", "Zeus es fuerte y cariñoso. Necesita una familia con experiencia."),
    ("Lola", "Lola es tierna y tranquila. Perfecta como primera mascota."),
    ("Simba", "Simba es valiente y juguetón. Siempre quiere estar acompañado."),
]


import json

def fetch_random_dog_urls(count: int) -> list[str]:
    try:
        url = f"https://dog.ceo/api/breeds/image/random/{count}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("message", [])
    except Exception as e:
        print(f"No se pudo obtener URLs de dog.ceo: {e}")
        return []


def download_dog_photo(url: str) -> str:
    """Descarga y procesa (Pillow: sin EXIF, máx. 1600 px, miniatura). Devuelve "" si falla."""
    try:
        return images.download_and_store(url) or ""
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo descargar foto {url}: {e}")
        return ""


def local_photos(limit: int = 40) -> list[str]:
    """Fotos ya existentes en la carpeta de uploads (para sembrar sin internet)."""
    files = [p for p in UPLOAD_DIR.glob("*.jpg") if not p.name.endswith("_thumb.jpg")]
    random.shuffle(files)
    return [f"/uploads/{p.name}" for p in files[:limit]]


def seed():
    run_startup_migrations()
    db = SessionLocal()
    try:
        # Limpiar datos previos de prueba (se conservan usuarios que no sean @patitas.com)
        db.query(Message).delete()
        db.query(Conversation).delete()
        db.query(AdoptionApplication).delete()
        db.query(Reminder).delete()
        db.query(Match).delete()
        db.query(DogPass).delete()
        db.query(OrderItem).delete()
        db.query(Order).delete()
        db.query(Donation).delete()
        db.query(Product).delete()
        db.query(PointLog).delete()
        db.query(LostReport).delete()
        db.query(Dog).delete()
        db.query(FosterHome).delete()
        db.query(Refuge).delete()
        db.query(Notification).delete()
        db.query(BotInteraction).delete()
        db.query(User).filter(User.email.like("%@patitas.com")).delete(synchronize_session=False)
        db.commit()

        print("Creando usuarios...")
        users = []
        for i, (name, email, phone) in enumerate(NAMES):
            city, country, lat, lon = random.choice(CITIES)
            u = User(
                email=email,
                full_name=name,
                phone=phone,
                city=city,
                country=country,
                latitude=lat + random.uniform(-0.05, 0.05),
                longitude=lon + random.uniform(-0.05, 0.05),
                phone_verified=True,
                role="user",
                is_active=True,
                created_at=datetime.utcnow() - timedelta(days=random.randint(1, 60)),
                hashed_password=get_password_hash("Patitas123!"),
            )
            db.add(u)
            users.append(u)
        db.commit()
        for u in users:
            db.refresh(u)

        print("Descargando fotos de perros...")
        dog_urls = fetch_random_dog_urls(40)
        photos = [download_dog_photo(u) for u in dog_urls]
        photos = [p for p in photos if p]
        if len(photos) < 15:
            # Sin internet: reutilizamos fotos que ya estén en uploads
            photos += local_photos(40 - len(photos))
        if not photos:
            print("Aviso: no hay fotos disponibles; los perros se crearán sin foto.")

        print("Creando perros en adopcion...")
        dogs = []
        for i, (dname, desc) in enumerate(DOG_TEMPLATES):
            owner = random.choice(users)
            city, country, base_lat, base_lon = random.choice(CITIES)
            lat = base_lat + random.uniform(-0.08, 0.08)
            lon = base_lon + random.uniform(-0.08, 0.08)
            dog_photos = random.sample(photos, k=min(random.randint(2, 4), len(photos))) if photos else []
            d = Dog(
                owner_id=owner.id,
                name=dname,
                breed=random.choice(BREEDS),
                age_years=random.choice([0, 1, 2, 3, 4]),
                age_months=random.choice([0, 2, 4, 6, 8]),
                size=random.choice(SIZES),
                color=random.choice(COLORS),
                description=desc,
                city=city,
                country=country,
                latitude=lat,
                longitude=lon,
                photos=dog_photos,
                status="available",
                created_at=datetime.utcnow() - timedelta(days=random.randint(0, 30)),
            )
            db.add(d)
            dogs.append(d)
        db.commit()
        for d in dogs:
            db.refresh(d)

        print("Creando refugios...")
        refuges = []
        for i in range(3):
            owner = users[i]
            city, country, lat, lon = random.choice(CITIES)
            r = Refuge(
                user_id=owner.id,
                name=f"Refugio {['Esperanza', 'Huellitas', 'Corazon Peludo'][i]}",
                description="Refugio verificado dedicado al rescate y adopcion responsable de perritos.",
                city=city,
                country=country,
                status="approved",
                rescued_count=random.randint(10, 80),
                adopted_count=random.randint(5, 50),
                foster_count=random.randint(0, 15),
                points=random.randint(50, 300),
                documents=["/uploads/doc1.jpg"],
                created_at=datetime.utcnow() - timedelta(days=random.randint(20, 100)),
            )
            db.add(r)
            refuges.append(r)
        db.commit()
        for r in refuges:
            db.refresh(r)

        print("Creando productos de refugios...")
        for r in refuges:
            for j in range(random.randint(2, 4)):
                p = Product(
                    refuge_id=r.id,
                    name=random.choice(["Correa reflectiva", "Croquetas premium", "Juguete mordedor", "Cama chica", "Plato doble", "Shampoo canino"]),
                    description="Producto de calidad para tu mascota. Todo lo recaudado apoya al refugio.",
                    price=random.randint(50, 500),
                    stock=random.randint(5, 30),
                    photos=[random.choice(photos)] if photos else [],
                    is_active=True,
                )
                db.add(p)
        db.commit()

        print("Creando matches, solicitudes y conversaciones...")
        # Asegurar que el usuario demo tenga conversaciones para probar
        demo_user = db.query(User).filter(User.email == "demo@patitasfind.example.com").first()
        if not demo_user:
            demo_user = User(
                email="demo@patitasfind.example.com",
                full_name="Usuario Demo",
                phone="+525512345678",
                phone_verified=True,
                city="Ciudad de México",
                country="México",
                latitude=19.4326,
                longitude=-99.1332,
                role="user",
                is_active=True,
            )
            db.add(demo_user)
            db.commit()
            db.refresh(demo_user)

        for _ in range(8):
            adopter = random.choice(users)
            dog = random.choice(dogs)
            if dog.owner_id == adopter.id:
                continue
            m = Match(
                user_id=adopter.id,
                dog_id=dog.id,
                status=random.choice(["pending_application", "approved", "rejected"]),
                created_at=datetime.utcnow() - timedelta(days=random.randint(0, 10)),
            )
            db.add(m)
            db.commit()
            db.refresh(m)

            app = AdoptionApplication(
                match_id=m.id,
                answers={
                    "housing": random.choice(["casa_con_jardin", "departamento_grande"]),
                    "experience": random.choice(["mucha", "alguna"]),
                    "children": random.choice(["si_grandes", "no"]),
                    "other_pets": random.choice(["perros", "no"]),
                    "budget": random.choice(["500-1000", "1000+"]),
                    "outdoor": random.choice(["jardin", "parque_cerca"]),
                },
                status="pending" if m.status == "pending_application" else ("approved" if m.status == "approved" else "rejected"),
            )
            db.add(app)

            if m.status == "approved":
                conv = Conversation(match_id=m.id, user_a_id=adopter.id, user_b_id=dog.owner_id,
                                    last_message_at=datetime.utcnow())
                db.add(conv)
                db.commit()
                db.refresh(conv)
                for k in range(random.randint(2, 5)):
                    sender_id = random.choice([adopter.id, dog.owner_id])
                    msg = Message(
                        conversation_id=conv.id,
                        sender_id=sender_id,
                        content=random.choice([
                            "Hola, me encantaría conocer a " + dog.name,
                            "Claro, ¿cuándo podrías pasar?",
                            "Estoy disponible este fin de semana",
                            "Perfecto, te espero",
                            "Gracias por la oportunidad"
                        ]),
                        created_at=datetime.utcnow() - timedelta(hours=random.randint(1, 48)),
                    )
                    db.add(msg)
            db.commit()

        # Match aprobado con chat para el usuario demo
        demo_dog = random.choice(dogs)
        if demo_dog.owner_id != demo_user.id:
            demo_match = Match(
                user_id=demo_user.id,
                dog_id=demo_dog.id,
                status="approved",
                created_at=datetime.utcnow() - timedelta(days=2),
            )
            db.add(demo_match)
            db.commit()
            db.refresh(demo_match)
            db.add(AdoptionApplication(match_id=demo_match.id, answers={"housing": "casa_con_jardin", "experience": "mucha", "children": "no", "other_pets": "no", "budget": "1000+", "outdoor": "jardin"}, status="approved"))
            demo_conv = Conversation(match_id=demo_match.id, user_a_id=demo_user.id, user_b_id=demo_dog.owner_id,
                                     last_message_at=datetime.utcnow())
            db.add(demo_conv)
            db.commit()
            db.refresh(demo_conv)
            db.add(Message(conversation_id=demo_conv.id, sender_id=demo_user.id, content="¡Hola! Me encanta " + demo_dog.name + ". ¿Me lo podrían mostrar?", created_at=datetime.utcnow() - timedelta(hours=5)))
            db.add(Message(conversation_id=demo_conv.id, sender_id=demo_dog.owner_id, content="¡Claro! Está disponible para que lo conozcas este fin de semana.", created_at=datetime.utcnow() - timedelta(hours=4)))
            db.commit()

        print("Creando ordenes de prueba...")
        approved_matches_with_conv = db.query(Match).filter(Match.status == "approved").all()
        for m in approved_matches_with_conv[:3]:
            # Crear una orden ficticia de productos para el adoptante
            products_for_order = db.query(Product).order_by(Product.id).limit(2).all()
            if products_for_order:
                total = sum([p.price for p in products_for_order])
                order = Order(
                    user_id=m.user_id,
                    total=total,
                    shipping_address=f"Calle de prueba {random.randint(1, 100)}, {m.dog.city or 'Ciudad de Mexico'}",
                    status=random.choice(["paid", "shipped"]),
                    created_at=datetime.utcnow() - timedelta(days=random.randint(1, 10)),
                )
                db.add(order)
                db.commit()
                db.refresh(order)
                for p in products_for_order:
                    db.add(OrderItem(order_id=order.id, product_id=p.id, quantity=1, unit_price=p.price))
                db.commit()

        print("Creando recordatorios post-adopcion...")
        for m in approved_matches_with_conv[:5]:
            db.add(Reminder(
                user_id=m.user_id,
                match_id=m.id,
                title="Vacuna de refuerzo",
                due_date=datetime.utcnow() + timedelta(days=random.randint(7, 30)),
                type="vaccine",
                is_completed=random.choice([True, False]),
            ))
        db.commit()

        print("Creando reportes perdidos y encontrados...")
        for _ in range(6):
            reporter = random.choice(users)
            city, country, lat, lon = random.choice(CITIES)
            lr = LostReport(
                reporter_id=reporter.id,
                dog_name=random.choice(["Pelusa", "Chato", "Manchas", "Negro", "Princesa"]),
                report_type=random.choice(["lost", "found"]),
                description="Visto por última vez cerca del parque. Cualquier información es valiosa.",
                city=city,
                country=country,
                latitude=lat + random.uniform(-0.05, 0.05),
                longitude=lon + random.uniform(-0.05, 0.05),
                photos=[random.choice(photos)] if photos else [],
                status="active",
                source="app",
            )
            db.add(lr)
        # Reporte anónimo recibido por WhatsApp (reporter_id nulo)
        city, country, lat, lon = CITIES[0]
        db.add(LostReport(
            reporter_id=None,
            dog_name="Perrito encontrado",
            report_type="found",
            description="Perrito café con collar rojo, muy amigable. Reporte recibido por WhatsApp.",
            city=city, country=country,
            latitude=lat + 0.01, longitude=lon - 0.01,
            photos=[random.choice(photos)] if photos else [],
            status="active", source="whatsapp", contact_phone="5215512345678",
        ))
        db.commit()

        print("Creando hogares de paso...")
        for i in range(2):
            owner = users[-(i+1)]
            city, country, lat, lon = random.choice(CITIES)
            fh = FosterHome(
                user_id=owner.id,
                description="Hogar temporal seguro y amoroso mientras encontramos familia definitiva.",
                city=city,
                country=country,
                capacity=random.randint(1, 4),
                status="approved",
            )
            db.add(fh)
        db.commit()

        print("Creando notificaciones...")
        for u in users[:5]:
            for _ in range(random.randint(1, 3)):
                n = Notification(
                    user_id=u.id,
                    type=random.choice(["new_like", "new_application", "match_approved"]),
                    title=random.choice(["Nuevo like", "Nueva solicitud", "Match aprobado"]),
                    body="Alguien interactuo con una de tus publicaciones.",
                    is_read=random.choice([True, False]),
                )
                db.add(n)
        db.commit()

        print("Calculando firmas visuales de las fotos...")
        for model in (Dog, LostReport):
            for obj in db.query(model).all():
                if obj.photos:
                    try:
                        obj.photo_signature = signature_for_urls(obj.photos)
                    except Exception as e:  # noqa: BLE001
                        print(f"No se pudo calcular la firma de {model.__name__} {obj.id}: {e}")
        db.commit()

        print("Seeding completo.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()

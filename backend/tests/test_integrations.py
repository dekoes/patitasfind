"""Adaptadores externos con HTTP simulado: SMS (SMS Masivos/Twilio), visión (OpenAI-compatible),
Google OAuth (state + vinculación) y validaciones de producción."""
import json
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from app import oauth
from app.config import Settings, settings
from app.services import sms, vision
from tests.conftest import make_jpeg


class FakeResp:
    def __init__(self, status=200, body=None, text=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("sin JSON")
        return self._body


# --------------------------------------------------------------------------- teléfono
@pytest.mark.parametrize("raw,expected", [
    ("55 1234 5678", "+525512345678"),
    ("(55) 1234-5678", "+525512345678"),
    ("+52 55 1234 5678", "+525512345678"),
    ("525512345678", "+525512345678"),
    ("5215512345678", "+525512345678"),
    ("+521 55 1234 5678", "+525512345678"),
    ("0052 33 1234 5678", "+523312345678"),
    ("044 55 1234 5678", "+525512345678"),
    ("12345", None),
    ("0512345678", None),
    ("+1 415 555 1234", None),
    ("55-1234-567a", None),
    ("", None),
    (None, None),
])
def test_normalize_mx_phone(raw, expected):
    assert sms.normalize_mx_phone(raw) == expected


# --------------------------------------------------------------------------- SMS Masivos
def test_smsmasivos_payload_and_sandbox(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResp(200, {"success": True, "message": "Mensajes enviados", "code": "sms_01"})

    monkeypatch.setattr(sms.requests, "post", fake_post)
    monkeypatch.setattr(settings, "sms_provider", "smsmasivos")
    monkeypatch.setattr(settings, "smsmasivos_api_key", "llave-prueba")
    monkeypatch.setattr(settings, "smsmasivos_sandbox", True)
    assert sms.provider() == "smsmasivos"
    assert sms.send_otp("+525512345678", "123456") == "smsmasivos"
    call = calls[0]
    assert call["url"] == "https://api.smsmasivos.com.mx/sms/send"
    assert call["headers"]["apikey"] == "llave-prueba"
    assert call["json"]["numbers"] == "5512345678" and call["json"]["country_code"] == "52"
    assert call["json"]["sandbox"] == 1
    assert call["json"]["message"] == "GuauWoow: tu codigo es 123456. Vence en 10 min. No lo compartas con nadie."

    monkeypatch.setattr(settings, "smsmasivos_sandbox", False)
    sms.send_otp("+525512345678", "654321")
    assert "sandbox" not in calls[1]["json"]


@pytest.mark.parametrize("resp", [
    FakeResp(200, {"success": False, "message": "Créditos insuficientes"}),
    FakeResp(401, {"success": False, "message": "apikey inválida"}),
    FakeResp(500, None, text="<html>error</html>"),
])
def test_smsmasivos_failures(monkeypatch, resp):
    monkeypatch.setattr(sms.requests, "post", lambda *a, **k: resp)
    monkeypatch.setattr(settings, "sms_provider", "smsmasivos")
    monkeypatch.setattr(settings, "smsmasivos_api_key", "llave")
    with pytest.raises(sms.SMSError) as exc:
        sms.send_otp("+525512345678", "123456")
    assert str(exc.value) == "No pudimos enviar el SMS, intenta de nuevo"


def test_smsmasivos_network_error(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("sin red")

    monkeypatch.setattr(sms.requests, "post", boom)
    monkeypatch.setattr(settings, "sms_provider", "smsmasivos")
    monkeypatch.setattr(settings, "smsmasivos_api_key", "llave")
    with pytest.raises(sms.SMSError):
        sms.send_otp("+525512345678", "123456")


def test_send_code_endpoint_with_smsmasivos(client, make_user, monkeypatch):
    """Con proveedor real: no devuelve dev_code y un fallo del proveedor da 502."""
    u = make_user("SMS real", verify=False)
    sent = []
    monkeypatch.setattr(settings, "sms_provider", "smsmasivos")
    monkeypatch.setattr(settings, "smsmasivos_api_key", "llave")
    monkeypatch.setattr(sms.requests, "post", lambda url, json=None, **k: sent.append(json) or FakeResp(200, {"success": True}))
    r = client.post("/users/me/phone/send-code", headers=u["hip"])
    assert r.status_code == 200 and "dev_code" not in r.json() and sent[0]["numbers"] == u["phone"][-10:]

    v = make_user("SMS falla", verify=False)
    monkeypatch.setattr(sms.requests, "post", lambda *a, **k: FakeResp(200, {"success": False}))
    r = client.post("/users/me/phone/send-code", headers=v["hip"])
    assert r.status_code == 502 and r.json()["detail"] == "No pudimos enviar el SMS, intenta de nuevo"


def test_twilio_messages_adapter(monkeypatch):
    calls = []
    monkeypatch.setattr(sms.requests, "post", lambda url, data=None, auth=None, **k: calls.append((url, data, auth)) or FakeResp(201, {"sid": "SM1"}))
    monkeypatch.setattr(settings, "sms_provider", "twilio")
    monkeypatch.setattr(settings, "twilio_account_sid", "AC123")
    monkeypatch.setattr(settings, "twilio_auth_token", "tok")
    monkeypatch.setattr(settings, "twilio_from_number", "+15550001111")
    assert sms.send_otp("+525512345678", "111222") == "twilio"
    url, data, auth = calls[0]
    assert url.endswith("/Accounts/AC123/Messages.json") and data["To"] == "+525512345678"
    assert data["From"] == "+15550001111" and "111222" in data["Body"] and auth == ("AC123", "tok")


def test_zernio_messages_adapter(monkeypatch):
    calls = []
    monkeypatch.setattr(sms.requests, "post", lambda url, json=None, headers=None, **k: calls.append((url, json, headers)) or FakeResp(200, {"id": "msg_1", "status": "sent"}))
    monkeypatch.setattr(settings, "sms_provider", "zernio")
    monkeypatch.setattr(settings, "zernio_api_key", "zrn_live_123")
    monkeypatch.setattr(settings, "zernio_from", "GUAUWOOW")
    assert sms.provider() == "zernio"
    assert sms.send_otp("+525512345678", "333444") == "zernio"
    url, payload, headers = calls[0]
    assert url == "https://zernio.com/api/v1/sms/messages"
    assert payload["from"] == "GUAUWOOW" and payload["to"] == "+525512345678" and "333444" in payload["text"]
    assert headers["Authorization"] == "Bearer zrn_live_123"


def test_sms_provider_fallbacks(monkeypatch):
    monkeypatch.setattr(settings, "sms_provider", "smsmasivos")
    monkeypatch.setattr(settings, "smsmasivos_api_key", None)
    monkeypatch.setattr(settings, "environment", "development")
    assert settings.sms_effective_provider == "dev"
    monkeypatch.setattr(settings, "environment", "staging")
    assert settings.sms_effective_provider is None and settings.otp_enabled is False


# --------------------------------------------------------------------------- visión
def test_extract_json_variants():
    assert vision.extract_json('{"is_dog": true}') == {"is_dog": True}
    assert vision.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert vision.extract_json('Claro, aquí está: {"a": {"b": 2}} ¡Listo!') == {"a": {"b": 2}}
    assert vision.extract_json('<think>hmm {no}</think>{"ok": 1}') == {"ok": 1}
    assert vision.extract_json("sin json") is None
    assert vision.extract_json("") is None


def test_normalize_analysis():
    out = vision.normalize_analysis({"is_dog": "true", "breed_guess": "Labrador", "size": "large",
                                     "colors": "Negro, blanco", "distinctive_marks": None, "approx_age": "Adulto joven"})
    assert out["size"] == "Grande" and out["colors"] == ["negro", "blanco"] and out["distinctive_marks"] == []
    assert out["is_dog"] is True and out["approx_age"] in ("adulto", "joven")
    assert set(out) == {"is_dog", "breed_guess", "size", "colors", "coat", "distinctive_marks", "approx_age", "description_es"}
    cat = vision.normalize_analysis({"is_dog": False, "breed_guess": "Gato", "size": "??"})
    assert cat["is_dog"] is False and cat["breed_guess"] == "" and cat["size"] == "Mediano"


def _ai_on(monkeypatch, **extra):
    monkeypatch.setattr(settings, "ai_api_key", "sk-prueba")
    monkeypatch.setattr(settings, "ai_base_url", "https://ia.ejemplo/v1")
    monkeypatch.setattr(settings, "ai_model", "qwen3-vl-flash")
    for k, v in extra.items():
        monkeypatch.setattr(settings, k, v)
    vision._memory_cache.clear()
    monkeypatch.setattr(vision.cache, "get", lambda k: None)
    monkeypatch.setattr(vision.cache, "set", lambda *a, **k: None)
    monkeypatch.setattr(vision.time, "sleep", lambda s: None)


def test_vision_request_and_parse(monkeypatch):
    _ai_on(monkeypatch, ai_extra_body='{"enable_thinking": false}')
    calls = []
    content = '```json\n{"is_dog": true, "breed_guess": "Mestizo (Labrador)", "size": "Mediano", "colors": ["café"],' \
              ' "coat": "corto", "distinctive_marks": ["oreja caída"], "approx_age": "adulto", "description_es": "Perrito café."}\n```'

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResp(200, {"model": "qwen3-vl-flash", "choices": [{"message": {"role": "assistant", "content": content}}]})

    monkeypatch.setattr(vision.requests, "post", fake_post)
    result = vision.analyze_image_bytes(make_jpeg(3, size=(2400, 1800)))
    assert result["breed_guess"] == "Mestizo (Labrador)" and result["colors"] == ["café"] and result["model"] == "qwen3-vl-flash"
    call = calls[0]
    assert call["url"] == "https://ia.ejemplo/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-prueba" and call["timeout"] <= 20
    assert call["json"]["model"] == "qwen3-vl-flash" and call["json"]["enable_thinking"] is False
    assert "response_format" not in call["json"]
    parts = call["json"]["messages"][1]["content"]
    img = next(p for p in parts if p["type"] == "image_url")["image_url"]["url"]
    assert img.startswith("data:image/jpeg;base64,")
    import base64, io
    from PIL import Image
    w, h = Image.open(io.BytesIO(base64.b64decode(img.split(",", 1)[1]))).size
    assert max(w, h) == 1024
    assert "SOLO" in next(p for p in parts if p["type"] == "text")["text"]
    # Segunda llamada: caché en memoria, sin HTTP
    vision.analyze_image_bytes(make_jpeg(3, size=(2400, 1800)))
    assert len(calls) == 1


def test_vision_retries_once_then_none(monkeypatch):
    _ai_on(monkeypatch)
    calls = []
    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: calls.append(1) or FakeResp(503, None, text="ocupado"))
    assert vision.analyze_image_bytes(make_jpeg(4)) is None
    assert len(calls) == 2


def test_vision_retry_succeeds_after_429(monkeypatch):
    _ai_on(monkeypatch)
    responses = [FakeResp(429, None, text="rate"),
                 FakeResp(200, {"choices": [{"message": {"content": '{"is_dog": true, "size": "Grande"}'}}]})]
    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: responses.pop(0))
    assert vision.analyze_image_bytes(make_jpeg(5))["size"] == "Grande"


def test_vision_no_retry_on_401_and_bad_text(monkeypatch):
    _ai_on(monkeypatch)
    calls = []
    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: calls.append(1) or FakeResp(401, {"error": "invalid key"}))
    assert vision.analyze_image_bytes(make_jpeg(6)) is None and len(calls) == 1
    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: FakeResp(200, {"choices": [{"message": {"content": "No puedo"}}]}))
    assert vision.analyze_image_bytes(make_jpeg(8)) is None


def test_vision_timeout_returns_none(monkeypatch):
    _ai_on(monkeypatch)

    def slow(*a, **k):
        raise requests.Timeout("lento")

    monkeypatch.setattr(vision.requests, "post", slow)
    assert vision.analyze_image_bytes(make_jpeg(9)) is None


def test_analyze_photo_endpoint(client, user, monkeypatch):
    _ai_on(monkeypatch)
    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: FakeResp(
        200, {"choices": [{"message": {"content": '{"is_dog": true, "breed_guess": "Chihuahua", "size": "pequeño", "colors": ["negro"], "description_es": "Chiquito."}'}}]}))
    r = client.post("/ai/analyze-photo", headers=user["h"], files={"file": ("q.jpg", make_jpeg(10), "image/jpeg")})
    assert r.status_code == 200
    body = r.json()
    assert body["breed"] == "Chihuahua" and body["size"] == "Pequeño" and body["color"] == "negro"
    assert body["description"] == "Chiquito."
    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: FakeResp(401, {"error": "bad key"}))
    vision._memory_cache.clear()
    r = client.post("/ai/analyze-photo", headers=user["h"], files={"file": ("q.jpg", make_jpeg(11), "image/jpeg")})
    assert r.status_code == 502


# --------------------------------------------------------------------------- Google OAuth
@pytest.fixture
def google_on(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cliente.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "secreto")
    monkeypatch.setattr(settings, "google_redirect_uri", None)
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:8082")


def _mock_google(monkeypatch, userinfo, seen=None):
    def fake_post(url, data=None, timeout=None, **k):
        assert url == oauth.GOOGLE_ACCESS_TOKEN_URL
        if seen is not None:
            seen.append(data)
        if data["code"] != "codigo-bueno":
            return FakeResp(400, {"error": "invalid_grant"})
        return FakeResp(200, {"access_token": "ya29.token", "id_token": "x"})

    def fake_get(url, headers=None, timeout=None, **k):
        assert headers["Authorization"] == "Bearer ya29.token"
        return FakeResp(200, userinfo)

    monkeypatch.setattr(oauth.requests, "post", fake_post)
    monkeypatch.setattr(oauth.requests, "get", fake_get)


def _start_login(client, query=""):
    r = client.get("/auth/google/login" + query, follow_redirects=False)
    assert r.status_code == 302
    loc = urlparse(r.headers["location"])
    params = parse_qs(loc.query)
    assert loc.netloc == "accounts.google.com"
    assert params["redirect_uri"] == ["http://localhost:8082/auth/google/callback"]
    assert params["client_id"] == ["cliente.apps.googleusercontent.com"]
    assert "pf_oauth_state" in r.headers.get("set-cookie", "") and "HttpOnly" in r.headers["set-cookie"]
    return params["state"][0], r.cookies.get("pf_oauth_state")


def test_google_login_disabled_redirects(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", None)
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code == 302 and "auth_error=" in r.headers["location"]


def test_google_state_validation(client, google_on, monkeypatch):
    _mock_google(monkeypatch, {"sub": "1", "email": "x@gmail.com", "email_verified": True})
    state, nonce = _start_login(client)
    client.cookies.clear()
    # Sin cookie (otro navegador / CSRF)
    r = client.get("/auth/google/callback", params={"code": "codigo-bueno", "state": state}, follow_redirects=False)
    assert r.status_code == 302 and "/app/?auth_error=" in r.headers["location"]
    # state alterado
    r = client.get("/auth/google/callback", params={"code": "codigo-bueno", "state": state + "x"},
                   cookies={"pf_oauth_state": nonce}, follow_redirects=False)
    assert "auth_error=" in r.headers["location"]
    # cookie de otro flujo
    r = client.get("/auth/google/callback", params={"code": "codigo-bueno", "state": state},
                   cookies={"pf_oauth_state": "otro-nonce"}, follow_redirects=False)
    assert "auth_error=" in r.headers["location"]
    # state expirado
    import itsdangerous
    real_loads = itsdangerous.URLSafeTimedSerializer.loads

    def expired(self, s, max_age=None, **kw):
        raise itsdangerous.SignatureExpired("vencido")

    monkeypatch.setattr(itsdangerous.URLSafeTimedSerializer, "loads", expired)
    r = client.get("/auth/google/callback", params={"code": "codigo-bueno", "state": state},
                   cookies={"pf_oauth_state": nonce}, follow_redirects=False)
    assert "auth_error=" in r.headers["location"]
    monkeypatch.setattr(itsdangerous.URLSafeTimedSerializer, "loads", real_loads)
    # Google devolvió error (el usuario canceló)
    r = client.get("/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert "auth_error=" in r.headers["location"]


def test_google_new_user_and_terms(client, google_on, monkeypatch):
    import uuid
    email = f"g-{uuid.uuid4().hex[:8]}@gmail.com"
    seen = []
    _mock_google(monkeypatch, {"sub": uuid.uuid4().hex, "email": email, "email_verified": True, "name": "Gina",
                               "picture": "https://lh3.googleusercontent.com/a/x"}, seen)
    state, nonce = _start_login(client, "?accepted_terms=1&marketing_opt_in=1")
    r = client.get("/auth/google/callback", params={"code": "codigo-bueno", "state": state},
                   cookies={"pf_oauth_state": nonce}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("http://localhost:8082/app/#token=")
    assert seen[0]["redirect_uri"] == "http://localhost:8082/auth/google/callback"
    token = r.headers["location"].split("token=")[1]
    me = client.get("/users/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["email"] == email and me["full_name"] == "Gina" and me["has_password"] is False
    assert me["phone"] is None and me["phone_verification_required"] is True
    # Los parámetros de la URL no son una aceptación: Términos, edad y correos promocionales se dan en la app
    assert me["terms_accepted_at"] is None and me["marketing_opt_in"] is False and me["age_declaration_required"] is True
    # Restringido hasta agregar y verificar teléfono
    h = {"Authorization": f"Bearer {token}"}
    assert client.post("/lost-reports", headers=h, json={"dog_name": "G", "report_type": "lost"}).status_code == 403
    r = client.post("/users/me/terms", headers=h, json={"accepted_terms": True, "marketing_opt_in": True,
                                                        "is_adult": True, "birth_date": "1990-01-01"})
    assert r.status_code == 200, r.text
    assert r.json()["terms_version"] == settings.legal_terms_version and r.json()["marketing_opt_in"] is True
    client.cookies.clear()


def test_google_links_existing_account(client, google_on, user, monkeypatch):
    _mock_google(monkeypatch, {"sub": "google-sub-" + user["email"], "email": user["email"].upper(), "email_verified": True})
    state, nonce = _start_login(client)
    r = client.get("/auth/google/callback", params={"code": "codigo-bueno", "state": state},
                   cookies={"pf_oauth_state": nonce}, follow_redirects=False)
    token = r.headers["location"].split("token=")[1]
    me = client.get("/users/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["email"] == user["email"] and me["phone_verified"] is True  # misma cuenta, ya verificada
    client.cookies.clear()


def test_google_rejects_unverified_email_and_bad_code(client, google_on, user, monkeypatch):
    _mock_google(monkeypatch, {"sub": "zzz", "email": user["email"], "email_verified": False})
    state, nonce = _start_login(client)
    r = client.get("/auth/google/callback", params={"code": "codigo-bueno", "state": state},
                   cookies={"pf_oauth_state": nonce}, follow_redirects=False)
    assert "auth_error=" in r.headers["location"]
    state, nonce = _start_login(client)
    r = client.get("/auth/google/callback", params={"code": "codigo-malo", "state": state},
                   cookies={"pf_oauth_state": nonce}, follow_redirects=False)
    assert "auth_error=" in r.headers["location"]
    client.cookies.clear()


# --------------------------------------------------------------------------- producción
@pytest.fixture(autouse=False)
def clean_env(monkeypatch):
    import os
    for key in list(os.environ):
        if key.startswith(("CORS_", "WHATSAPP_", "SMS", "SMSMASIVOS_", "POSTGRES_", "ALLOW_DEMO", "SECRET_KEY", "DATABASE_URL",
                           "PUBLIC_BASE_URL", "SMTP_", "MERCADOPAGO_", "SHOP_", "TWILIO_", "REQUIRE_PHONE")):
            monkeypatch.delenv(key, raising=False)


def _prod(**overrides):
    base = dict(
        _env_file=None, environment="production", secret_key="x" * 64,
        database_url="postgresql+psycopg2://patitasfind:Muy-Segura-1@postgres:5432/patitasfind",
        cors_origins="https://guauwoow.com", sms_provider="smsmasivos", smsmasivos_api_key="k",
        public_base_url="https://guauwoow.com", smtp_host="smtp.ejemplo.mx", smtp_from="GuauWoow <no-reply@guauwoow.com>",
        private_files_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",  # 32 bytes en base64
    )
    base.update(overrides)
    return Settings(**base)


def test_production_settings_ok(clean_env):
    s = _prod()
    assert s.effective_cors_origin_regex is None and s.demo_enabled is False
    assert _prod(allow_demo_login=True).demo_enabled is False


@pytest.mark.parametrize("overrides,needle", [
    ({"secret_key": "dev-secret-key-change-in-production"}, "SECRET_KEY"),
    ({"cors_origins": None}, "CORS_ORIGINS"),
    ({"database_url": "postgresql+psycopg2://patitasfind:patitasfind@postgres:5432/patitasfind"}, "PostgreSQL"),
    ({"postgres_password": "patitasfind"}, "PostgreSQL"),
    ({"whatsapp_access_token": "EAAG", "whatsapp_verify_token": "otro-token-largo"}, "WHATSAPP_APP_SECRET"),
    ({"whatsapp_access_token": "EAAG", "whatsapp_app_secret": "s"}, "WHATSAPP_VERIFY_TOKEN"),
    ({"cors_origin_regex": r"https://.*\.trycloudflare\.com"}, "trycloudflare"),
    ({"smsmasivos_api_key": None}, "SMSMASIVOS_API_KEY"),
    ({"sms_provider": "dev"}, "SMS_PROVIDER=dev"),
    ({"secret_key": "corta"}, "SECRET_KEY es muy corta"),
    ({"public_base_url": None}, "PUBLIC_BASE_URL"),
    ({"public_base_url": "http://guauwoow.com"}, "PUBLIC_BASE_URL"),
    ({"cors_origins": "https://guauwoow.com,http://localhost:8082"}, "CORS_ORIGINS"),
    ({"smtp_host": None}, "SMTP_HOST"),
    ({"mercadopago_access_token": "APP_USR-1"}, "MERCADOPAGO_WEBHOOK_SECRET"),
    ({"shop_enabled": True}, "SHOP_ENABLED"),
])
def test_production_refuses_insecure(clean_env, overrides, needle):
    with pytest.raises(Exception) as exc:
        _prod(**overrides)
    assert needle in str(exc.value)


def test_dev_defaults(clean_env):
    s = Settings(_env_file=None, environment="development")
    assert "http://localhost:8082" in s.cors_origin_list and "trycloudflare" in s.effective_cors_origin_regex
    with pytest.raises(Exception):
        Settings(_env_file=None, sms_provider="otro")


# --------------------------------------------------------------------------- Sentry
def test_sentry_scrubbing_and_noop():
    from app import observability

    assert observability.init_sentry() is False or settings.sentry_dsn  # sin DSN: no-op
    event = {
        "request": {"headers": {"Authorization": "Bearer abc", "User-Agent": "x"}, "cookies": {"s": "1"},
                    "data": {"phone": "5512345678", "email": "a@b.mx", "note": "llámame al 55 1234 5678 o a@b.mx"}},
        "user": {"id": 7, "email": "a@b.mx", "ip_address": "1.2.3.4"},
        "extra": {"contact_phone": "+525512345678"},
        "exception": {"values": [{"value": "Fallo para pepe@correo.mx"}]},
    }
    out = observability._before_send(event, None)
    assert out["request"]["headers"]["Authorization"] == "[Filtrado]" and out["request"]["headers"]["User-Agent"] == "x"
    assert out["request"]["cookies"] == "[Filtrado]"
    assert out["request"]["data"]["phone"] == "[Filtrado]" and out["request"]["data"]["email"] == "[Filtrado]"
    assert "a@b.mx" not in out["request"]["data"]["note"] and "1234" not in out["request"]["data"]["note"]
    assert out["user"] == {"id": 7} and out["extra"]["contact_phone"] == "[Filtrado]"
    assert "pepe@correo.mx" not in out["exception"]["values"][0]["value"]

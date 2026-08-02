from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..provider_oauth_models import BatchDataOAuthConnection, BatchDataOAuthState

MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_TOOL_NAME = "lookup_property"


@dataclass(frozen=True)
class BatchDataConfig:
    mcp_url: str
    callback_base_url: str

    @classmethod
    def from_env(cls) -> "BatchDataConfig | None":
        mcp_url = (os.getenv("BATCHDATA_MCP_URL") or "").strip().rstrip("/")
        callback_base = (
            os.getenv("BATCHDATA_OAUTH_CALLBACK_BASE_URL")
            or os.getenv("PUBLIC_BACKEND_URL")
            or (f"https://{os.getenv('VERCEL_PROJECT_PRODUCTION_URL')}" if os.getenv("VERCEL_PROJECT_PRODUCTION_URL") else "")
        ).strip().rstrip("/")
        if not mcp_url:
            return None
        return cls(mcp_url=mcp_url, callback_base_url=callback_base)

    @property
    def redirect_uri(self) -> str:
        return f"{self.callback_base_url}/provider-intelligence/batchdata/callback"


class BatchDataProviderError(RuntimeError):
    def __init__(self, state: str, message: str, http_status: int | None = None):
        super().__init__(message)
        self.state = state
        self.http_status = http_status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _classify(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "ready_verified"
    if status_code in {401, 403}:
        return "invalid_credentials"
    if status_code == 402:
        return "payment_required"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "unavailable"
    return "configured_unverified"


def _validate_https(url: str, label: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise BatchDataProviderError("unavailable", f"{label} must be an HTTPS URL without embedded credentials")


def _fernet() -> Fernet:
    secret = (os.getenv("BATCHDATA_OAUTH_ENCRYPTION_KEY") or os.getenv("BOOTSTRAP_SECRET") or "").strip()
    if len(secret) < 32:
        raise BatchDataProviderError(
            "configured_unverified",
            "BATCHDATA_OAUTH_ENCRYPTION_KEY (or BOOTSTRAP_SECRET) must contain at least 32 characters",
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt(value: str | None) -> str | None:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii") if value else None


def _decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise BatchDataProviderError("invalid_credentials", "Stored BatchData credential cannot be decrypted") from exc


def _state_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _oauth_metadata_url(mcp_url: str) -> str:
    parsed = urlparse(mcp_url)
    return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server"


def _discover_oauth(config: BatchDataConfig) -> dict[str, Any]:
    _validate_https(config.mcp_url, "BatchData MCP URL")
    with httpx.Client(timeout=20.0, follow_redirects=False) as client:
        response = client.get(_oauth_metadata_url(config.mcp_url), headers={"Accept": "application/json"})
    if response.status_code != 200:
        raise BatchDataProviderError(_classify(response.status_code), "BatchData OAuth discovery failed", response.status_code)
    try:
        metadata = response.json()
    except ValueError as exc:
        raise BatchDataProviderError("unavailable", "BatchData OAuth metadata is not valid JSON") from exc
    required = ("issuer", "authorization_endpoint", "token_endpoint", "registration_endpoint")
    if not all(isinstance(metadata.get(key), str) and metadata[key] for key in required):
        raise BatchDataProviderError("unavailable", "BatchData OAuth metadata is incomplete")
    if "S256" not in metadata.get("code_challenge_methods_supported", []):
        raise BatchDataProviderError("unavailable", "BatchData OAuth server does not advertise PKCE S256")
    for key in required:
        _validate_https(metadata[key], f"BatchData OAuth {key}")
    return metadata


def _connection(db: Session, organization_id: int) -> BatchDataOAuthConnection | None:
    return db.scalar(select(BatchDataOAuthConnection).where(
        BatchDataOAuthConnection.organization_id == organization_id,
    ))


def oauth_status(config: BatchDataConfig | None, db: Session, organization_id: int) -> dict[str, Any]:
    if config is None:
        return {"state": "blocked", "configured": False, "verified": False, "missing": ["BATCHDATA_MCP_URL"]}
    missing = []
    if not config.callback_base_url:
        missing.append("BATCHDATA_OAUTH_CALLBACK_BASE_URL")
    try:
        _fernet()
    except BatchDataProviderError:
        missing.append("BATCHDATA_OAUTH_ENCRYPTION_KEY")
    connection = _connection(db, organization_id)
    connected = bool(connection and connection.access_token_encrypted and connection.revoked_at is None)
    if missing:
        state = "blocked"
    elif connected:
        state = "ready"
    elif connection:
        state = "authorization_required"
    else:
        state = "connection_required"
    return {
        "state": state,
        "configured": not missing,
        "verified": False,
        "connected": connected,
        "missing": missing,
        "environment": "oauth_mcp",
        "connected_at": connection.connected_at.isoformat() if connection and connection.connected_at else None,
        "expires_at": connection.expires_at.isoformat() if connection and connection.expires_at else None,
        "reason": None if connected else "Owner OAuth authorization required",
    }


def start_oauth(config: BatchDataConfig, db: Session, organization_id: int, user_id: int) -> dict[str, str]:
    if not config.callback_base_url:
        raise BatchDataProviderError("configured_unverified", "BATCHDATA_OAUTH_CALLBACK_BASE_URL missing")
    _validate_https(config.redirect_uri, "BatchData OAuth redirect URI")
    metadata = _discover_oauth(config)
    connection = _connection(db, organization_id)

    if connection is None or connection.issuer != metadata["issuer"]:
        registration_payload = {
            "client_name": "SAHJONY Wholesale Ops Provider Intelligence",
            "redirect_uris": [config.redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
        with httpx.Client(timeout=20.0, follow_redirects=False) as client:
            response = client.post(metadata["registration_endpoint"], json=registration_payload, headers={"Accept": "application/json"})
        if response.status_code not in {200, 201}:
            raise BatchDataProviderError(_classify(response.status_code), "BatchData OAuth client registration failed", response.status_code)
        try:
            registered = response.json()
        except ValueError as exc:
            raise BatchDataProviderError("unavailable", "BatchData client registration returned unreadable JSON") from exc
        client_id = str(registered.get("client_id") or "").strip()
        if not client_id:
            raise BatchDataProviderError("unavailable", "BatchData client registration did not return client_id")
        if connection is None:
            connection = BatchDataOAuthConnection(
                organization_id=organization_id,
                client_id=client_id,
                issuer=metadata["issuer"],
                resource_url=config.mcp_url,
            )
            db.add(connection)
        else:
            connection.client_id = client_id
            connection.issuer = metadata["issuer"]
            connection.resource_url = config.mcp_url
        connection.client_secret_encrypted = _encrypt(registered.get("client_secret"))

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    pending_states = db.scalars(select(BatchDataOAuthState).where(
        BatchDataOAuthState.organization_id == organization_id,
        BatchDataOAuthState.used_at.is_(None),
    )).all()
    for pending in pending_states:
        pending.used_at = _now()
    db.add(BatchDataOAuthState(
        organization_id=organization_id,
        user_id=user_id,
        state_hash=_state_hash(state),
        code_verifier_encrypted=_encrypt(verifier) or "",
        redirect_uri=config.redirect_uri,
        expires_at=_now() + timedelta(minutes=10),
    ))
    connection.revoked_at = None
    db.commit()

    query = urlencode({
        "response_type": "code",
        "client_id": connection.client_id,
        "redirect_uri": config.redirect_uri,
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "state": state,
        "resource": config.mcp_url,
    })
    return {"authorization_url": f"{metadata['authorization_endpoint']}?{query}", "state": "authorization_required"}


def complete_oauth(config: BatchDataConfig, db: Session, code: str, state: str) -> BatchDataOAuthConnection:
    oauth_state = db.scalar(select(BatchDataOAuthState).where(BatchDataOAuthState.state_hash == _state_hash(state)))
    if oauth_state is None or oauth_state.used_at is not None or (_aware(oauth_state.expires_at) or _now()) <= _now():
        raise BatchDataProviderError("invalid_credentials", "OAuth state is invalid, expired, or already used")
    connection = _connection(db, oauth_state.organization_id)
    if connection is None:
        raise BatchDataProviderError("invalid_credentials", "BatchData OAuth connection was not initialized")
    oauth_state.used_at = _now()
    db.commit()
    metadata = _discover_oauth(config)
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": connection.client_id,
        "redirect_uri": oauth_state.redirect_uri,
        "code_verifier": _decrypt(oauth_state.code_verifier_encrypted) or "",
        "resource": config.mcp_url,
    }
    client_secret = _decrypt(connection.client_secret_encrypted)
    if client_secret:
        payload["client_secret"] = client_secret
    with httpx.Client(timeout=20.0, follow_redirects=False) as client:
        response = client.post(metadata["token_endpoint"], data=payload, headers={"Accept": "application/json"})
    if response.status_code != 200:
        raise BatchDataProviderError(_classify(response.status_code), "BatchData OAuth token exchange failed", response.status_code)
    try:
        tokens = response.json()
    except ValueError as exc:
        raise BatchDataProviderError("unavailable", "BatchData token response is unreadable") from exc
    access_token = str(tokens.get("access_token") or "").strip()
    if not access_token:
        raise BatchDataProviderError("invalid_credentials", "BatchData token response omitted access_token")
    connection.access_token_encrypted = _encrypt(access_token)
    if tokens.get("refresh_token"):
        connection.refresh_token_encrypted = _encrypt(str(tokens["refresh_token"]))
    connection.token_type = str(tokens.get("token_type") or "Bearer")
    connection.scope = str(tokens.get("scope") or "") or None
    connection.expires_at = _now() + timedelta(seconds=max(30, int(tokens.get("expires_in") or 3600)))
    connection.connected_at = _now()
    connection.revoked_at = None
    db.commit()
    return connection


def _refresh(config: BatchDataConfig, db: Session, connection: BatchDataOAuthConnection) -> str:
    refresh_token = _decrypt(connection.refresh_token_encrypted)
    if not refresh_token:
        raise BatchDataProviderError("authorization_required", "BatchData OAuth authorization must be renewed")
    metadata = _discover_oauth(config)
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": connection.client_id,
        "resource": config.mcp_url,
    }
    client_secret = _decrypt(connection.client_secret_encrypted)
    if client_secret:
        payload["client_secret"] = client_secret
    with httpx.Client(timeout=20.0, follow_redirects=False) as client:
        response = client.post(metadata["token_endpoint"], data=payload, headers={"Accept": "application/json"})
    if response.status_code != 200:
        raise BatchDataProviderError(_classify(response.status_code), "BatchData OAuth refresh failed", response.status_code)
    try:
        tokens = response.json()
    except ValueError as exc:
        raise BatchDataProviderError("unavailable", "BatchData refresh response is unreadable") from exc
    access_token = str(tokens.get("access_token") or "").strip()
    if not access_token:
        raise BatchDataProviderError("invalid_credentials", "BatchData refresh response omitted access_token")
    connection.access_token_encrypted = _encrypt(access_token)
    if tokens.get("refresh_token"):
        connection.refresh_token_encrypted = _encrypt(str(tokens["refresh_token"]))
    connection.expires_at = _now() + timedelta(seconds=max(30, int(tokens.get("expires_in") or 3600)))
    db.commit()
    return access_token


def _access_token(config: BatchDataConfig, db: Session, organization_id: int) -> str:
    connection = _connection(db, organization_id)
    if connection is None or connection.revoked_at is not None or not connection.access_token_encrypted:
        raise BatchDataProviderError("authorization_required", "BatchData MCP is not connected")
    expires_at = _aware(connection.expires_at)
    if expires_at is not None and expires_at <= _now() + timedelta(seconds=60):
        return _refresh(config, db, connection)
    return _decrypt(connection.access_token_encrypted) or ""


def _force_refresh(config: BatchDataConfig, db: Session, organization_id: int) -> str:
    connection = _connection(db, organization_id)
    if connection is None:
        raise BatchDataProviderError("authorization_required", "BatchData MCP is not connected")
    return _refresh(config, db, connection)


def _jsonrpc_response(response: httpx.Response, request_id: int) -> dict[str, Any]:
    if response.status_code < 200 or response.status_code >= 300:
        raise BatchDataProviderError(_classify(response.status_code), f"BatchData MCP failed with HTTP {response.status_code}", response.status_code)
    content_type = response.headers.get("content-type", "").lower()
    candidates: list[dict[str, Any]] = []
    if "text/event-stream" in content_type:
        for line in response.text.splitlines():
            if line.startswith("data:"):
                try:
                    item = json.loads(line[5:].strip())
                    if isinstance(item, dict):
                        candidates.append(item)
                except ValueError:
                    continue
    else:
        try:
            item = response.json()
            if isinstance(item, dict):
                candidates.append(item)
        except ValueError as exc:
            raise BatchDataProviderError("unavailable", "BatchData MCP returned unreadable data") from exc
    message = next((item for item in candidates if item.get("id") == request_id), None)
    if message is None:
        raise BatchDataProviderError("unavailable", "BatchData MCP response did not contain the requested JSON-RPC result")
    if message.get("error"):
        error = message["error"]
        raise BatchDataProviderError("provider_error", str(error.get("message") if isinstance(error, dict) else error))
    return message.get("result") or {}


def _mcp_exchange(config: BatchDataConfig, token: str, method: str, params: dict[str, Any] | None, request_id: int) -> tuple[dict[str, Any], str | None]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": "SAHJONY-Wholesale-OS/Provider-Intelligence-v4",
    }
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "sahjony-wholesale-ops", "version": "4.0"},
        },
    }
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        init_response = client.post(config.mcp_url, headers=headers, json=initialize)
        init_result = _jsonrpc_response(init_response, 1)
        protocol_version = str(init_result.get("protocolVersion") or MCP_PROTOCOL_VERSION)
        session_id = init_response.headers.get("mcp-session-id")
        headers["MCP-Protocol-Version"] = protocol_version
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        client.post(config.mcp_url, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        response = client.post(config.mcp_url, headers=headers, json={
            "jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {},
        })
        return _jsonrpc_response(response, request_id), session_id


def verify_credentials(config: BatchDataConfig, db: Session, organization_id: int) -> dict[str, Any]:
    try:
        token = _access_token(config, db, organization_id)
        try:
            result, _ = _mcp_exchange(config, token, "tools/list", {}, 2)
        except BatchDataProviderError as exc:
            if exc.http_status != 401:
                raise
            token = _force_refresh(config, db, organization_id)
            result, _ = _mcp_exchange(config, token, "tools/list", {}, 2)
        names = [tool.get("name") for tool in result.get("tools", []) if isinstance(tool, dict)]
        found = MCP_TOOL_NAME in names
        return {
            "state": "ready_verified" if found else "configured_unverified",
            "verified": found,
            "environment": "oauth_mcp",
            "tool": MCP_TOOL_NAME,
            "contacts_exposed": False,
            "data_committed": False,
            "external_actions": False,
            "reason": None if found else f"{MCP_TOOL_NAME} is not available for this account",
        }
    except BatchDataProviderError as exc:
        return {
            "state": exc.state,
            "verified": False,
            "environment": "oauth_mcp",
            "http_status": exc.http_status,
            "reason": str(exc),
        }


def lookup_property(config: BatchDataConfig, db: Session, organization_id: int, address: dict[str, str]) -> dict[str, Any]:
    if not all((address.get(field) or "").strip() for field in ("street", "city", "state", "zip")):
        raise BatchDataProviderError("configured_unverified", "A complete street, city, state, and ZIP are required")
    token = _access_token(config, db, organization_id)
    arguments = {
        "property_street": address["street"].strip(),
        "property_city": address["city"].strip(),
        "property_state": address["state"].strip(),
        "property_zip": address["zip"].strip(),
    }
    try:
        result, session_id = _mcp_exchange(config, token, "tools/call", {"name": MCP_TOOL_NAME, "arguments": arguments}, 2)
    except BatchDataProviderError as exc:
        if exc.http_status != 401:
            raise
        token = _force_refresh(config, db, organization_id)
        result, session_id = _mcp_exchange(config, token, "tools/call", {"name": MCP_TOOL_NAME, "arguments": arguments}, 2)
    if result.get("isError"):
        raise BatchDataProviderError("provider_error", "BatchData lookup_property returned an error")
    raw: Any = result.get("structuredContent")
    if raw is None:
        texts = [item.get("text") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"]
        raw_text = "\n".join(item for item in texts if isinstance(item, str))
        try:
            raw = json.loads(raw_text) if raw_text else result
        except ValueError:
            raw = {"text": raw_text}
    return {
        "provider_id": "batchdata",
        "environment": "oauth_mcp",
        "request_id": session_id,
        "observed_at": _now().isoformat(),
        "http_status": 200,
        "raw": raw,
    }


def disconnect(config: BatchDataConfig, db: Session, organization_id: int) -> bool:
    connection = _connection(db, organization_id)
    if connection is None:
        return False
    token = _decrypt(connection.refresh_token_encrypted) or _decrypt(connection.access_token_encrypted)
    if token:
        try:
            metadata = _discover_oauth(config)
            payload = {"token": token, "client_id": connection.client_id}
            client_secret = _decrypt(connection.client_secret_encrypted)
            if client_secret:
                payload["client_secret"] = client_secret
            with httpx.Client(timeout=10.0, follow_redirects=False) as client:
                client.post(metadata.get("revocation_endpoint") or urljoin(metadata["issuer"], "revoke"), data=payload)
        except (BatchDataProviderError, httpx.HTTPError):
            pass
    connection.access_token_encrypted = None
    connection.refresh_token_encrypted = None
    connection.revoked_at = _now()
    db.commit()
    return True


def canonicalize_lookup(result: dict[str, Any]) -> dict[str, Any]:
    raw = result.get("raw") or {}
    records = raw.get("results") or raw.get("data") or raw.get("result") or raw
    first = records[0] if isinstance(records, list) and records else records if isinstance(records, dict) else {}

    property_data = first.get("property") or first.get("propertyData") or first
    owner = first.get("owner") or first.get("ownerData") or {}
    valuation = first.get("valuation") or first.get("avm") or {}
    contacts = first.get("contacts") or first.get("contact") or {}
    mortgages = first.get("mortgages") or first.get("mortgage") or []
    liens = first.get("liens") or []
    comps = first.get("comparables") or first.get("comps") or []

    field_provenance = {
        field: {
            "provider_id": "batchdata",
            "observed_at": result.get("observed_at"),
            "request_id": result.get("request_id"),
            "environment": result.get("environment"),
            "confidence": 0.90,
        }
        for field in ("property", "owner", "valuation", "contacts", "mortgages", "liens", "comparables")
    }

    return {
        "property": property_data if isinstance(property_data, dict) else {},
        "owner": owner if isinstance(owner, dict) else {},
        "valuation": valuation if isinstance(valuation, dict) else {},
        "contacts": contacts if isinstance(contacts, (dict, list)) else {},
        "mortgages": mortgages if isinstance(mortgages, (dict, list)) else [],
        "liens": liens if isinstance(liens, (dict, list)) else [],
        "comparables": comps if isinstance(comps, list) else [],
        "field_provenance": field_provenance,
        "provider": {
            "id": "batchdata",
            "environment": result.get("environment"),
            "request_id": result.get("request_id"),
            "observed_at": result.get("observed_at"),
            "http_status": result.get("http_status"),
            "transport": "mcp_streamable_http",
            "tool": MCP_TOOL_NAME,
        },
        "truth_scope": ["licensed_property_data", "licensed_owner_data", "licensed_contact_data"],
        "confidence": 0.90,
        "limitations": [
            "Provider data must be independently reviewed before offers or outreach",
            "Contact data does not itself establish consent to call or text",
            "DNC and TCPA screening are required before communication",
        ],
    }

import streamlit as st
import pandas as pd
import yfinance as yf
import json
import base64
import os
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import urllib.parse
import urllib.request
import urllib.error
import io
import tempfile
import shutil

# Configuration de la page
st.set_page_config(
    page_title="Scanner Pro & DCA Automatisé",
    page_icon="📈",
    layout="wide"
)

# Fichier de sauvegarde et de secours
PORTFOLIO_FILE = "portefeuille_banques.json"
BACKUP_FILE = "portefeuille_banques.bak"
API_KEYS_FILE = "scanner_api_keys.json"  # Stockage local des clés API (fichier sensible)
VIRTUAL_PORTFOLIO_FILE = "portefeuille_virtuel.json"
VIRTUAL_INITIAL_CAPITAL = 10000.0


VIRTUAL_GITHUB_REPO = "ars67660/bourse-scanner"
VIRTUAL_GITHUB_BRANCH = "main"
VIRTUAL_GITHUB_PATH = "portefeuille_virtuel.json"


def _virtual_github_token():
    """Lit le jeton GitHub depuis les secrets Streamlit ou l'environnement."""
    try:
        token = st.secrets.get("GITHUB_TOKEN", "")
    except Exception:
        token = ""
    return str(token or os.getenv("GITHUB_TOKEN", "")).strip()


def _virtual_github_request(method="GET", payload=None):
    token = _virtual_github_token()
    if not token:
        return None
    url = f"https://api.github.com/repos/{VIRTUAL_GITHUB_REPO}/contents/{VIRTUAL_GITHUB_PATH}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "bourse-scanner-virtual-portfolio",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _normalize_virtual_portfolio(data):
    if not isinstance(data, dict) or not isinstance(data.get("positions", []), list):
        return None
    data.setdefault("initial_capital", VIRTUAL_INITIAL_CAPITAL)
    data.setdefault("cash", VIRTUAL_INITIAL_CAPITAL)
    data.setdefault("positions", [])
    data.setdefault("closed_trades", [])
    data.setdefault("last_cycle", None)
    return data


def load_virtual_portfolio():
    """Charge le portefeuille partagé depuis GitHub, sans exiger de jeton pour la lecture."""
    if _virtual_github_token():
        try:
            remote = _virtual_github_request("GET")
            if remote and remote.get("content"):
                raw = base64.b64decode(remote["content"]).decode("utf-8")
                portfolio = _normalize_virtual_portfolio(json.loads(raw))
                if portfolio is not None:
                    return portfolio
        except Exception as exc:
            st.warning(f"Lecture GitHub authentifiée indisponible : {type(exc).__name__}")

    # Le dépôt est public : la lecture de la sauvegarde ne nécessite aucun jeton.
    try:
        url = "https://raw.githubusercontent.com/ars67660/bourse-scanner/main/portefeuille_virtuel.json"
        request = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "bourse-scanner"})
        with urllib.request.urlopen(request, timeout=8) as response:
            portfolio = _normalize_virtual_portfolio(json.loads(response.read().decode("utf-8")))
        if portfolio is not None:
            return portfolio
    except Exception:
        pass

    try:
        with open(VIRTUAL_PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = _normalize_virtual_portfolio(json.load(f))
        if portfolio is not None:
            return portfolio
    except (OSError, json.JSONDecodeError):
        pass

    return {"initial_capital": VIRTUAL_INITIAL_CAPITAL, "cash": VIRTUAL_INITIAL_CAPITAL,
            "positions": [], "closed_trades": [], "last_cycle": None}


def save_virtual_portfolio(portfolio):
    """Sauvegarde GitHub si un jeton est configuré; sinon secours local."""
    try:
        serialized = json.dumps(portfolio, indent=2, ensure_ascii=False)
        token = _virtual_github_token()
        if token:
            current = _virtual_github_request("GET")
            payload = {
                "message": "Mettre à jour le portefeuille virtuel simulé",
                "content": base64.b64encode(serialized.encode("utf-8")).decode("ascii"),
                "branch": VIRTUAL_GITHUB_BRANCH,
            }
            if current and current.get("sha"):
                payload["sha"] = current["sha"]
            _virtual_github_request("PUT", payload)
            return True
        tmp = VIRTUAL_PORTFOLIO_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(serialized)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, VIRTUAL_PORTFOLIO_FILE)
        return True
    except Exception as exc:
        st.error(f"Échec de sauvegarde du portefeuille virtuel : {type(exc).__name__}")
        return False

def load_saved_api_keys():
    """Charge les clés API enregistrées localement, si le fichier existe."""
    try:
        with open(API_KEYS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

def save_api_keys(keys):
    """Enregistre les clés API localement et restreint les permissions si possible."""
    try:
        cleaned = {str(k): str(v).strip() for k, v in keys.items() if str(v).strip()}
        temp_path = API_KEYS_FILE + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, API_KEYS_FILE)
        try:
            os.chmod(API_KEYS_FILE, 0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False

def validate_app_data(data):
    """Valide et nettoie la structure globale (portefeuilles et favoris)."""
    if not isinstance(data, dict):
        return {"portfolios": {"Banque Principale": []}, "favoris": [], "watchlist": []}
    
    favoris = data.get("favoris", [])
    if not isinstance(favoris, list):
        favoris = []
    favoris = [str(s) for s in favoris if isinstance(s, (str, int))]
    watchlist = data.get("watchlist", [])
    if not isinstance(watchlist, list):
        watchlist = []
    watchlist = list(dict.fromkeys(str(s) for s in watchlist if isinstance(s, (str, int))))

    raw_portfolios = data.get("portfolios", data if "Banque Principale" in data or len(data) > 0 else {"Banque Principale": []})
    if not isinstance(raw_portfolios, dict):
        raw_portfolios = {"Banque Principale": []}
    
    cleaned_portfolios = {}
    for bank_name, items in raw_portfolios.items():
        if bank_name in {"favoris", "watchlist"}:
            continue
        if not isinstance(bank_name, str) or not bank_name.strip():
            continue
        if not isinstance(items, list):
            items = []
        
        valid_items = []
        for item in items:
            if isinstance(item, dict) and "name" in item and "symbol" in item:
                try:
                    item["qty"] = float(item.get("qty", 0.0))
                    item["invested_eur"] = float(item.get("invested_eur", 0.0))
                    item["fees_eur"] = float(item.get("fees_eur", 0.0))
                    item["entry_price"] = float(item.get("entry_price", 0.0))
                    valid_items.append(item)
                except (ValueError, TypeError):
                    continue
        cleaned_portfolios[bank_name.strip()] = valid_items
        
    if not cleaned_portfolios:
        cleaned_portfolios = {"Banque Principale": []}

    return {"portfolios": cleaned_portfolios, "favoris": favoris, "watchlist": watchlist}

def load_app_data():
    data = None
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            st.warning(f"⚠️ Fichier principal corrompu détecté ({e}). Tentative de récupération via la copie de secours...")
            if os.path.exists(BACKUP_FILE):
                try:
                    with open(BACKUP_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    pass

    if data is None and os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    if data is None:
        data = {"portfolios": {"Banque Principale": []}, "favoris": [], "watchlist": []}

    return validate_app_data(data)

def save_app_data(app_data):
    """Sauvegarde JSON atomique; conserve une copie du dernier fichier valide."""
    validated_data = validate_app_data(app_data)
    temp_path = None
    try:
        directory = os.path.dirname(os.path.abspath(PORTFOLIO_FILE))
        fd, temp_path = tempfile.mkstemp(prefix=".portefeuille_", suffix=".tmp", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(validated_data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        # Ne remplace la sauvegarde de secours qu'après avoir vérifié le JSON existant.
        if os.path.exists(PORTFOLIO_FILE):
            try:
                with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                    json.load(f)
                shutil.copy2(PORTFOLIO_FILE, BACKUP_FILE)
            except (OSError, json.JSONDecodeError):
                pass

        os.replace(temp_path, PORTFOLIO_FILE)
        temp_path = None
        st.session_state.app_data = validated_data
        return True
    except Exception as e:
        st.error(f"❌ Erreur critique lors de la sauvegarde : {e}")
        return False
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

if "app_data" not in st.session_state:
    st.session_state.app_data = load_app_data()

# --- Menu de configuration des fournisseurs de données ---
_PROVIDER_DEFAULTS = {
    "Yahoo Finance": True,
    "Stooq": True,
    "Twelve Data": True,
    "Finnhub": True,
    "EODHD": True,
}
_PROVIDER_FALLBACKS = ["Stooq", "Twelve Data", "Finnhub", "EODHD"]
_API_SECRET_NAMES = {
    "Twelve Data": "TWELVE_DATA_API_KEY",
    "Finnhub": "FINNHUB_API_KEY",
    "EODHD": "EODHD_API_KEY",
}
if "provider_config_applied" not in st.session_state:
    st.session_state.provider_config_applied = {
        "enabled": dict(_PROVIDER_DEFAULTS),
        "order": list(_PROVIDER_FALLBACKS),
    }
for _provider, _enabled in _PROVIDER_DEFAULTS.items():
    st.session_state.setdefault(f"provider_ui_enabled_{_provider}", _enabled)
if "saved_api_keys" not in st.session_state:
    st.session_state.saved_api_keys = load_saved_api_keys()
for _secret_name in _API_SECRET_NAMES.values():
    _initial_key = st.session_state.saved_api_keys.get(_secret_name, "")
    if not _initial_key:
        try:
            _initial_key = st.secrets.get(_secret_name, "")
        except Exception:
            _initial_key = os.getenv(_secret_name, "")
    st.session_state.setdefault(f"provider_api_input_{_secret_name}", _initial_key or "")
st.session_state.setdefault("provider_ui_order", list(_PROVIDER_FALLBACKS))

def restore_api_configuration():
    """Restaure les clés déjà enregistrées et remet les paramètres fournisseurs par défaut."""
    saved = load_saved_api_keys()
    restored_keys = {}
    for secret_name in _API_SECRET_NAMES.values():
        value = str(saved.get(secret_name, "") or "").strip()
        if not value:
            try:
                value = str(st.secrets.get(secret_name, "") or "").strip()
            except Exception:
                value = str(os.getenv(secret_name, "") or "").strip()
        restored_keys[secret_name] = value
        st.session_state[f"provider_api_input_{secret_name}"] = value

    st.session_state.saved_api_keys = {k: v for k, v in saved.items() if v}
    st.session_state.provider_ui_order = list(_PROVIDER_FALLBACKS)
    st.session_state.provider_config_applied = {
        "enabled": dict(_PROVIDER_DEFAULTS),
        "order": list(_PROVIDER_FALLBACKS),
    }
    for provider, enabled in _PROVIDER_DEFAULTS.items():
        st.session_state[f"provider_ui_enabled_{provider}"] = enabled
    try:
        st.cache_data.clear()
    except Exception:
        pass
    st.session_state.api_restore_message = (
        "Configuration API restaurée. Les clés proviennent du fichier enregistré, "
        "puis des Secrets Streamlit ou des variables d’environnement. "
        "Une clé perdue et absente de ces sources ne peut pas être recréée."
    )
    st.session_state.api_restore_key_count = sum(bool(v) for v in restored_keys.values())


with st.sidebar.expander("🔌 Fournisseurs de cours & API", expanded=False):
    st.caption("Activez les sources et renseignez vos clés API. Yahoo Finance reste la source principale si activée.")
    if st.button("♻️ Restaurer les clés et paramètres API", key="restore_api_configuration", use_container_width=True,
                  help="Recharge les clés déjà sauvegardées ou présentes dans les Secrets Streamlit/l’environnement, et rétablit les fournisseurs par défaut."):
        restore_api_configuration()
        st.success(st.session_state.api_restore_message)
        st.info(f"Clés retrouvées : {st.session_state.api_restore_key_count} sur {len(_API_SECRET_NAMES)}.")

    for _provider in _PROVIDER_DEFAULTS:
        st.checkbox(_provider, key=f"provider_ui_enabled_{_provider}")
    st.markdown("**Clés API (facultatives)**")
    for _provider, _secret_name in _API_SECRET_NAMES.items():
        st.text_input(
            f"Clé API — {_provider}",
            key=f"provider_api_input_{_secret_name}",
            type="password",
            help=f"La clé peut être sauvegardée localement avec le bouton ci-dessous. Variable/secret compatible : {_secret_name}."
        )
    _save_col, _clear_col = st.columns(2)
    with _save_col:
        if st.button("💾 Sauvegarder les clés API", key="save_provider_api_keys", use_container_width=True):
            _keys_to_save = {
                name: st.session_state.get(f"provider_api_input_{name}", "").strip()
                for name in _API_SECRET_NAMES.values()
            }
            if save_api_keys(_keys_to_save):
                st.session_state.saved_api_keys = {k: v for k, v in _keys_to_save.items() if v}
                st.success("Clés API sauvegardées sur cet ordinateur/serveur.")
            else:
                st.error("Impossible de sauvegarder les clés API. Vérifiez les droits d’écriture du dossier.")
    with _clear_col:
        if st.button("🗑️ Effacer les clés sauvegardées", key="clear_provider_api_keys", use_container_width=True):
            if save_api_keys({}):
                st.session_state.saved_api_keys = {}
                for _secret_name in _API_SECRET_NAMES.values():
                    st.session_state[f"provider_api_input_{_secret_name}"] = ""
                st.success("Clés API locales effacées.")
            else:
                st.error("Impossible d’effacer le fichier des clés API.")
    st.caption("Sécurité : les clés sont enregistrées dans un fichier local non chiffré. Ne partagez pas ce fichier et ne l’ajoutez pas à Git. Sur Streamlit Cloud, le disque peut être éphémère : utilisez plutôt les Secrets de Streamlit.")
    st.multiselect(
        "Ordre des fournisseurs de secours",
        options=_PROVIDER_FALLBACKS,
        key="provider_ui_order",
        help="Sélectionnez les fournisseurs dans l’ordre souhaité. Les sources désactivées seront ignorées."
    )
    if st.button("Appliquer la configuration", key="apply_provider_config", use_container_width=True):
        st.session_state.provider_config_applied = {
            "enabled": {
                provider: bool(st.session_state.get(f"provider_ui_enabled_{provider}", True))
                for provider in _PROVIDER_DEFAULTS
            },
            "order": list(st.session_state.get("provider_ui_order", _PROVIDER_FALLBACKS)),
        }
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.success("Configuration appliquée.")
    _applied = st.session_state.provider_config_applied
    st.caption("Configuration active : " + ("Yahoo Finance, " if _applied["enabled"].get("Yahoo Finance", True) else "") + ", ".join(p for p in _applied["order"] if _applied["enabled"].get(p, True)))

# --- Récupération sécurisée du Sentiment du Marché ---
@st.cache_data(ttl=300)
def get_crypto_fear_and_greed():
    try:
        url = "https://api.alternative.me/fng/"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            res_data = json.loads(response.read().decode())
            val = int(res_data['data'][0]['value'])
            classification = res_data['data'][0]['value_classification']
            return val, classification
    except Exception:
        return 50, "Neutre"

@st.cache_data(ttl=300)
def get_stock_market_sentiment():
    try:
        vix = yf.Ticker("^VIX").history(period="5d")
        if not vix.empty:
            vix_close = float(vix['Close'].iloc[-1])
            if vix_close >= 30:
                return int(max(5, 100 - vix_close * 2.5)), "Peur Extrême 😱"
            elif vix_close >= 22:
                return int(100 - vix_close * 2.2), "Peur 😨"
            elif vix_close >= 15:
                return int(100 - vix_close * 2.0), "Neutre 🙂"
            else:
                return int(min(95, 100 - vix_close * 1.8)), "Avidité 🤑"
    except Exception:
        pass
    return 50, "Neutre 🙂"

@st.cache_data(ttl=300)
def get_vix_history():
    try:
        vix = yf.Ticker("^VIX")
        df = vix.history(period="6mo")
        if not df.empty:
            return df
    except Exception:
        pass
    return None

# Base de données d'actifs
assets_db = [
    {"name": "EUR/USD", "type": "Forex", "symbol": "EURUSD=X", "liquidity": 2, "volatility": 2, "trend": 1, "risk_reward": 1, "catalyst": 0},
    {"name": "GBP/USD", "type": "Forex", "symbol": "GBPUSD=X", "liquidity": 2, "volatility": 2, "trend": -1, "risk_reward": 1, "catalyst": 0},
    {"name": "USD/JPY", "type": "Forex", "symbol": "USDJPY=X", "liquidity": 2, "volatility": 2, "trend": 3, "risk_reward": 3, "catalyst": 2},
    {"name": "EUR/GBP", "type": "Forex", "symbol": "EURGBP=X", "liquidity": 2, "volatility": 1, "trend": 0, "risk_reward": 1, "catalyst": 0},
    {"name": "EUR/CHF", "type": "Forex", "symbol": "EURCHF=X", "liquidity": 2, "volatility": 1, "trend": 0, "risk_reward": 1, "catalyst": 0},
    {"name": "Apple (AAPL)", "type": "Actions US", "symbol": "AAPL", "liquidity": 2, "volatility": 2, "trend": 3, "risk_reward": 1, "catalyst": 2},
    {"name": "Nvidia (NVDA)", "type": "Actions US", "symbol": "NVDA", "liquidity": 2, "volatility": -2, "trend": 3, "risk_reward": 3, "catalyst": 2},
    {"name": "Tesla (TSLA)", "type": "Actions US", "symbol": "TSLA", "liquidity": 2, "volatility": -2, "trend": -1, "risk_reward": -3, "catalyst": -2},
    {"name": "Microsoft (MSFT)", "type": "Actions US", "symbol": "MSFT", "liquidity": 2, "volatility": 2, "trend": 3, "risk_reward": 2, "catalyst": 1},
    {"name": "Amazon (AMZN)", "type": "Actions US", "symbol": "AMZN", "liquidity": 2, "volatility": 2, "trend": 3, "risk_reward": 2, "catalyst": 1},
    {"name": "Alphabet / Google (GOOGL)", "type": "Actions US", "symbol": "GOOGL", "liquidity": 2, "volatility": 2, "trend": 2, "risk_reward": 1, "catalyst": 1},
    {"name": "Meta Platforms (META)", "type": "Actions US", "symbol": "META", "liquidity": 2, "volatility": 2, "trend": 3, "risk_reward": 2, "catalyst": 2},
    {"name": "Netflix (NFLX)", "type": "Actions US", "symbol": "NFLX", "liquidity": 2, "volatility": -2, "trend": 2, "risk_reward": 1, "catalyst": 1},
    {"name": "AMD", "type": "Actions US", "symbol": "AMD", "liquidity": 2, "volatility": -2, "trend": 1, "risk_reward": 1, "catalyst": 0},
    {"name": "TotalEnergies", "type": "Actions FR", "symbol": "TTE.PA", "liquidity": 1, "volatility": 0, "trend": 1, "risk_reward": 1, "catalyst": 0},
    {"name": "LVMH", "type": "Actions FR", "symbol": "MC.PA", "liquidity": 1, "volatility": 2, "trend": -3, "risk_reward": -3, "catalyst": -2},
    {"name": "Airbus", "type": "Actions FR", "symbol": "AIR.PA", "liquidity": 1, "volatility": 1, "trend": 2, "risk_reward": 2, "catalyst": 1},
    {"name": "Schneider Electric", "type": "Actions FR", "symbol": "SU.PA", "liquidity": 1, "volatility": 1, "trend": 3, "risk_reward": 2, "catalyst": 1},
    {"name": "Sanofi", "type": "Actions FR", "symbol": "SAN.PA", "liquidity": 1, "volatility": 0, "trend": 1, "risk_reward": 1, "catalyst": 0},
    {"name": "BNP Paribas", "type": "Actions FR", "symbol": "BNP.PA", "liquidity": 1, "volatility": 2, "trend": 1, "risk_reward": 1, "catalyst": 0},
    {"name": "Hermès", "type": "Actions FR", "symbol": "RMS.PA", "liquidity": 1, "volatility": 1, "trend": 2, "risk_reward": 2, "catalyst": 1},
    {"name": "AXA", "type": "Actions FR", "symbol": "CS.PA", "liquidity": 1, "volatility": 0, "trend": 1, "risk_reward": 1, "catalyst": 0},
    {"name": "Orange", "type": "Actions FR", "symbol": "ORA.PA", "liquidity": 1, "volatility": 0, "trend": 0, "risk_reward": 1, "catalyst": 0},
    {"name": "Stellantis", "type": "Actions FR", "symbol": "STLAP.PA", "liquidity": 1, "volatility": -2, "trend": -1, "risk_reward": -1, "catalyst": -1},
    {"name": "CAC 40", "type": "Indices", "symbol": "^FCHI", "liquidity": 2, "volatility": 0, "trend": 0, "risk_reward": 1, "catalyst": 0},
    {"name": "DAX 40 (Allemagne)", "type": "Indices", "symbol": "^GDAXI", "liquidity": 2, "volatility": 1, "trend": 2, "risk_reward": 2, "catalyst": 1},
    {"name": "Euro Stoxx 50", "type": "Indices", "symbol": "^STOXX50E", "liquidity": 2, "volatility": 0, "trend": 1, "risk_reward": 1, "catalyst": 0},
    {"name": "S&P 500", "type": "Indices", "symbol": "^GSPC", "liquidity": 2, "volatility": 2, "trend": 3, "risk_reward": 3, "catalyst": 0},
    {"name": "Nasdaq 100", "type": "Indices", "symbol": "^NDX", "liquidity": 2, "volatility": 2, "trend": 3, "risk_reward": 1, "catalyst": 2},
    {"name": "Dow Jones", "type": "Indices", "symbol": "^DJI", "liquidity": 2, "volatility": 1, "trend": 2, "risk_reward": 2, "catalyst": 0},
    {"name": "Bitcoin (BTC)", "type": "Cryptos", "symbol": "BTC-USD", "liquidity": 1, "volatility": 2, "trend": 3, "risk_reward": 3, "catalyst": 2},
    {"name": "Ethereum (ETH)", "type": "Cryptos", "symbol": "ETH-USD", "liquidity": 1, "volatility": 2, "trend": 1, "risk_reward": 1, "catalyst": 0},
    {"name": "Solana (SOL)", "type": "Cryptos", "symbol": "SOL-USD", "liquidity": 1, "volatility": -2, "trend": 3, "risk_reward": 3, "catalyst": 2},
    {"name": "XRP", "type": "Cryptos", "symbol": "XRP-USD", "liquidity": 1, "volatility": -2, "trend": 1, "risk_reward": 1, "catalyst": 0},
    {"name": "Cardano (ADA)", "type": "Cryptos", "symbol": "ADA-USD", "liquidity": 1, "volatility": -2, "trend": 0, "risk_reward": 1, "catalyst": 0},
    {"name": "Or (XAU)", "type": "Matières Premières", "symbol": "GC=F", "liquidity": 2, "volatility": 2, "trend": 3, "risk_reward": 3, "catalyst": 2},
    {"name": "Argent (Silver)", "type": "Matières Premières", "symbol": "SI=F", "liquidity": 2, "volatility": -2, "trend": 2, "risk_reward": 2, "catalyst": 1},
    {"name": "Pétrole Brent", "type": "Matières Premières", "symbol": "BZ=F", "liquidity": 2, "volatility": -2, "trend": -1, "risk_reward": 1, "catalyst": 0},
    {"name": "Cuivre (Copper)", "type": "Matières Premières", "symbol": "HG=F", "liquidity": 2, "volatility": 1, "trend": 1, "risk_reward": 1, "catalyst": 0}
]

def _clean_ohlcv_frame(df):
    """Normalise un historique OHLCV et élimine les lignes inutilisables."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    frame = df.copy()
    # Harmonise les noms de colonnes entre fournisseurs.
    frame.columns = [str(c).strip().title() for c in frame.columns]
    if "Datetime" in frame.columns and "Date" not in frame.columns:
        frame = frame.rename(columns={"Datetime": "Date"})
    required = ["Close"]
    if not all(col in frame.columns for col in required):
        return None
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col not in frame.columns:
            frame[col] = np.nan
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["Close"])
    frame = frame[frame["Close"] > 0]
    if frame.empty:
        return None
    # Les indicateurs ATR ont besoin de High/Low; repli prudent si absents.
    frame["High"] = frame["High"].fillna(frame["Close"])
    frame["Low"] = frame["Low"].fillna(frame["Close"])
    return frame.sort_index()


def _get_stooq_history(symbol):
    """Stooq en secours pour les actions US simples; pas d'approximation de symbole."""
    # Les suffixes, indices, devises, contrats futures et cryptos ne sont pas
    # convertis automatiquement: un mauvais mapping serait plus dangereux qu'un échec.
    if not symbol or any(ch in symbol for ch in ".^=-/ "):
        return None
    stooq_symbol = urllib.parse.quote(symbol.lower() + ".us", safe="")
    url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=5) as response:
        raw = response.read().decode("utf-8", errors="replace")
    if not raw or "No data" in raw or raw.count("\n") < 2:
        return None
    frame = pd.read_csv(io.StringIO(raw), parse_dates=["Date"], index_col="Date")
    return _clean_ohlcv_frame(frame)


def _get_api_key(secret_name):
    """Lit d’abord la clé saisie dans le menu, puis Streamlit Secrets/env."""
    try:
        value = st.session_state.get(f"provider_api_input_{secret_name}", "")
    except Exception:
        value = ""
    if value:
        return value.strip()
    try:
        value = st.secrets.get(secret_name, "")
    except Exception:
        value = ""
    return value or os.getenv(secret_name, "")


def _http_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _get_twelve_data_history(symbol):
    """Historique journalier Twelve Data; nécessite TWELVE_DATA_API_KEY."""
    api_key = _get_api_key("TWELVE_DATA_API_KEY")
    if not api_key or not symbol:
        return None
    # Les symboles multi-marchés peuvent nécessiter une notation Twelve Data spécifique.
    params = urllib.parse.urlencode({
        "symbol": symbol, "interval": "1day", "outputsize": 5000,
        "apikey": api_key
    })
    payload = _http_json(f"https://api.twelvedata.com/time_series?{params}")
    values = payload.get("values")
    if not isinstance(values, list) or not values:
        return None
    frame = pd.DataFrame(values).rename(columns={
        "datetime": "Date", "open": "Open", "high": "High",
        "low": "Low", "close": "Close", "volume": "Volume"
    })
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.set_index("Date").sort_index()
    return _clean_ohlcv_frame(frame)


def _get_finnhub_history(symbol):
    """Bougies journalières Finnhub; nécessite FINNHUB_API_KEY."""
    api_key = _get_api_key("FINNHUB_API_KEY")
    if not api_key or not symbol or symbol.startswith("^"):
        return None
    import time
    to_ts = int(time.time())
    from_ts = to_ts - 10 * 365 * 24 * 60 * 60
    params = urllib.parse.urlencode({
        "symbol": symbol, "resolution": "D", "from": from_ts,
        "to": to_ts, "token": api_key
    })
    payload = _http_json(f"https://finnhub.io/api/v1/stock/candle?{params}")
    if payload.get("s") != "ok" or not payload.get("c"):
        return None
    frame = pd.DataFrame({
        "Date": pd.to_datetime(payload.get("t", []), unit="s", errors="coerce"),
        "Open": payload.get("o", []), "High": payload.get("h", []),
        "Low": payload.get("l", []), "Close": payload.get("c", []),
        "Volume": payload.get("v", [])
    }).set_index("Date").sort_index()
    return _clean_ohlcv_frame(frame)


def _get_eodhd_history(symbol):
    """Historique journalier EODHD; nécessite EODHD_API_KEY."""
    api_key = _get_api_key("EODHD_API_KEY")
    if not api_key or not symbol:
        return None
    # EODHD utilise généralement EXCHANGE ticker (ex. AAPL.US, AIR.PA).
    # Les symboles Yahoo avec préfixe ^ ou suffixes de contrats ne sont pas convertis.
    if symbol.startswith("^") or symbol.endswith("=F"):
        return None
    from datetime import date, timedelta
    date_from = (date.today() - timedelta(days=365 * 10)).isoformat()
    params = urllib.parse.urlencode({
        "api_token": api_key, "fmt": "json", "period": "d", "from": date_from
    })
    encoded_symbol = urllib.parse.quote(symbol, safe=".")
    payload = _http_json(f"https://eodhd.com/api/eod/{encoded_symbol}?{params}")
    if not isinstance(payload, list) or not payload:
        return None
    frame = pd.DataFrame(payload).rename(columns={
        "date": "Date", "open": "Open", "high": "High",
        "low": "Low", "close": "Close", "volume": "Volume"
    })
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.set_index("Date").sort_index()
    return _clean_ohlcv_frame(frame)


@st.cache_data(ttl=60)
def get_market_indicators(symbol, period="1y", interval="1d"):
    """Essaie Yahoo Finance, puis Stooq, Twelve Data, Finnhub et EODHD en secours.

    Les sources de secours sont réservées aux bougies journalières pour éviter de
    mélanger silencieusement des fréquences ou de présenter un cours retardé comme temps réel.
    Les API payantes/gratuites optionnelles ne sont appelées que si leur clé est configurée.
    """
    candidates = []
    errors = []

    # Configuration active du menu latéral. Yahoo est la seule source intraday.
    provider_config = st.session_state.get("provider_config_applied", {})
    enabled = provider_config.get("enabled", _PROVIDER_DEFAULTS)
    fallback_order = provider_config.get("order", _PROVIDER_FALLBACKS)

    # 1) Yahoo Finance, source principale si activée.
    if enabled.get("Yahoo Finance", True):
        try:
            ticker = yf.Ticker(symbol)
            df_yahoo = ticker.history(period=period, interval=interval, auto_adjust=False)
            df_yahoo = _clean_ohlcv_frame(df_yahoo)
            # Yahoo ne fournit pas toujours une bougie 4h; repli vers 1h uniquement intraday.
            if (df_yahoo is None or df_yahoo.empty) and interval in ("1h", "4h"):
                df_yahoo = _clean_ohlcv_frame(
                    ticker.history(period="1mo", interval="1h", auto_adjust=False)
                )
            if df_yahoo is not None and len(df_yahoo) >= 5:
                df_yahoo.attrs["source"] = "Yahoo Finance"
                candidates.append(df_yahoo)
        except Exception as exc:
            errors.append(f"Yahoo Finance: {type(exc).__name__}")

    # Les fournisseurs de secours sont réservés aux historiques journaliers.
    is_daily = interval in ("1d", "5d", "1wk", "1mo", "3mo")
    provider_functions = {
        "Stooq": _get_stooq_history,
        "Twelve Data": _get_twelve_data_history,
        "Finnhub": _get_finnhub_history,
        "EODHD": _get_eodhd_history,
    }
    if not candidates and is_daily:
        for provider_name in fallback_order:
            provider_fn = provider_functions.get(provider_name)
            if provider_fn is None or not enabled.get(provider_name, True):
                continue
            try:
                fallback_df = provider_fn(symbol)
                if fallback_df is not None and len(fallback_df) >= 5:
                    # Applique une fenêtre comparable à la demande initiale.
                    if period.endswith("y") and period[:-1].isdigit():
                        cutoff = pd.Timestamp.now(tz=None) - pd.Timedelta(days=365 * int(period[:-1]))
                        idx = pd.to_datetime(fallback_df.index, errors="coerce")
                        fallback_df = fallback_df.loc[idx >= cutoff]
                    elif period.endswith("mo") and period[:-2].isdigit():
                        cutoff = pd.Timestamp.now(tz=None) - pd.Timedelta(days=30 * int(period[:-2]))
                        idx = pd.to_datetime(fallback_df.index, errors="coerce")
                        fallback_df = fallback_df.loc[idx >= cutoff]
                    fallback_df = _clean_ohlcv_frame(fallback_df)
                    if fallback_df is not None and len(fallback_df) >= 5:
                        fallback_df.attrs["source"] = provider_name
                        candidates.append(fallback_df)
                        break
            except Exception as exc:
                errors.append(f"{provider_name}: {type(exc).__name__}")

    if not candidates:
        return None, float("nan"), float("nan"), 50.0, float("nan"), None

    df = candidates[0]
    try:
        current_price = float(df["Close"].iloc[-1])
        if not np.isfinite(current_price) or current_price <= 0:
            return None, float("nan"), float("nan"), 50.0, float("nan"), None

        close = pd.to_numeric(df["Close"], errors="coerce")
        sma_200_value = close.rolling(window=200, min_periods=200).mean().iloc[-1]
        sma_200 = float(sma_200_value) if pd.notna(sma_200_value) else float("nan")
        sma_50_value = close.rolling(window=50, min_periods=50).mean().iloc[-1]
        sma_50 = float(sma_50_value) if pd.notna(sma_50_value) else float("nan")

        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi_series = 100 - (100 / (1 + rs))
        rsi_14 = float(rsi_series.iloc[-1]) if not rsi_series.empty and pd.notna(rsi_series.iloc[-1]) else 50.0

        high_low = df["High"] - df["Low"]
        high_close = np.abs(df["High"] - close.shift())
        low_close = np.abs(df["Low"] - close.shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr_value = true_range.rolling(window=14, min_periods=14).mean().iloc[-1]
        atr_14 = float(atr_value) if pd.notna(atr_value) else float("nan")
        if not np.isfinite(atr_14) or atr_14 <= 0:
            atr_14 = current_price * 0.015
        return current_price, sma_200, sma_50, rsi_14, atr_14, df
    except Exception:
        return None, float("nan"), float("nan"), 50.0, float("nan"), None

def compute_trading_setup(current_price, atr, scores, sma_200, sma_50, rsi_14):
    if current_price is None or not np.isfinite(current_price) or current_price <= 0:
        raise ValueError("Cours de marché indisponible ou invalide; analyse annulée.")
    if atr is None or not np.isfinite(atr) or atr <= 0:
        atr = current_price * 0.015
    if sma_200 is None or not np.isfinite(sma_200):
        sma_200 = float('nan')
    if sma_50 is None or not np.isfinite(sma_50):
        sma_50 = float('nan')
    if rsi_14 is None or not np.isfinite(rsi_14):
        rsi_14 = 50.0

    weighted_score = (
        scores["t"] * 2.5 +
        scores["r"] * 2.0 +
        scores["v"] * 1.0 +
        scores["c"] * 1.0 +
        scores["l"] * 0.5
    )
    
    percentage_score = int(((weighted_score + 18) / 36) * 100)
    percentage_score = max(0, min(100, percentage_score))

    trend_bullish = bool(np.isfinite(sma_200) and np.isfinite(sma_50) and current_price > sma_200 and sma_50 > sma_200)

    # Le score est un indicateur heuristique, pas une probabilité de réussite.
    if not trend_bullish:
        percentage_score = min(percentage_score, 54)
    if rsi_14 > 78:
        percentage_score = min(percentage_score, 54)

    if percentage_score >= 75:
        signal = "ACHAT FORT"
    elif percentage_score >= 55:
        signal = "ACHAT"
    else:
        signal = "NEUTRE / ÉVITER"

    # Stratégie strictement long-only : niveaux de risque/rendement orientés à la hausse.
    entry = current_price * 0.998
    sl = entry - (1.5 * atr)
    tp_ct = entry + (2.0 * atr)
    tp_lt = entry + (4.5 * atr)

    daily_move = atr if atr > 0 else (current_price * 0.01)
    
    diff_ct = abs(tp_ct - entry)
    diff_lt = abs(tp_lt - entry)
    
    days_ct = max(1, round(diff_ct / daily_move)) if not np.isnan(diff_ct) and not np.isnan(daily_move) and daily_move > 0 else 1
    days_lt = max(1, round(diff_lt / daily_move)) if not np.isnan(diff_lt) and not np.isnan(daily_move) and daily_move > 0 else 1

    decimals = 4 if current_price < 10 else (2 if current_price < 500 else 1)
    return {
        "signal": signal,
        "score": percentage_score,
        "price": round(current_price, decimals),
        "entry": round(entry, decimals),
        "sl": round(sl, decimals),
        "tp_ct": round(tp_ct, decimals),
        "tp_lt": round(tp_lt, decimals),
        "days_ct": int(days_ct),
        "days_lt": int(days_lt),
        "sma_200": round(sma_200, decimals),
        "sma_50": round(sma_50, decimals),
        "rsi_14": round(rsi_14, 1),
        "atr": round(atr, decimals)
    }

def compute_opportunity_analysis(df, direction_mode="both_watch"):
    """Score technique directionnel sur 100; signal d'étude, jamais ordre automatique."""
    if df is None or not isinstance(df, pd.DataFrame) or len(df) < 35 or "Close" not in df:
        return None
    data = df.copy()
    close = pd.to_numeric(data["Close"], errors="coerce")
    high = pd.to_numeric(data.get("High", close), errors="coerce")
    low = pd.to_numeric(data.get("Low", close), errors="coerce")
    volume = pd.to_numeric(data.get("Volume", pd.Series(index=data.index, dtype=float)), errors="coerce")
    valid = close.notna() & (close > 0)
    close, high, low, volume = close[valid], high[valid], low[valid], volume[valid]
    if len(close) < 35:
        return None

    price = float(close.iloc[-1])
    sma20, sma50, sma200 = close.rolling(20).mean(), close.rolling(50).mean(), close.rolling(200).mean()
    ema12, ema26 = close.ewm(span=12, adjust=False).mean(), close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    rsi_delta = close.diff()
    avg_gain = rsi_delta.clip(lower=0).rolling(14).mean()
    avg_loss = -rsi_delta.clip(upper=0).rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100 - 100 / (1 + rs)
    rsi = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50.0

    prev_close = close.shift(1)
    tr = pd.concat([(high-low).abs(), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    atr_series = tr.rolling(14).mean()
    atr = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else price * 0.015
    atr_pct = atr / price * 100 if price else 0

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr_smooth = tr.rolling(14).mean().replace(0, np.nan)
    plus_di = 100 * plus_dm.rolling(14).mean() / atr_smooth
    minus_di = 100 * minus_dm.rolling(14).mean() / atr_smooth
    dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0, np.nan)
    adx = float(dx.rolling(14).mean().iloc[-1]) if len(dx) >= 28 and pd.notna(dx.rolling(14).mean().iloc[-1]) else 0.0
    pdi = float(plus_di.iloc[-1]) if pd.notna(plus_di.iloc[-1]) else 0.0
    mdi = float(minus_di.iloc[-1]) if pd.notna(minus_di.iloc[-1]) else 0.0

    avg_vol = volume.rolling(20).mean()
    vol_ratio = float(volume.iloc[-1] / avg_vol.iloc[-1]) if len(volume) and pd.notna(avg_vol.iloc[-1]) and avg_vol.iloc[-1] > 0 else 1.0
    last_return = float(close.pct_change().iloc[-1]) if len(close) >= 2 else 0.0
    # Le volume ne confirme un scénario que s'il accompagne le mouvement dans son sens.
    volume_up = vol_ratio >= 1.2 and last_return > 0
    volume_down = vol_ratio >= 1.2 and last_return < 0
    prior_high = float(high.shift(1).rolling(20).max().iloc[-1]) if len(high) >= 21 else price
    prior_low = float(low.shift(1).rolling(20).min().iloc[-1]) if len(low) >= 21 else price
    m20 = float(sma20.iloc[-1]) if pd.notna(sma20.iloc[-1]) else price
    m50 = float(sma50.iloc[-1]) if pd.notna(sma50.iloc[-1]) else price
    m200 = float(sma200.iloc[-1]) if pd.notna(sma200.iloc[-1]) else float("nan")
    macd_up = float(macd.iloc[-1]) > float(macd_signal.iloc[-1])
    macd_down = float(macd.iloc[-1]) < float(macd_signal.iloc[-1])
    breakout_up = price > prior_high
    breakout_down = price < prior_low
    pullback_up = price >= m50 and abs(price-m20) / price < 0.025 and rsi >= 42
    pullback_down = price <= m50 and abs(price-m20) / price < 0.025 and rsi <= 58
    trend_up = price > m50 and (not np.isfinite(m200) or m50 > m200)
    trend_down = price < m50 and (not np.isfinite(m200) or m50 < m200)
    # Score de confluence : tendance, momentum, ADX directionnel, volume confirmé,
    # structure, risque et pénalité si le cours est déjà trop étiré.
    def score_side(bull):
        trend = (int(price > m50) + int(m50 > m200 if np.isfinite(m200) else price > m50) + int(m20 > m50)) if bull else (int(price < m50) + int(m50 < m200 if np.isfinite(m200) else price < m50) + int(m20 < m50))
        trend_pts = trend / 3 * 25
        macd_ok = macd_up if bull else macd_down
        rsi_ok = (45 <= rsi <= 68) if bull else (32 <= rsi <= 55)
        momentum_pts = (12 if macd_ok else 0) + (8 if rsi_ok else (3 if (35 <= rsi <= 75) else 0))
        directional_strength = (pdi > mdi) if bull else (mdi > pdi)
        adx_pts = min(15, adx / 30 * 15) if directional_strength else 0
        directional_volume = volume_up if bull else volume_down
        volume_pts = 15 if directional_volume else (6 if vol_ratio >= 0.9 and directional_strength else 0)
        is_breakout = breakout_up if bull else breakout_down
        is_pullback = pullback_up if bull else pullback_down
        is_trend = trend_up if bull else trend_down
        structure_pts = 15 if is_breakout else (11 if is_pullback else (5 if is_trend else 0))
        distance_m20_pct = abs(price - m20) / price * 100 if price else 0
        penalty = min(10, max(0, distance_m20_pct - 4) * 2)
        if bull and rsi >= 75:
            penalty += 8
        elif (not bull) and rsi <= 25:
            penalty += 8
        risk_pts = 10 if 0.3 <= atr_pct <= 4.5 else (6 if atr_pct <= 7 else 1)
        if atr_pct < 0.2:
            risk_pts = 4
        total = int(round(trend_pts + momentum_pts + adx_pts + volume_pts + structure_pts + risk_pts - penalty))
        return min(100, max(0, total))

    long_score, short_score = score_side(True), score_side(False)

    # Le mode demandé doit réellement piloter le biais et les niveaux retournés.
    # both_watch compare les deux côtés; long/short forcent le scénario correspondant.
    mode = str(direction_mode or "both_watch").strip().lower().replace("-", "_").replace(" ", "_")
    mode_aliases = {
        "both": "both_watch", "both_watch": "both_watch", "watch_both": "both_watch",
        "long": "long", "long_only": "long", "achat": "long",
        "short": "short", "short_only": "short", "vente": "short",
    }
    mode = mode_aliases.get(mode, "both_watch")
    side = "LONG" if mode == "long" else "SHORT" if mode == "short" else ("LONG" if long_score >= short_score else "SHORT")

    if side == "LONG":
        score = long_score
        setup = "Cassure haussière" if breakout_up else ("Repli en tendance haussière" if pullback_up else "Tendance haussière")
        entry, stop, target1, target2 = price, price - 1.5*atr, price + 2*atr, price + 3*atr
        rmult = (target1-entry) / max(entry-stop, 1e-12)
    else:
        score = short_score
        setup = "Cassure baissière" if breakout_down else ("Repli en tendance baissière" if pullback_down else "Tendance baissière")
        entry, stop, target1, target2 = price, price + 1.5*atr, price - 2*atr, price - 3*atr
        rmult = (entry-target1) / max(stop-entry, 1e-12)

    if score >= 80:
        quality = "Configuration forte à étudier"
    elif score >= 65:
        quality = "Opportunité à surveiller"
    elif score >= 50:
        quality = "Configuration en formation"
    else:
        quality = "Signal faible"
    # Les positions short sont seulement signalées: aucune exécution n'est possible.
    signal = f"{side} — {quality}" if score >= 50 else "NEUTRE — pas de configuration claire"
    return {
        "score": score, "long_score": long_score, "short_score": short_score,
        "direction_mode": mode, "side": side, "signal": signal, "setup": setup, "price": price,
        "entry": entry, "sl": stop, "tp_ct": target1, "tp_lt": target2,
        "rsi": rsi, "adx": adx, "volume_ratio": vol_ratio,
        "atr_pct": atr_pct, "rr": rmult, "macd": "Haussier" if macd_up else "Baissier",
        "breakout": "Oui" if (breakout_up if side == "LONG" else breakout_down) else "Non",
        "volume_confirme": "Oui" if (volume_up if side == "LONG" else volume_down) else "Non",
        "distance_moyenne20_pct": round(abs(price - m20) / price * 100, 2) if price else 0,
        "sma20": m20, "sma50": m50, "sma200": m200,
    }


def estimate_target_time(timeframe_label, target_multiple):
    """Estimation théorique en bougies ATR, pas une prévision ni un compte à rebours."""
    bars = max(1, int(round(float(target_multiple))))
    units = {
        "15 minutes": (15, "minute", "minutes"),
        "1 heure": (1, "heure", "heures"),
        "4 heures (agrégé)": (4, "heure", "heures"),
        "1 jour": (1, "jour de bourse", "jours de bourse"),
        "1 semaine": (1, "semaine", "semaines"),
        "1 mois": (1, "mois", "mois"),
    }
    unit_count, singular, plural = units.get(timeframe_label, (1, "bougie", "bougies"))
    amount = bars * unit_count
    if timeframe_label == "15 minutes":
        return f"~{amount} min"
    if timeframe_label in ("1 heure", "4 heures (agrégé)"):
        return f"~{amount} h"
    return f"~{amount} {singular if amount == 1 else plural}"


def plot_asset_chart(asset_name, df, levels):
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df.index, df['Close'], label="Prix (Clôture)", color="blue", linewidth=2)
    sma_200_series = df['Close'].rolling(window=200).mean()
    sma_50_series = df['Close'].rolling(window=50).mean()
    ax.plot(df.index, sma_200_series, label="SMA 200", color="orange", linestyle="--", linewidth=1.5)
    ax.plot(df.index, sma_50_series, label="SMA 50", color="purple", linestyle=":", linewidth=1.5)

    ax.axhline(y=float(levels["entry"]), color="gray", linestyle=":", label=f"Entrée: {levels['entry']}")
    ax.axhline(y=float(levels["sl"]), color="red", linestyle=":", label=f"Stop-Loss: {levels['sl']}")
    ax.axhline(y=float(levels["tp_ct"]), color="magenta", linestyle=":", label=f"TP CT: {levels['tp_ct']}")
    ax.axhline(y=float(levels["tp_lt"]), color="green", linestyle=":", label=f"TP LT: {levels['tp_lt']}")

    ax.set_title(f"Analyse Technique & Filtre de Tendance - {asset_name}")
    ax.legend(loc="upper left")
    ax.grid(True, linestyle="--", alpha=0.5)
    st.pyplot(fig)
    plt.close(fig)

# Titre
st.title("📈 Terminal de Trading & Gestion de Portefeuille")

# --- BOUTON D'AIDE & EXPLICATION DES PARAMÈTRES ---
with st.expander("📖 GUIDE D'UTILISATION & EXPLICATION DES PARAMÈTRES D'ENTRÉE", expanded=False):
    st.markdown("""
    ### 1. Comment utiliser le programme ?
    * **Scanner & Indicateurs (Onglet 1) :** Permet d'analyser en profondeur un actif sélectionné, de paramétrer ses notes qualitatives, de visualiser ses niveaux techniques et d'enregistrer vos ordres d'achat (ou plans DCA) dans votre banque.
    * **Screener Global (Onglet 2) :** Analyse les configurations LONG et SHORT sur plusieurs horizons, sans exécuter d’ordre automatiquement. Vous pouvez filtrer par catégorie ou score, voir les graphiques détaillés et **exporter vos résultats en Excel**.
    * **Mes Favoris (Onglet 3) :** Retrouvez rapidement vos actifs suivis en favoris avec un accès direct à leurs graphiques et liens TradingView.
    * **Banques & DCA (Onglet 4) :** Créez vos comptes ou portefeuilles virtuels, suivez la quantité d'unités détenues, le capital investi et supprimez des lignes si besoin.
    * **Mesure & Performance (Onglet 5) :** Évaluez en temps réel la plus ou moins-value globale de vos portefeuilles et votre **taux de réussite (win rate)**.
    * **Sauvegarde (Onglet 6) :** Téléchargez une sauvegarde JSON de vos données ou restaurez un fichier précédent en cas de besoin.

    ---

    ### 2. Explication des 5 Piliers d'Analyse (Paramètres d'Entrée sur le Marché)
    Dans l'onglet **Scanner**, 5 curseurs/menus vous permettent de pondérer l'actif selon des critères professionnels :
    1. **Liquidité (Poids : 0.5) :** Mesure la facilité à acheter ou vendre sans impacter le prix. 
       * *Valeur haute (+2)* = Actif ultra-liquide (Forex majeur, grandes actions).
    2. **Volatilité (Poids : 1.0) :** Mesure l'amplitude des variations de prix.
       * *Valeur haute (+2)* = Volatilité équilibrée et favorable ; *Négative (-2)* = Volatilité excessive ou risque de forte secousse.
    3. **Tendance (Poids : 2.5 — Le plus important) :** Évalue le sens directionnel du marché par rapport aux moyennes mobiles (SMA 50 et SMA 200) et au RSI.
       * *Valeur forte (+3)* = Tendance haussière puissante confirmée.
    4. **Risque / Rendement (Poids : 2.0) :** Estime si le potentiel de gain justifie le risque pris (basé sur l'indicateur de volatilité **ATR**).
    5. **Catalyseurs (Poids : 1.0) :** Intègre les éléments contextuels (publications de résultats d'entreprises, annonces de banques centrales, actualités sectorielles).

    ---

    ### 3. Comment sont calculés les Objectifs (Entrée, Stop-Loss, Take Profit) ?
    Le système utilise l'**ATR (Average True Range sur 14 périodes)** pour mesurer la respiration réelle de l'actif :
    * **Prix d'Entrée :** Légèrement optimisé sous le prix actuel en cas d'achat (`Prix × 0,998`) ou au-dessus en cas de vente.
    * **Stop-Loss (Sécurité) :** Placé à **1,5 ATR** de distance pour couper la position si le marché se retourne.
    * **Take Profit Court Terme (TP CT) :** Situé à **2,0 ATR** de l'entrée (~ objectif rapide).
    * **Take Profit Long Terme (TP LT) :** Situé à **4,5 ATR** de l'entrée (~ objectif de tendance étendu).
    * **Délais estimés :** Calculés en divisant la distance de l'objectif par le mouvement journalier moyen (ATR).
    """)

st.markdown("---")

# --- BANDEAU SUPERIEUR DE SENTIMENT DU MARCHE (SÉCURISÉ) ---
try:
    crypto_val, crypto_class = get_crypto_fear_and_greed()
    stock_val, stock_class = get_stock_market_sentiment()

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.subheader("🌐 Sentiment Bourse & Actions (VIX)")
        st.progress(stock_val / 100)
        st.write(f"**Indice de Confiance : {stock_val} / 100** — État : `{stock_class}`")

    with col_s2:
        st.subheader("🪙 Sentiment Cryptomonnaies (Fear & Greed)")
        st.progress(crypto_val / 100)
        st.write(f"**Indice Crypto : {crypto_val} / 100** — État : `{crypto_class}`")

    with st.expander("📉 Voir la courbe historique de l'Indice VIX (Volatilité / Peur sur 6 mois)", expanded=False):
        df_vix = get_vix_history()
        if df_vix is not None:
            fig_vix, ax_vix = plt.subplots(figsize=(10, 3))
            ax_vix.plot(df_vix.index, df_vix['Close'], color="crimson", linewidth=1.5, label="Indice VIX")
            ax_vix.axhline(y=20, color="orange", linestyle="--", alpha=0.7, label="Seuil de Crainte (20)")
            ax_vix.axhline(y=30, color="red", linestyle=":", alpha=0.7, label="Zone de Panique (30)")
            ax_vix.set_title("Évolution de la Peur du Marché (Indice VIX - 6 mois)", fontsize=10)
            ax_vix.legend(loc="upper left", fontsize=8)
            ax_vix.grid(True, linestyle="--", alpha=0.3)
            st.pyplot(fig_vix)
            plt.close(fig_vix)
        else:
            st.warning("Impossible de charger l'historique du VIX.")
except Exception:
    st.info("ℹ️ Indicateurs de sentiment momentanément indisponibles (le reste du terminal fonctionne normalement).")

st.markdown("---")

# Onglets
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "Scanner & Indicateurs", 
    "Screener Global", 
    "⭐ Mes Favoris",
    "Banques & DCA", 
    "📊 Mesure & Performance", 
    "💾 Sauvegarde & Restauration",
    "🤖 Portefeuille virtuel",
    "📋 Ma Watchlist"
])

with tab1:
    st.header("Analyse Détaillée d'un Actif")
    asset_names = [a["name"] for a in assets_db]
    selected_name = st.selectbox("Sélectionner l'actif :", asset_names, key="scanner_asset_select")
    selected_asset = next(a for a in assets_db if a["name"] == selected_name)

    is_favorite = selected_asset["symbol"] in st.session_state.app_data["favoris"]
    col_fav1, col_fav2 = st.columns([4, 1])
    with col_fav2:
        if is_favorite:
            if st.button("⭐ Retirer des favoris", key=f"fav_rem_{selected_asset['symbol']}", use_container_width=True):
                if selected_asset["symbol"] in st.session_state.app_data["favoris"]:
                    st.session_state.app_data["favoris"].remove(selected_asset["symbol"])
                    save_app_data(st.session_state.app_data)
                    st.success("Retiré des favoris !")
                    st.rerun()
        else:
            if st.button("☆ Ajouter aux favoris", key=f"fav_add_{selected_asset['symbol']}", use_container_width=True):
                if selected_asset["symbol"] not in st.session_state.app_data["favoris"]:
                    st.session_state.app_data["favoris"].append(selected_asset["symbol"])
                    save_app_data(st.session_state.app_data)
                    st.success("Ajouté aux favoris !")
                    st.rerun()

    live_price, sma_200, sma_50, rsi_14, atr_val, history_df = get_market_indicators(selected_asset["symbol"], period="1y", interval="1d")
    if live_price is None or not np.isfinite(live_price) or live_price <= 0:
        st.error("Impossible de récupérer un cours valide pour cet actif. Analyse et investissement désactivés pour éviter tout prix fictif.")
        st.stop()
    data_source = getattr(history_df, "attrs", {}).get("source", "fournisseur non identifié") if history_df is not None else "fournisseur non identifié"
    st.caption(f"Source des données : **{data_source}** — les fournisseurs de secours peuvent fournir des cours retardés ou uniquement journaliers.")

    tv_symbol = selected_asset["symbol"].replace("=X", "").replace("-USD", "USD").replace("=F", "")
    tv_url = f"https://www.tradingview.com/chart/?symbol={urllib.parse.quote(tv_symbol)}"
    st.markdown(f"🔗 **[Ouvrir cet actif sur TradingView]({tv_url})**", unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(label="Prix de marché (devise de cotation)", value=f"{live_price:,.2f}")
    col2.metric(label="ATR Réel (14)", value=f"{atr_val:,.4f}")
    col3.metric(label="SMA 50 / 200", value=f"{sma_50:,.1f} / {sma_200:,.1f}")
    col4.metric(label="RSI (14)", value=f"{rsi_14}")

    st.subheader("Paramétrage des 5 Piliers d'Analyse")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        liq = st.selectbox("1. Liquidité", [2, 1, -2], index=0 if selected_asset["liquidity"]==2 else 1, key="p1")
    with c2:
        vol = st.selectbox("2. Volatilité", [2, 0, -2], index=0 if selected_asset["volatility"]==2 else (1 if selected_asset["volatility"]==0 else 2), key="p2")
    with c3:
        trd = st.selectbox("3. Tendance", [3, 1, 0, -1, -3], index=2, key="p3")
    with c4:
        rr = st.selectbox("4. Risque/Rendement", [3, 1, -3], index=1, key="p4")
    with c5:
        cat = st.selectbox("5. Catalyseurs", [2, 0, -2], index=1, key="p5")

    scores = {"l": liq, "v": vol, "t": trd, "r": rr, "c": cat}
    result = compute_trading_setup(live_price, atr_val, scores, sma_200, sma_50, rsi_14)

    if result["score"] >= 75:
        st.success(f"🌟 **SIGNAL TECHNIQUE FORT (TENDANCE FILTRÉE)** — Score : {result['score']}/100")
    elif result["signal"] == "NEUTRE / ÉVITER":
        st.info(f"Signal : **{result['signal']}** (Score technique : {result['score']}/100)")
    else:
        st.info(f"Signal : **{result['signal']}** (Score : {result['score']}/100)")

    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    sc1.metric("Signal Global", result["signal"])
    sc2.metric("Score", f"{result['score']} / 100")
    sc3.metric("Entrée", result["entry"])
    sc4.metric("Stop-Loss", result["sl"])
    sc5.metric("TP Long Terme", result["tp_lt"])

    col_d1, col_d2 = st.columns(2)
    col_d1.metric("⏱️ Délai estimé TP Court Terme", f"~ {result['days_ct']} jour(s)")
    col_d2.metric("⏱️ Délai estimé TP Long Terme", f"~ {result['days_lt']} jour(s)")

    if st.checkbox("Afficher le graphique technique et les moyennes mobiles", key="chk_chart"):
        if history_df is not None:
            plot_asset_chart(selected_asset["name"], history_df, result)
        else:
            st.warning("Historique indisponible.")

    st.markdown("---")
    st.subheader("Enregistrer un achat simulé / Plan DCA indicatif")
    st.caption("Cette application suit un plan DCA mais n’exécute aucun ordre et ne déclenche pas automatiquement les achats futurs.")
    
    portfolios = st.session_state.app_data["portfolios"]
    if len(portfolios) > 0:
        bank_names = list(portfolios.keys())
        target_bank = st.selectbox("Banque / Compte cible :", bank_names, key="target_bank_ord")
        
        col_inv1, col_inv2 = st.columns(2)
        with col_inv1:
            budget_eur = st.number_input("Montant investi (€) :", min_value=1.0, value=50.0, step=5.0, key="budget_inv")
            pricing_mode = st.radio("Prix d'exécution :", ["Prix du marché en direct", "Prix d'entrée calculé"], key="pricing_mode")
        
        with col_inv2:
            frequency = st.selectbox("Fréquence (DCA) :", ["Achat unique (Manuel)", "1 fois par semaine", "2 fois par mois", "Tous les mois", "Tous les 3 mois"], key="freq_dca")
            fees_eur = st.number_input("Frais (€) :", min_value=0.0, value=1.0, step=0.5, key="fees_inv")

        # Le budget est en EUR alors que le cours peut être en USD/GBP/etc.
        # Sans taux FX explicite, ne pas simuler une quantité financièrement trompeuse.
        quote_currency = "EUR" if selected_asset["symbol"].endswith("=X") and selected_asset["symbol"].startswith("EUR") else ("USD" if selected_asset["symbol"].endswith("-USD") or selected_asset["symbol"].endswith("=F") else "UNKNOWN")
        if selected_asset["symbol"].endswith("=X"):
            quote_currency = selected_asset["symbol"].split("=")[0][-3:]
        elif selected_asset["symbol"].endswith(".L"):
            quote_currency = "GBP"
        elif selected_asset["symbol"].endswith(".PA") or selected_asset["symbol"].endswith(".DE") or selected_asset["symbol"].endswith(".AS"):
            quote_currency = "EUR"

        applied_price = live_price if pricing_mode == "Prix du marché en direct" else result["entry"]
        net_budget = max(0.0, budget_eur - fees_eur)
        currency_supported = quote_currency == "EUR"
        quantity_bought = net_budget / applied_price if currency_supported and applied_price > 0 else 0
        if not currency_supported:
            st.warning(f"Le cours de cet actif est probablement coté en {quote_currency}. La conversion EUR/ devise n'est pas encore fiable dans cette version : l'enregistrement simulé est désactivé pour éviter une quantité erronée.")
        else:
            st.write(f"**Synthèse :** Pour {budget_eur} € (frais: {fees_eur} €) -> **{quantity_bought:.4f} unités** de {selected_asset['name']} au prix de {applied_price:.4f} (cours en EUR).")

        if st.button("Valider l'Investissement", key="btn_validate_inv", disabled=not currency_supported):
            if budget_eur <= 0:
                st.error("❌ Le montant investi doit être supérieur à 0.")
            elif quantity_bought <= 0:
                st.error("❌ Le budget net après frais est insuffisant pour acquérir cet actif.")
            else:
                new_position = {
                    "name": selected_asset["name"],
                    "symbol": selected_asset["symbol"],
                    "qty": quantity_bought,
                    "invested_eur": budget_eur,
                    "fees_eur": fees_eur,
                    "entry_price": applied_price,
                    "frequency": frequency,
                    "sl": result["sl"],
                    "tp_ct": result["tp_ct"],
                    "tp_lt": result["tp_lt"],
                    "days_ct": result["days_ct"],
                    "days_lt": result["days_lt"],
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M")
                }
                portfolios[target_bank].append(new_position)
                if save_app_data(st.session_state.app_data):
                    st.success("✅ Investissement enregistré et sauvegardé en toute sécurité !")
                else:
                    st.error("❌ Erreur lors de la sauvegarde automatique.")
    else:
        st.warning("Veuillez d'abord créer une banque dans l'onglet 'Banques & DCA'.")

with tab2:
    st.header("Screener Global & Filtre temporel")
    st.info("💡 Sélectionnez l'horizon temporel de votre choix. Vous pouvez filtrer, trier et exporter vos résultats au format Excel.")
    
    # Les paramètres sont regroupés dans un formulaire : aucune analyse ne démarre
    # tant que l'utilisateur n'a pas cliqué sur « Lancer le screener ».
    with st.form("screener_config_form"):
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            timeframe_label = st.selectbox(
                "Horizon temporel :",
                ["15 minutes", "1 heure", "4 heures (agrégé)", "1 jour", "1 semaine", "1 mois"],
                key="tf_select"
            )
        with col_f2:
            filter_type = st.selectbox(
                "Catégorie :",
                ["Tous"] + sorted(set(a["type"] for a in assets_db)),
                key="filter_screener"
            )
        with col_f3:
            min_score = st.slider(
                "Score minimum des actifs à rechercher :",
                min_value=0, max_value=100, value=65, step=5,
                help="Seuls les actifs ayant un score égal ou supérieur à ce seuil seront affichés. 65 = opportunité à surveiller; 80 = configuration forte à étudier.",
                key="screener_min_score"
            )
        st.info("Mode directionnel : détection LONG et SHORT à étudier uniquement. Aucun ordre n'est envoyé automatiquement.")
        sort_order = st.selectbox(
            "Trier par :",
            ["Ordre par défaut", "Score (Plus élevé au plus bas)", "Meilleur compromis score / risque", "Nom (A-Z)"],
            key="sort_order_select"
        )
        launch_screener = st.form_submit_button(
            "🔎 Lancer le screener",
            type="primary",
            use_container_width=True
        )

    if launch_screener:
        st.session_state.screener_config = {
            "timeframe_label": timeframe_label,
            "filter_type": filter_type,
            "min_score": min_score,
            "sort_order": sort_order,
        }
        st.session_state.screener_has_run = True

    if not st.session_state.get("screener_has_run", False):
        st.info("Choisissez votre horizon, la catégorie et le score minimum, puis cliquez sur « Lancer le screener ».")
    else:
        # Utilise les derniers paramètres soumis : modifier le formulaire ne relance
        # pas l'analyse tant que le bouton n'a pas été pressé à nouveau.
        _cfg = st.session_state.get("screener_config", {})
        timeframe_label = _cfg.get("timeframe_label", timeframe_label)
        filter_type = _cfg.get("filter_type", filter_type)
        min_score = int(_cfg.get("min_score", min_score))
        sort_order = _cfg.get("sort_order", sort_order)

    if st.session_state.get("screener_has_run", False):
        tf_mapping = {
            "15 minutes": ("5d", "15m"),
            "1 heure": ("1mo", "1h"),
            "4 heures (agrégé)": ("1mo", "1h"),
            "1 jour": ("1y", "1d"),
            "1 semaine": ("2y", "1wk"),
            "1 mois": ("5y", "1mo"),
        }
        selected_period, selected_interval = tf_mapping[timeframe_label]

        st.markdown("---")

        screened_list = []
        excel_export_data = []
        unavailable_assets = []

        for asset in assets_db:
            if filter_type != "Tous" and asset["type"] != filter_type:
                continue
        
            p, sma_200, sma_50, rsi, atr_val, history_df_scr = get_market_indicators(asset["symbol"], period=selected_period, interval=selected_interval)
            if p is not None and np.isfinite(p) and p > 0 and history_df_scr is not None:
                # Le 4h est réellement agrégé depuis les bougies 1h, sans les mélanger.
                analysis_df = history_df_scr
                if timeframe_label == "4 heures (agrégé)":
                    analysis_df = history_df_scr.resample("4h").agg({
                        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
                    }).dropna(subset=["Close"])
                opp = compute_opportunity_analysis(analysis_df, direction_mode="both_watch")
                if opp is None:
                    unavailable_assets.append(asset["symbol"])
                    continue
                score_val = opp["score"]
                if score_val < min_score:
                    continue
                res = {
                    "signal": opp["signal"], "score": score_val, "price": round(opp["price"], 5),
                    "entry": round(opp["entry"], 5), "sl": round(opp["sl"], 5),
                    "tp_ct": round(opp["tp_ct"], 5), "tp_lt": round(opp["tp_lt"], 5),
                    "rsi_14": round(opp["rsi"], 1), "atr": round(opp["price"]*opp["atr_pct"]/100, 5),
                    "sma_50": round(opp["sma50"], 5), "sma_200": round(opp["sma200"], 5) if np.isfinite(opp["sma200"]) else float("nan"),
                    **opp
                }
                screened_list.append({"asset": asset, "res": res, "history_df": analysis_df})
                excel_export_data.append({
                    "Nom": asset["name"], "Ticker": asset["symbol"], "Catégorie": asset["type"],
                    "Horizon": timeframe_label, "Cours": res["price"], "Biais détecté": opp["side"],
                    "Configuration": opp["setup"], "Score global (/100)": score_val,
                    "Score LONG": opp["long_score"], "Score SHORT": opp["short_score"],
                    "Entrée indicative": res["entry"], "Stop indicatif": res["sl"],
                    "Objectif 1": res["tp_ct"], "Temps estimé objectif 1": estimate_target_time(timeframe_label, 2),
                    "Objectif 2": res["tp_lt"], "Temps estimé objectif 2": estimate_target_time(timeframe_label, 3),
                    "Ratio rendement/risque": round(opp["rr"], 2), "RSI": round(opp["rsi"], 1),
                    "ADX": round(opp["adx"], 1), "Volume relatif": round(opp["volume_ratio"], 2),
                    "ATR %": round(opp["atr_pct"], 2), "MACD": opp["macd"], "Cassure confirmée": opp["breakout"],
                    "Volume confirme le sens": opp["volume_confirme"], "Écart à la MM20 (%)": opp["distance_moyenne20_pct"],
                })
            else:
                unavailable_assets.append(asset["symbol"])

        if unavailable_assets:
            shown = ", ".join(unavailable_assets[:12])
            suffix = f" et {len(unavailable_assets) - 12} autre(s)" if len(unavailable_assets) > 12 else ""
            st.warning(f"Cours indisponible ou invalide pour {len(unavailable_assets)} actif(s) : {shown}{suffix}. Ces actifs ont été ignorés dans le screener.")

        if sort_order == "Score (Plus élevé au plus bas)":
            screened_list.sort(key=lambda x: x["res"]["score"], reverse=True)
            excel_export_data.sort(key=lambda x: x["Score global (/100)"], reverse=True)
        elif sort_order == "Meilleur compromis score / risque":
            # Classement composite, sans écraser ni masquer le score technique original.
            def _priority(item):
                r = item["res"]
                rr = float(r.get("rr", 0) or 0)
                score = float(r.get("score", 0) or 0)
                rr_factor = min(1.0, max(0.0, rr / 2.0))
                return score * (0.65 + 0.35 * rr_factor)
            screened_list.sort(key=_priority, reverse=True)
            excel_export_data.sort(key=lambda x: float(x["Score global (/100)"]) * (0.65 + 0.35 * min(1.0, max(0.0, float(x.get("Ratio rendement/risque", 0) or 0) / 2.0))), reverse=True)
        elif sort_order == "Nom (A-Z)":
            screened_list.sort(key=lambda x: x["asset"]["name"])
            excel_export_data.sort(key=lambda x: x["Nom"])

        if excel_export_data:
            df_excel = pd.DataFrame(excel_export_data)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_excel.to_excel(writer, index=False, sheet_name='Screener Bourse')
            excel_data = output.getvalue()

            col_exp1, col_exp2 = st.columns([3, 1])
            with col_exp2:
                st.download_button(
                    label="📥 Exporter le Screener en Excel",
                    data=excel_data,
                    file_name=f"screener_bourse_{timeframe_label.replace(' ', '_')}_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_export_excel",
                    use_container_width=True
                )
            st.markdown("---")

        for rank_index, item in enumerate(screened_list, start=1):
            asset = item["asset"]
            res = item["res"]
            history_df_scr = item["history_df"]
            score_val = res["score"]

            is_fav = asset["symbol"] in st.session_state.app_data["favoris"]
            # Statut directionnel coloré affiché directement dans le SCREENER.
            prix = res.get("price", float("nan"))
            sma50 = res.get("sma_50", float("nan"))
            sma200 = res.get("sma_200", float("nan"))
            rsi = res.get("rsi_14", 50)
            haussier = np.isfinite(sma50) and np.isfinite(sma200) and prix > sma50 > sma200
            baissier = np.isfinite(sma50) and np.isfinite(sma200) and prix < sma50 < sma200
            if score_val >= 75 and haussier and rsi < 75:
                signal_type = "ACHAT FORT"
            elif score_val >= 55 and np.isfinite(sma50) and prix > sma50:
                signal_type = "ACHAT"
            elif baissier and score_val <= 35 and rsi < 45:
                signal_type = "VENTE FORTE"
            elif np.isfinite(sma50) and prix < sma50:
                signal_type = "VENTE"
            else:
                signal_type = "NEUTRE"
            is_strong_signal = signal_type in ("ACHAT FORT", "VENTE FORTE")
        
            col_fav, col_desc, col_prices, col_targets, col_state, col_chart_btn = st.columns([0.6, 2.2, 2.0, 2.8, 2.2, 0.8])
        
            with col_fav:
                if is_fav:
                    if st.button("⭐", key=f"scr_rem_{asset['symbol']}", help="Retirer des favoris"):
                        st.session_state.app_data["favoris"].remove(asset["symbol"])
                        save_app_data(st.session_state.app_data)
                        st.rerun()
                else:
                    if st.button("☆", key=f"scr_add_{asset['symbol']}", help="Ajouter aux favoris"):
                        if asset["symbol"] not in st.session_state.app_data["favoris"]:
                            st.session_state.app_data["favoris"].append(asset["symbol"])
                            save_app_data(st.session_state.app_data)
                            st.rerun()
                        
            with col_desc:
                prefix = "🔥 " if is_strong_signal else ""
                st.markdown(f"**#{rank_index} · {prefix}{asset['name']}**<br>`{asset['symbol']}`", unsafe_allow_html=True)
            
            with col_prices:
                st.markdown(f"Réel: **{res['price']} €**<br>Entrée: `{res['entry']} €`", unsafe_allow_html=True)
            
            with col_targets:
                st.markdown(f"SL: <span style='color:red;'>`{res['sl']} €`</span><br>TP CT: `{res['tp_ct']} €` | TP LT: `{res['tp_lt']} €`", unsafe_allow_html=True)
                # Les objectifs sont définis à environ 2 ATR et 3 ATR dans l'analyse.
                # La barre compare les délais théoriques estimés, elle ne mesure pas une progression réelle.
                t_ct = estimate_target_time(timeframe_label, 2)
                t_lt = estimate_target_time(timeframe_label, 3)
                st.caption(f"⏱️ Temps estimé TP CT : {t_ct} · TP LT : {t_lt}")
                st.progress(0.67, text="TP CT · estimation relative")
                st.progress(1.0, text="TP LT · estimation relative")
            
            with col_state:
                signal_styles = {
                    "ACHAT FORT": "background-color:#047857;color:white;border:2px solid #34d399;",
                    "ACHAT": "background-color:#d1fae5;color:#065f46;border:2px solid #6ee7b7;",
                    "NEUTRE": "background-color:#e5e7eb;color:#374151;border:2px solid #9ca3af;",
                    "VENTE": "background-color:#fee2e2;color:#991b1b;border:2px solid #fca5a5;",
                    "VENTE FORTE": "background-color:#b91c1c;color:white;border:2px solid #f87171;",
                }
                sig_style = signal_styles[signal_type] + "display:inline-block;padding:5px 9px;border-radius:6px;font-weight:800;box-shadow:0 2px 5px rgba(0,0,0,.15);"
                fond = "#ecfdf5" if signal_type in ("ACHAT", "ACHAT FORT") else ("#fef2f2" if signal_type in ("VENTE", "VENTE FORTE") else "#f9fafb")
                bord = "#059669" if signal_type in ("ACHAT", "ACHAT FORT") else ("#dc2626" if signal_type in ("VENTE", "VENTE FORTE") else "#9ca3af")
                st.markdown(
                    f"<div style='padding:7px;background:{fond};border-left:5px solid {bord};border-radius:7px;'>"
                    f"<span style='{sig_style}'>{signal_type}</span><br><b>Score : {score_val}/100</b></div>",
                    unsafe_allow_html=True
                )
                st.caption(f"{res.get('setup', '')} · R/R {res.get('rr', 0):.1f} · ADX {res.get('adx', 0):.0f}")

            with col_chart_btn:
                st.write("")
                chart_key = f"show_chart_{asset['symbol']}"
                if chart_key not in st.session_state:
                    st.session_state[chart_key] = False
            
                if st.button("📈", key=f"btn_chart_{asset['symbol']}", help="Voir le graphique et les paramètres"):
                    st.session_state[chart_key] = not st.session_state[chart_key]

            if st.session_state.get(chart_key, False):
                with st.expander(f"📊 Analyse Technique détaillée & Graphique ({timeframe_label}) : {asset['name']}", expanded=True):
                    col_info1, col_info2, col_info3 = st.columns(3)
                    col_info1.metric("RSI (14)", res["rsi_14"])
                    col_info2.metric("ADX", f"{res.get('adx', 0):.1f}")
                    col_info3.metric("Volume relatif", f"{res.get('volume_ratio', 1):.2f}x")
                    st.caption(f"Scores directionnels : LONG {res.get('long_score', 0)}/100 · SHORT {res.get('short_score', 0)}/100 · MACD {res.get('macd', 'n/a')} · ATR {res.get('atr_pct', 0):.2f}% · Volume dans le sens : {res.get('volume_confirme', 'n/a')} · Écart MM20 : {res.get('distance_moyenne20_pct', 0):.2f}%")
                
                    tv_s = asset["symbol"].replace("=X", "").replace("-USD", "USD").replace("=F", "")
                    st.markdown(f"🔗 **[Ouvrir sur TradingView]** (https://www.tradingview.com/chart/?symbol={urllib.parse.quote(tv_s)})", unsafe_allow_html=True)
                
                    if history_df_scr is not None:
                        plot_asset_chart(asset["name"], history_df_scr, res)
                    else:
                        st.warning("Historique indisponible.")

            st.divider()

        st.caption("⚠️ Scores, niveaux et délais sont des estimations heuristiques basées sur l'historique et l'ATR, pas des probabilités ni des garanties. Les délais indiquent un ordre de grandeur en bougies si le prix évolue dans la direction visée; ils ne représentent pas une progression réelle. Les signaux SHORT sont informatifs : aucun ordre automatique n'est exécuté.")

with tab8:
    st.header("📋 Ma Watchlist — Screener personnel")
    st.info("Créez votre propre liste d'actifs, indépendante des favoris, puis relancez l'analyse technique quand vous le souhaitez.")

    watchlist_symbols = st.session_state.app_data.setdefault("watchlist", [])
    asset_by_symbol = {a["symbol"]: a for a in assets_db}
    available_assets = [a for a in assets_db if a["symbol"] not in watchlist_symbols]
    with st.form("watchlist_add_form"):
        chosen_assets = st.multiselect(
            "Sélectionner les actifs à ajouter à ma liste",
            options=[a["symbol"] for a in available_assets],
            format_func=lambda symbol: f"{asset_by_symbol[symbol]['name']} ({symbol})",
            placeholder="Choisissez un ou plusieurs actifs..."
        )
        add_watchlist = st.form_submit_button("➕ Ajouter à ma liste", type="primary", use_container_width=True)
    if add_watchlist and chosen_assets:
        for symbol in chosen_assets:
            if symbol not in watchlist_symbols:
                watchlist_symbols.append(symbol)
        st.session_state.app_data["watchlist"] = watchlist_symbols
        if save_app_data(st.session_state.app_data):
            st.success(f"{len(chosen_assets)} actif(s) ajouté(s) à votre Watchlist.")
        st.rerun()

    watchlist_symbols = st.session_state.app_data.get("watchlist", [])
    st.caption(f"{len(watchlist_symbols)} actif(s) dans votre liste personnelle.")
    if watchlist_symbols:
        remove_col, refresh_col = st.columns(2)
        with remove_col:
            remove_symbol = st.selectbox(
                "Retirer un actif de la liste",
                options=[""] + watchlist_symbols,
                format_func=lambda symbol: "Choisir un actif..." if not symbol else f"{asset_by_symbol.get(symbol, {}).get('name', symbol)} ({symbol})",
                key="watchlist_remove_select"
            )
            if st.button("🗑️ Retirer l'actif sélectionné", disabled=not bool(remove_symbol), use_container_width=True):
                st.session_state.app_data["watchlist"].remove(remove_symbol)
                save_app_data(st.session_state.app_data)
                st.rerun()
        with refresh_col:
            if st.button("🔄 Actualiser ma Watchlist", type="primary", use_container_width=True):
                get_market_indicators.clear()
                st.rerun()

        with st.form("watchlist_analysis_form"):
            wc1, wc2 = st.columns(2)
            with wc1:
                watch_tf = st.selectbox("Horizon d'analyse", ["15 minutes", "1 heure", "4 heures (agrégé)", "1 jour", "1 semaine", "1 mois"], index=3, key="watchlist_tf")
            with wc2:
                watch_min_score = st.slider("Score minimum", 0, 100, 0, 5, key="watchlist_score")
            run_watchlist = st.form_submit_button("🔎 Analyser ma liste", use_container_width=True)
        if run_watchlist:
            st.session_state.watchlist_config = {"timeframe": watch_tf, "min_score": watch_min_score}
            st.session_state.watchlist_has_run = True

        if st.session_state.get("watchlist_has_run", False):
            cfg = st.session_state.get("watchlist_config", {})
            tf_map = {
                "15 minutes": ("5d", "15m"), "1 heure": ("1mo", "1h"),
                "4 heures (agrégé)": ("1mo", "1h"), "1 jour": ("1y", "1d"),
                "1 semaine": ("2y", "1wk"), "1 mois": ("5y", "1mo")
            }
            period, interval = tf_map.get(cfg.get("timeframe", "1 jour"), ("1y", "1d"))
            rows = []
            unavailable = []
            progress = st.progress(0, text="Analyse des actifs de votre liste...")
            for index, symbol in enumerate(watchlist_symbols):
                asset = asset_by_symbol.get(symbol)
                if not asset:
                    continue
                try:
                    price, _, _, _, _, history = get_market_indicators(symbol, period=period, interval=interval)
                    if price is None or history is None or history.empty:
                        unavailable.append(symbol)
                        continue
                    analysis = history
                    if cfg.get("timeframe") == "4 heures (agrégé)":
                        analysis = history.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna(subset=["Close"])
                    opportunity = compute_opportunity_analysis(analysis, direction_mode="both_watch")
                    if opportunity is not None and opportunity["score"] >= int(cfg.get("min_score", 0)):
                        rows.append({
                            "Actif": asset["name"], "Ticker": symbol, "Cours": round(float(price), 5),
                            "Opération": "ACHAT" if opportunity.get("side") == "LONG" else "VENTE",
                            "Signal": opportunity["signal"], "Direction": opportunity.get("side", ""),
                            "Score Achat": opportunity.get("long_score", 0),
                            "Score Vente": opportunity.get("short_score", 0),
                            "Score retenu /100": opportunity["score"], "Entrée indicative": round(opportunity["entry"], 5),
                            "Stop-loss": round(opportunity["sl"], 5), "Objectif CT": round(opportunity["tp_ct"], 5),
                            "Objectif LT": round(opportunity["tp_lt"], 5), "RSI": round(opportunity["rsi"], 1),
                            "Ratio R/R": round(opportunity.get("rr", 0), 2)
                        })
                    else:
                        unavailable.append(symbol)
                except Exception:
                    unavailable.append(symbol)
                progress.progress((index + 1) / max(1, len(watchlist_symbols)), text=f"Analyse : {index + 1}/{len(watchlist_symbols)}")
            progress.empty()
            if rows:
                df_watch = pd.DataFrame(rows).sort_values("Score retenu /100", ascending=False)
                st.dataframe(df_watch, use_container_width=True, hide_index=True)
                output_watch = io.BytesIO()
                with pd.ExcelWriter(output_watch, engine="openpyxl") as writer:
                    df_watch.to_excel(writer, index=False, sheet_name="Ma Watchlist")
                st.download_button("📥 Exporter ma Watchlist en Excel", data=output_watch.getvalue(), file_name=f"ma_watchlist_{datetime.now().strftime('%Y-%m-%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                st.warning("Aucun résultat ne correspond au score minimum ou les cours sont indisponibles.")
            if unavailable:
                st.caption("Actifs sans résultat exploitable : " + ", ".join(unavailable))
    else:
        st.warning("Votre Watchlist est vide. Sélectionnez des actifs ci-dessus pour commencer.")

with tab3:
    st.header("⭐ Liste de vos Actifs Favoris")
    st.info("💡 Les favoris utilisent le même moteur d'analyse, les mêmes cours mis en cache et le même horizon que le Screener (journalier par défaut). Les filtres de score/catégorie du Screener ne masquent pas vos favoris.")

    col_fav_refresh, col_fav_count = st.columns([1, 3])
    with col_fav_refresh:
        if st.button("🔄 Actualiser les favoris", key="btn_refresh_favoris", use_container_width=True):
            # Vide le cache des données de marché pour forcer une nouvelle récupération des cours.
            get_market_indicators.clear()
            st.rerun()
    with col_fav_count:
        st.caption(f"{len(st.session_state.app_data['favoris'])} actif(s) dans vos favoris")

    favoris_list = st.session_state.app_data["favoris"]
    if not favoris_list:
        st.warning("Aucun actif dans vos favoris pour le moment. Vous pouvez en ajouter depuis le 'Screener Global' ou le 'Scanner & Indicateurs'.")
    else:
        fav_assets_objs = [a for a in assets_db if a["symbol"] in favoris_list]

        # Les favoris réutilisent exactement l'horizon et le moteur d'analyse du Screener.
        # Si le Screener n'a pas encore été lancé, on utilise l'horizon journalier.
        fav_cfg = st.session_state.get("screener_config", {})
        fav_timeframe = fav_cfg.get("timeframe_label", "1 jour")
        fav_tf_mapping = {
            "15 minutes": ("5d", "15m"),
            "1 heure": ("1mo", "1h"),
            "4 heures (agrégé)": ("1mo", "1h"),
            "1 jour": ("1y", "1d"),
            "1 semaine": ("2y", "1wk"),
            "1 mois": ("5y", "1mo"),
        }
        fav_period, fav_interval = fav_tf_mapping.get(fav_timeframe, ("1y", "1d"))

        for asset in fav_assets_objs:
            p, sma_200, sma_50, rsi, atr_val, history_df_fav = get_market_indicators(
                asset["symbol"], period=fav_period, interval=fav_interval
            )
            if p is not None and np.isfinite(p) and p > 0 and history_df_fav is not None:
                analysis_df_fav = history_df_fav
                if fav_timeframe == "4 heures (agrégé)":
                    analysis_df_fav = history_df_fav.resample("4h").agg({
                        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
                    }).dropna(subset=["Close"])
                opp_fav = compute_opportunity_analysis(analysis_df_fav, direction_mode="both_watch")
                if opp_fav is None:
                    st.warning(f"Analyse indisponible pour {asset['symbol']} avec l'horizon {fav_timeframe}.")
                    continue
                # Même structure de résultat, mêmes scores et mêmes niveaux que le Screener.
                res = {
                    "signal": opp_fav["signal"], "score": opp_fav["score"],
                    "price": round(opp_fav["price"], 5), "entry": round(opp_fav["entry"], 5),
                    "sl": round(opp_fav["sl"], 5), "tp_ct": round(opp_fav["tp_ct"], 5),
                    "tp_lt": round(opp_fav["tp_lt"], 5), "rsi_14": round(opp_fav["rsi"], 1),
                    "atr": round(opp_fav["price"] * opp_fav["atr_pct"] / 100, 5),
                    "sma_50": round(opp_fav["sma50"], 5),
                    "sma_200": round(opp_fav["sma200"], 5) if np.isfinite(opp_fav["sma200"]) else float("nan"),
                    **opp_fav,
                }
                score_val = int(res["score"])
                # Conserve exactement la règle de statut utilisée dans le Screener.
                sma50_fav = res.get("sma_50", float("nan"))
                sma200_fav = res.get("sma_200", float("nan"))
                rsi_fav = res.get("rsi_14", 50)
                prix_fav = res.get("price", p)
                tendance_haussiere = np.isfinite(sma50_fav) and np.isfinite(sma200_fav) and prix_fav > sma50_fav > sma200_fav
                tendance_baissiere = np.isfinite(sma50_fav) and np.isfinite(sma200_fav) and prix_fav < sma50_fav < sma200_fav
                if score_val >= 75 and tendance_haussiere and rsi_fav < 75:
                    signal_type = "ACHAT FORT"
                elif score_val >= 55 and np.isfinite(sma50_fav) and prix_fav > sma50_fav:
                    signal_type = "ACHAT"
                elif tendance_baissiere and score_val <= 35 and rsi_fav < 45:
                    signal_type = "VENTE FORTE"
                elif np.isfinite(sma50_fav) and prix_fav < sma50_fav:
                    signal_type = "VENTE"
                else:
                    signal_type = "NEUTRE"
                is_strong_signal = signal_type in ("ACHAT FORT", "VENTE FORTE")
                
                col_fav, col_desc, col_prices, col_targets, col_state, col_chart_btn, col_tv = st.columns([0.6, 2.2, 2.0, 2.8, 2.0, 0.8, 0.8])
                
                with col_fav:
                    if st.button("🗑️", key=f"fav_tab3_rem_{asset['symbol']}", help="Retirer des favoris"):
                        st.session_state.app_data["favoris"].remove(asset["symbol"])
                        save_app_data(st.session_state.app_data)
                        st.rerun()
                        
                with col_desc:
                    prefix = "🔥 " if is_strong_signal else ""
                    st.markdown(f"**{prefix}{asset['name']}**<br>`{asset['symbol']}`", unsafe_allow_html=True)
                    
                with col_prices:
                    st.markdown(f"Réel: **{res['price']} €**<br>Entrée: `{res['entry']} €`", unsafe_allow_html=True)
                    
                with col_targets:
                    st.markdown(f"SL: <span style='color:red;'>`{res['sl']} €`</span><br>TP CT: `{res['tp_ct']} €` | TP LT: `{res['tp_lt']} €`", unsafe_allow_html=True)
                    
                with col_state:
                    signal_styles = {
                        "ACHAT FORT": "background-color:#047857;color:white;border:2px solid #34d399;",
                        "ACHAT": "background-color:#d1fae5;color:#065f46;border:2px solid #6ee7b7;",
                        "NEUTRE": "background-color:#e5e7eb;color:#374151;border:2px solid #9ca3af;",
                        "VENTE": "background-color:#fee2e2;color:#991b1b;border:2px solid #fca5a5;",
                        "VENTE FORTE": "background-color:#b91c1c;color:white;border:2px solid #f87171;"
                    }
                    sig_style = signal_styles[signal_type] + "display:inline-block;padding:5px 9px;border-radius:6px;font-weight:800;box-shadow:0 2px 5px rgba(0,0,0,.15);"
                    fond = "#ecfdf5" if signal_type in ("ACHAT", "ACHAT FORT") else ("#fef2f2" if signal_type in ("VENTE", "VENTE FORTE") else "#f9fafb")
                    bord = "#059669" if signal_type in ("ACHAT", "ACHAT FORT") else ("#dc2626" if signal_type in ("VENTE", "VENTE FORTE") else "#9ca3af")
                    st.markdown(
                        f"<div style='padding:7px;background:{fond};border-left:5px solid {bord};border-radius:7px;'>"
                        f"<span style='{sig_style}'>{signal_type}</span><br><b>Score : {score_val}/100</b></div>",
                        unsafe_allow_html=True
                    )

                with col_chart_btn:
                    st.write("")
                    chart_key = f"show_fav_chart_{asset['symbol']}"
                    if chart_key not in st.session_state:
                        st.session_state[chart_key] = False
                    
                    if st.button("📈", key=f"btn_fav_chart_{asset['symbol']}", help="Voir le graphique et les paramètres"):
                        st.session_state[chart_key] = not st.session_state[chart_key]

                with col_tv:
                    st.write("")
                    tv_s = asset["symbol"].replace("=X", "").replace("-USD", "USD").replace("=F", "")
                    tv_url = f"https://www.tradingview.com/chart/?symbol={urllib.parse.quote(tv_s)}"
                    st.markdown(f"[📊]({tv_url})", help="Ouvrir sur TradingView")

                if st.session_state.get(chart_key, False):
                    with st.expander(f"📊 Analyse Technique détaillée & Graphique : {asset['name']}", expanded=True):
                        col_info1, col_info2, col_info3 = st.columns(3)
                        col_info1.metric("RSI (14)", res["rsi_14"])
                        col_info2.metric("ATR (14)", res["atr"])
                        col_info3.metric("Moyennes Mobiles", f"SMA50: {res['sma_50']} | SMA200: {res['sma_200']}")
                        
                        st.markdown(f"🔗 **[Ouvrir sur TradingView]({tv_url})**", unsafe_allow_html=True)
                        
                        if analysis_df_fav is not None:
                            plot_asset_chart(asset["name"], analysis_df_fav, res)
                        else:
                            st.warning("Historique indisponible.")

                st.divider()

with tab4:
    st.header("Gestion des Banques & Portefeuilles")

    portfolios = st.session_state.app_data["portfolios"]
    col_new1, col_new2 = st.columns([3, 1])
    with col_new1:
        new_bank_name = st.text_input("Nouvelle banque :", placeholder="Nom de la banque...", key="new_bank_input")
    with col_new2:
        st.write("")
        if st.button("Créer la Banque", key="btn_create_bank"):
            clean_name = new_bank_name.strip()
            if not clean_name:
                st.error("❌ Le nom de la banque ne peut pas être vide.")
            elif clean_name in portfolios:
                st.error("❌ Cette banque existe déjà.")
            else:
                portfolios[clean_name] = []
                if save_app_data(st.session_state.app_data):
                    st.success(f"✅ Banque '{clean_name}' créée et sauvegardée !")
                    st.rerun()
                else:
                    st.error("❌ Échec de la sauvegarde.")

    st.markdown("---")

    if not portfolios:
        st.info("Aucune banque enregistrée.")
    else:
        selected_bank_view = st.selectbox("Consulter la banque :", list(portfolios.keys()), key="select_bank_view")
        
        if st.button("Supprimer cette banque", key="btn_del_bank"):
            if len(portfolios) <= 1:
                st.error("❌ Vous devez conserver au moins une banque active.")
            else:
                del portfolios[selected_bank_view]
                save_app_data(st.session_state.app_data)
                st.success("✅ Banque supprimée.")
                st.rerun()

        bank_items = portfolios[selected_bank_view]
        if not bank_items:
            st.info("Cette banque est vide.")
        else:
            portfolio_table = []
            total_investi = 0
            total_valeur = 0

            for idx, item in enumerate(bank_items):
                current_p, _, _, _, _, _ = get_market_indicators(item["symbol"], period="1y", interval="1d")
                price_is_live = current_p is not None and np.isfinite(current_p) and current_p > 0
                if not price_is_live:
                    current_p = item["entry_price"]
                
                qty = item.get("qty", 1.0)
                inv_eur = item.get("invested_eur", current_p * qty)
                valeur_totale = current_p * qty
                plus_moins_value = valeur_totale - inv_eur
                
                total_investi += inv_eur
                total_valeur += valeur_totale

                portfolio_table.append({
                    "Index": idx,
                    "Actif": item["name"] + (" (cours indisponible; valeur au PRU)" if not price_is_live else ""),
                    "Fréquence / plan indicatif": item.get("frequency", "Unique"),
                    "Quantité": round(qty, 4),
                    "Investi (€)": round(inv_eur, 2),
                    "Valeur (€)": round(valeur_totale, 2),
                    "Plus/Moins-Value (€)": round(plus_moins_value, 2)
                })

            st.metric("Valeur Totale du Portefeuille", f"{total_valeur:,.2f} €", delta=f"{total_valeur - total_investi:,.2f} €")

            df_port = pd.DataFrame(portfolio_table)
            st.dataframe(df_port.drop(columns=["Index"]), use_container_width=True)

            item_to_delete = st.selectbox("Ligne à retirer :", range(len(bank_items)), format_func=lambda x: f"{bank_items[x]['name']} (Investi: {bank_items[x].get('invested_eur', 0)} €)", key="select_item_del")
            if st.button("Supprimer la ligne sélectionnée", key="btn_del_item"):
                bank_items.pop(item_to_delete)
                save_app_data(st.session_state.app_data)
                st.success("✅ Ligne supprimée et sauvegardée !")
                st.rerun()

with tab5:
    st.header("📊 Mesure des Résultats & Performance Analytique")
    st.info("🎯 Mesurez objectivement les résultats réels de vos investissements basés sur les prix en direct du marché.")

    portfolios = st.session_state.app_data["portfolios"]
    if not portfolios:
        st.warning("Aucune donnée de portefeuille enregistrée pour mesurer les résultats.")
    else:
        all_positions = []
        global_invested = 0.0
        global_value = 0.0
        winning_positions = 0
        total_positions = 0

        for bank_name, items in portfolios.items():
            for item in items:
                current_p, _, _, _, _, _ = get_market_indicators(item["symbol"], period="1y", interval="1d")
                price_is_live = current_p is not None and np.isfinite(current_p) and current_p > 0
                if not price_is_live:
                    current_p = item["entry_price"]
                
                qty = item.get("qty", 1.0)
                inv_eur = item.get("invested_eur", current_p * qty)
                valeur_totale = current_p * qty
                pnl_eur = valeur_totale - inv_eur
                pnl_pct = (pnl_eur / inv_eur * 100) if inv_eur > 0 else 0.0

                global_invested += inv_eur
                global_value += valeur_totale
                total_positions += 1
                if pnl_eur >= 0:
                    winning_positions += 1

                all_positions.append({
                    "Banque": bank_name,
                    "Actif": item["name"],
                    "Date": item.get("date", "N/A"),
                    "Investi (€)": round(inv_eur, 2),
                    "Valeur Actuelle (€)": round(valeur_totale, 2),
                    "P&L (€)": round(pnl_eur, 2),
                    "P&L (%)": round(pnl_pct, 2)
                })

        global_pnl = global_value - global_invested
        global_pnl_pct = (global_pnl / global_invested * 100) if global_invested > 0 else 0.0
        win_rate = (winning_positions / total_positions * 100) if total_positions > 0 else 0.0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Capital Total Investi", f"{global_invested:,.2f} €")
        m2.metric("Valeur de Marché Actuelle", f"{global_value:,.2f} €", delta=f"{global_pnl:,.2f} € ({global_pnl_pct:+.2f}%)")
        m3.metric("Taux de Réussite Mesuré", f"{win_rate:.1f}%", help="Pourcentage de positions actuellement en gain")
        m4.metric("Nombre de Positions Actives", f"{total_positions}")

        st.markdown("---")
        st.subheader("📋 Tableau Détaillé des Résultats par Position")
        
        if len(all_positions) > 0:
            df_results = pd.DataFrame(all_positions)

            def color_pnl(val):
                if val > 0:
                    return 'color: #16a34a; font-weight: bold;'
                elif val < 0:
                    return 'color: #dc2626; font-weight: bold;'
                return 'color: #64748b;'

            st.dataframe(df_results.style.map(color_pnl, subset=['P&L (€)', 'P&L (%)']), use_container_width=True)
        else:
            st.info("ℹ️ Aucune position active enregistrée dans vos portefeuilles pour le moment. Ajoutez des ordres depuis l'onglet 'Scanner & Indicateurs'.")

with tab6:
    st.header("💾 Sauvegarde & Restauration des Données")
    st.info("Vos modifications sont sauvegardées **automatiquement** en temps réel avec un système de secours atomique (`.bak`) incluant vos portefeuilles et vos favoris.")

    st.subheader("1. Sauvegarder sur votre ordinateur")
    json_data = json.dumps(st.session_state.app_data, indent=4, ensure_ascii=False)
    st.download_button(
        label="📥 Télécharger le fichier de sauvegarde (.json)",
        data=json_data,
        file_name=f"sauvegarde_portefeuille_{datetime.now().strftime('%Y-%m-%d')}.json",
        mime="application/json",
        key="download_backup_btn"
    )

    st.markdown("---")

    st.subheader("2. Restaurer depuis une sauvegarde")
    uploaded_file = st.file_uploader("Importer un fichier de sauvegarde (.json) :", type=["json"], key="upload_backup_file")
    
    if uploaded_file is not None:
        try:
            raw_data = json.load(uploaded_file)
            validated_restored_data = validate_app_data(raw_data)
            
            if st.button("⚠️ Confirmer et Remplacer les données actuelles", key="btn_confirm_restore"):
                st.session_state.app_data = validated_restored_data
                save_app_data(st.session_state.app_data)
                st.success("✅ Données validées et restaurées avec succès !")
                st.rerun()
        except Exception as e:
            st.error(f"❌ Le fichier importé est invalide ou corrompu : {e}")

with tab7:
    st.header("🤖 Portefeuille virtuel — trading automatique simulé")
    st.warning("Simulation uniquement : aucun ordre réel n'est envoyé. Les cours peuvent être retardés selon le fournisseur. Les frais, le spread et le slippage ne sont pas modélisés.")

    if "virtual_portfolio" not in st.session_state:
        st.session_state.virtual_portfolio = load_virtual_portfolio()
    if st.button("🔄 Actualiser le portefeuille sauvegardé", key="vp_refresh_portfolio", use_container_width=True):
        st.session_state.virtual_portfolio = load_virtual_portfolio()
        st.rerun()
    vp = st.session_state.virtual_portfolio
    st.info("Le portefeuille est sauvegardé automatiquement dans le dépôt. Le calcul se lance toutes les 15 minutes, même si cette page est fermée. Aucun ordre réel n'est envoyé.")
    st.warning("Le portefeuille est en euros : seuls les actifs cotés en EUR sont désormais proposés à l'achat et aux nouveaux signaux automatiques. Les anciennes positions en devise étrangère ou inconnue sont conservées, mais leurs opérations automatiques et ventes manuelles sont suspendues faute de conversion FX fiable.")
    if not _virtual_github_token():
        st.caption("Mode simple : lecture en ligne sans configuration. Les cycles et sauvegardes sont gérés automatiquement; les commandes manuelles sont désactivées.")

    # Paramètres communs au cycle automatique GitHub Actions.
    vp_timeframe = "15 minutes"
    vp_period, vp_interval = ("5d", "15m")
    vp_max_positions = 50
    vp_min_score = 65
    vp_risk_pct = 1.0

    # Le portefeuille est libellé en EUR : aucune conversion FX n'est actuellement intégrée.
    def _vp_quote_currency(symbol):
        symbol = str(symbol or "")
        if symbol.endswith(".PA") or symbol in {"^FCHI", "^GDAXI", "^STOXX50E"}:
            return "EUR"
        if symbol.endswith("-USD") or symbol.endswith("=F"):
            return "USD"
        if symbol.endswith("=X"):
            return symbol[-5:-2]
        if symbol in {"AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "GOOGL", "META", "NFLX", "AMD", "^GSPC", "^NDX", "^DJI"}:
            return "USD"
        return "UNKNOWN"

    def _vp_is_eur_position(position):
        return position.get("currency", _vp_quote_currency(position.get("symbol"))) == "EUR"
    st.caption("Réglages automatiques : 15 minutes · 50 positions maximum · score minimum 65 · risque théorique 1 % par position.")

    def _vp_mark_to_market(position, current_price):
        if not _vp_is_eur_position(position):
            return 0.0
        qty = float(position.get("qty", 0.0))
        entry = float(position.get("entry", 0.0))
        direction = position.get("side", "LONG")
        pnl = (current_price - entry) * qty if direction == "LONG" else (entry - current_price) * qty
        return float(position.get("capital", entry * qty)) + pnl

    def _vp_close_position(position, exit_price, reason, portfolio):
        entry = float(position.get("entry", 0.0))
        qty = float(position.get("qty", 0.0))
        side = position.get("side", "LONG")
        pnl = (exit_price - entry) * qty if side == "LONG" else (entry - exit_price) * qty
        capital = float(position.get("capital", entry * qty))
        portfolio["cash"] = float(portfolio.get("cash", 0.0)) + capital + pnl
        closed = dict(position)
        closed.update({"exit": float(exit_price), "pnl_eur": float(pnl), "exit_reason": reason,
                       "closed_at": datetime.now().isoformat(timespec="seconds")})
        portfolio.setdefault("closed_trades", []).append(closed)

    if st.button("▶️ Lancer un cycle maintenant", key="vp_run_cycle", type="primary", use_container_width=True, disabled=not bool(_virtual_github_token())):
        # Une seule collecte par actif pendant ce cycle. Les positions ouvertes sont traitées d'abord.
        market_cache = {}
        assets_by_symbol = {a["symbol"]: a for a in assets_db}
        for symbol in {p.get("symbol") for p in vp.get("positions", [])}:
            if symbol and symbol in assets_by_symbol:
                a = assets_by_symbol[symbol]
                px, _, _, _, _, hist = get_market_indicators(symbol, period=vp_period, interval=vp_interval)
                market_cache[symbol] = (a, px, hist)

        remaining_positions = []
        closed_count = 0
        for pos in vp.get("positions", []):
            symbol = pos.get("symbol")
            # Conserver sans les modifier les anciennes positions non libellées en EUR.
            if not _vp_is_eur_position(pos):
                remaining_positions.append(pos)
                continue
            cached = market_cache.get(symbol)
            if cached is None:
                remaining_positions.append(pos)
                continue
            _, px, hist = cached
            if px is None or not np.isfinite(px) or px <= 0:
                remaining_positions.append(pos)
                continue
            px = float(px)
            side = pos.get("side", "LONG")
            sl = float(pos.get("sl", 0.0))
            tp = float(pos.get("tp", 0.0))
            # Si SL et TP sont touchés dans la même bougie, hypothèse prudente : SL prioritaire.
            candle = hist.iloc[-1] if hist is not None and not hist.empty else None
            high = float(candle["High"]) if candle is not None and "High" in candle and pd.notna(candle["High"]) else px
            low = float(candle["Low"]) if candle is not None and "Low" in candle and pd.notna(candle["Low"]) else px
            reason = None
            exit_price = px
            if side == "LONG":
                if low <= sl:
                    reason, exit_price = "Stop-loss", sl
                elif high >= tp:
                    reason, exit_price = "Take-profit", tp
            else:
                if high >= sl:
                    reason, exit_price = "Stop-loss", sl
                elif low <= tp:
                    reason, exit_price = "Take-profit", tp
            if reason:
                _vp_close_position(pos, float(exit_price), reason, vp)
                closed_count += 1
            else:
                pos["last_price"] = px
                remaining_positions.append(pos)
        vp["positions"] = remaining_positions

        # Cherche les meilleurs nouveaux signaux sur la base de l'horizon choisi.
        candidates = []
        for asset in assets_db:
            if _vp_quote_currency(asset["symbol"]) != "EUR":
                continue
            if asset["symbol"] not in market_cache:
                px, _, _, _, _, hist = get_market_indicators(asset["symbol"], period=vp_period, interval=vp_interval)
                market_cache[asset["symbol"]] = (asset, px, hist)
            _, px, hist = market_cache[asset["symbol"]]
            if px is None or not np.isfinite(px) or px <= 0 or hist is None or hist.empty:
                continue
            analysis_df = hist
            if vp_timeframe == "4 heures (agrégé)":
                analysis_df = hist.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna(subset=["Close"])
            opp = compute_opportunity_analysis(analysis_df, direction_mode="both_watch")
            if not opp or opp["score"] < max(int(vp_min_score), 75) or opp["side"] not in ("LONG", "SHORT"):
                continue
            candidates.append({"asset": asset, "opp": opp})
        candidates.sort(key=lambda item: (item["opp"]["score"] * (0.65 + 0.35 * min(1.0, max(0.0, float(item["opp"].get("rr", 0)) / 2.0)))), reverse=True)

        equity_before = float(vp.get("cash", 0.0)) + sum(_vp_mark_to_market(p, float(p.get("last_price", p.get("entry", 0)))) for p in vp["positions"])
        # Réduit progressivement les anciennes positions ayant engagé tout le capital.
        max_allocation_pct = 8.0
        max_total_exposure_pct = 70.0
        allocation_cap = max(0.0, float(vp.get("initial_capital", VIRTUAL_INITIAL_CAPITAL)) * max_allocation_pct / 100.0)
        for pos in vp["positions"]:
            old_capital = float(pos.get("capital", float(pos.get("entry", 0)) * float(pos.get("qty", 0))))
            if old_capital > allocation_cap > 0:
                scale = allocation_cap / old_capital
                pos["qty"] = float(pos.get("qty", 0)) * scale
                pos["capital"] = allocation_cap
                vp["cash"] = float(vp.get("cash", 0.0)) + (old_capital - allocation_cap)
        risk_per_position = max(0.0, equity_before * min(float(vp_risk_pct), 0.5) / 100.0)
        max_total_exposure = max(0.0, equity_before * max_total_exposure_pct / 100.0)
        existing = {p.get("symbol") for p in vp["positions"]}
        opened_count = 0
        for item in candidates:
            if len(vp["positions"]) >= min(int(vp_max_positions), 12):
                break
            asset, opp = item["asset"], item["opp"]
            symbol = asset["symbol"]
            if symbol in existing:
                continue
            entry = float(opp["price"])
            sl = float(opp["sl"])
            tp = float(opp["tp_ct"])
            distance = abs(entry - sl)
            if entry <= 0 or distance <= 0 or (opp["side"] == "LONG" and not (sl < entry < tp)) or (opp["side"] == "SHORT" and not (tp < entry < sl)):
                continue
            qty_by_risk = risk_per_position / distance if risk_per_position > 0 else 0.0
            current_exposure = sum(max(0.0, float(p.get("capital", float(p.get("entry", 0)) * float(p.get("qty", 0))))) for p in vp["positions"])
            remaining_exposure = max(0.0, max_total_exposure - current_exposure)
            allocation_limit = min(float(vp.get("cash", 0.0)), max(0.0, equity_before * max_allocation_pct / 100.0), remaining_exposure)
            qty_by_cash = allocation_limit / entry if entry > 0 else 0.0
            qty = min(qty_by_risk, qty_by_cash)
            if not np.isfinite(qty) or qty <= 0:
                continue
            capital = qty * entry
            vp["cash"] = float(vp.get("cash", 0.0)) - capital
            vp["positions"].append({
                "name": asset["name"], "symbol": symbol, "side": opp["side"], "score": int(opp["score"]),
                "entry": entry, "last_price": entry, "currency": "EUR", "sl": sl, "tp": tp,
                "tp_long": float(opp["tp_lt"]), "qty": qty, "capital": capital,
                "opened_at": datetime.now().isoformat(timespec="seconds"), "timeframe": vp_timeframe,
            })
            existing.add(symbol)
            opened_count += 1
        vp["last_cycle"] = datetime.now().isoformat(timespec="seconds")
        st.session_state.virtual_portfolio = vp
        if save_virtual_portfolio(vp):
            st.success(f"Cycle terminé : {closed_count} position(s) clôturée(s), {opened_count} nouvelle(s) position(s) ouverte(s).")
        else:
            st.error("Le cycle a été exécuté en mémoire, mais la sauvegarde locale a échoué.")
        st.rerun()

    # Opérations manuelles sur le portefeuille virtuel (aucun ordre réel).
    st.divider()
    st.subheader("🛒 Acheter ou vendre manuellement")
    st.caption("Ces opérations modifient uniquement le portefeuille virtuel partagé. Elles ne transmettent aucun ordre à un courtier.")
    if not _virtual_github_token():
        st.warning("Les opérations manuelles nécessitent le jeton GitHub configuré dans les secrets Streamlit pour sauvegarder le portefeuille partagé.")

    buy_col, sell_col = st.columns(2)
    with buy_col:
        st.markdown("#### Acheter une position")
        asset_choices = [a for a in assets_db if _vp_quote_currency(a["symbol"]) == "EUR"]
        if asset_choices:
            asset_labels = {f"{a.get('name', a['symbol'])} ({a['symbol']})": a for a in asset_choices}
            with st.form("vp_manual_buy_form"):
                buy_label = st.selectbox("Actif à acheter", list(asset_labels.keys()), key="vp_manual_buy_asset")
                buy_qty = st.number_input("Quantité à acheter", min_value=0.000001, value=1.0, step=1.0, format="%.6f", key="vp_manual_buy_qty")
                buy_submit = st.form_submit_button("🟢 Confirmer l'achat simulé", use_container_width=True, disabled=not bool(_virtual_github_token()))
            if buy_submit:
                asset = asset_labels[buy_label]
                symbol = asset["symbol"]
                try:
                    current_price, _, _, _, _, _ = get_market_indicators(symbol, period=vp_period, interval=vp_interval)
                    if current_price is None or not np.isfinite(current_price) or float(current_price) <= 0:
                        st.error(f"Impossible de récupérer un cours valide pour {symbol}.")
                    else:
                        current_price = float(current_price)
                        cost = current_price * float(buy_qty)
                        if cost > float(vp.get("cash", 0.0)):
                            st.error(f"Solde insuffisant : achat de {cost:,.2f} € pour {float(vp.get('cash', 0.0)):,.2f} € disponibles.")
                        else:
                            now = datetime.now().isoformat(timespec="seconds")
                            vp["cash"] = float(vp.get("cash", 0.0)) - cost
                            vp.setdefault("positions", []).append({
                                "name": asset.get("name", symbol), "symbol": symbol, "side": "LONG", "score": 0,
                                "entry": current_price, "last_price": current_price, "currency": "EUR",
                                "sl": current_price * 0.92, "tp": current_price * 1.16,
                                "tp_long": current_price * 1.16, "qty": float(buy_qty), "capital": cost,
                                "opened_at": now, "timeframe": "Manuel", "source": "manual",
                            })
                            st.session_state.virtual_portfolio = vp
                            if save_virtual_portfolio(vp):
                                st.success(f"Achat simulé enregistré : {buy_qty:g} × {symbol} à {current_price:,.4f} €.")
                            else:
                                st.error("L'achat a été calculé, mais la sauvegarde GitHub a échoué.")
                            st.rerun()
                except Exception as exc:
                    st.error(f"Impossible d'enregistrer l'achat simulé : {type(exc).__name__}.")
        else:
            st.info("Aucun actif disponible dans la liste du scanner.")

    with sell_col:
        st.markdown("#### Vendre une position ouverte")
        open_positions = list(enumerate(vp.get("positions", [])))
        if open_positions:
            def _vp_position_label(index):
                position = vp["positions"][index]
                return f"{position.get('name', position.get('symbol', 'Actif'))} ({position.get('symbol', '')}) · {position.get('side', 'LONG')} · quantité {float(position.get('qty', 0.0)):g}"
            with st.form("vp_manual_sell_form"):
                sell_index = st.selectbox("Position à vendre", [i for i, _ in open_positions], format_func=_vp_position_label, key="vp_manual_sell_position")
                sell_position = vp["positions"][sell_index]
                sell_available = max(0.000001, float(sell_position.get("qty", 0.0)))
                sell_qty = st.number_input("Quantité à vendre", min_value=0.000001, max_value=sell_available, value=sell_available, step=min(1.0, sell_available), format="%.6f", key=f"vp_manual_sell_qty_{sell_index}")
                sell_submit = st.form_submit_button("🔴 Confirmer la vente simulée", use_container_width=True, disabled=not bool(_virtual_github_token()))
            if sell_submit:
                position = vp["positions"][sell_index]
                available_qty = float(position.get("qty", 0.0))
                quantity = float(sell_qty)
                try:
                    current_price, _, _, _, _, _ = get_market_indicators(position["symbol"], period=vp_period, interval=vp_interval)
                    if not _vp_is_eur_position(position):
                        st.error(f"Vente suspendue pour {position['symbol']} : devise de cotation non EUR ou inconnue. La position est conservée sans modification.")
                    elif current_price is None or not np.isfinite(current_price) or float(current_price) <= 0:
                        st.error(f"Impossible de récupérer un cours valide pour {position['symbol']}.")
                    elif quantity <= 0 or quantity > available_qty + 1e-9:
                        st.error("La quantité à vendre est invalide.")
                    else:
                        current_price = float(current_price)
                        quantity = min(quantity, available_qty)
                        entry = float(position.get("entry", 0.0))
                        side = position.get("side", "LONG")
                        pnl = (current_price - entry) * quantity if side == "LONG" else (entry - current_price) * quantity
                        capital_before = float(position.get("capital", entry * available_qty))
                        capital_released = capital_before * quantity / available_qty if available_qty > 0 else 0.0
                        vp["cash"] = float(vp.get("cash", 0.0)) + capital_released + pnl
                        closed_trade = dict(position)
                        closed_trade.update({
                            "qty": quantity, "capital": capital_released, "exit": current_price,
                            "pnl_eur": float(pnl), "exit_reason": "Vente manuelle simulée",
                            "closed_at": datetime.now().isoformat(timespec="seconds"),
                        })
                        vp.setdefault("closed_trades", []).append(closed_trade)
                        remaining_qty = available_qty - quantity
                        if remaining_qty <= max(1e-9, available_qty * 1e-9):
                            vp["positions"].pop(sell_index)
                        else:
                            position["qty"] = remaining_qty
                            position["capital"] = max(0.0, capital_before - capital_released)
                            position["last_price"] = current_price
                        st.session_state.virtual_portfolio = vp
                        if save_virtual_portfolio(vp):
                            st.success(f"Vente simulée enregistrée : {quantity:g} × {position.get('symbol', '')} à {current_price:,.4f} € · résultat {pnl:+,.2f} €.")
                        else:
                            st.error("La vente a été calculée, mais la sauvegarde GitHub a échoué.")
                        st.rerun()
                except Exception as exc:
                    st.error(f"Impossible d'enregistrer la vente simulée : {type(exc).__name__}.")
        else:
            st.info("Aucune position ouverte à vendre.")

    # Recalcul de valorisation avec cours en cache (lecture seule, aucun ordre sur un simple rafraîchissement).
    vp_positions_table = []
    equity = float(vp.get("cash", 0.0))
    unrealized = 0.0
    for pos in vp.get("positions", []):
        price = float(pos.get("last_price", pos.get("entry", 0.0)))
        try:
            live_price, _, _, _, _, _ = get_market_indicators(pos["symbol"], period=vp_period, interval=vp_interval)
            if live_price is not None and np.isfinite(live_price) and live_price > 0:
                price = float(live_price)
        except Exception:
            pass
        currency = pos.get("currency", _vp_quote_currency(pos.get("symbol")))
        is_eur = currency == "EUR"
        pnl = ((price - float(pos["entry"])) * float(pos["qty"]) if pos.get("side") == "LONG" else (float(pos["entry"]) - price) * float(pos["qty"])) if is_eur else 0.0
        capital = float(pos.get("capital", float(pos["entry"]) * float(pos["qty"])))
        if is_eur:
            equity += capital + pnl
            unrealized += pnl
        vp_positions_table.append({
            "Actif": pos.get("name", pos.get("symbol")), "Opération": ("Achat" if pos.get("side", "LONG") == "LONG" else "Vente"), "Devise": currency, "Score": pos.get("score"),
            "Entrée (devise de cotation)": round(float(pos["entry"]), 6), "Cours actuel": round(price, 6),
            "Stop-loss": round(float(pos["sl"]), 6), "Take-profit court": round(float(pos["tp"]), 6),
            "Quantité simulée": round(float(pos["qty"]), 6), "P&L latent (€)": round(pnl, 2) if is_eur else "Non valorisé",
            "Ouverte le": pos.get("opened_at", ""),
        })

    realized = sum(float(t.get("pnl_eur", 0.0)) for t in vp.get("closed_trades", []) if t.get("currency", _vp_quote_currency(t.get("symbol"))) == "EUR")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Capital initial", f"{float(vp.get('initial_capital', VIRTUAL_INITIAL_CAPITAL)):,.2f} €")
    m2.metric("Valeur estimée", f"{equity:,.2f} €", delta=f"{equity - float(vp.get('initial_capital', VIRTUAL_INITIAL_CAPITAL)):+,.2f} €")
    m3.metric("P&L réalisé", f"{realized:+,.2f} €")
    m4.metric("P&L latent", f"{unrealized:+,.2f} €")
    st.caption(f"Horizon : {vp_timeframe} · Dernier cycle : {vp.get('last_cycle') or 'jamais lancé'} · Solde disponible : {float(vp.get('cash', 0.0)):,.2f} €")

    st.subheader("Positions ouvertes")
    if vp_positions_table:
        st.dataframe(pd.DataFrame(vp_positions_table), use_container_width=True, hide_index=True)
    else:
        st.info("Aucune position ouverte pour le moment. Le prochain cycle automatique recherchera des opportunités.")

    st.subheader("Historique des clôtures")
    if vp.get("closed_trades"):
        closed_rows = [{"Actif": t.get("name", t.get("symbol")), "Sens": t.get("side"), "Score": t.get("score"),
                        "Entrée": round(float(t.get("entry", 0)), 6), "Sortie": round(float(t.get("exit", 0)), 6),
                        "Résultat (€)": round(float(t.get("pnl_eur", 0)), 2), "Motif": t.get("exit_reason"),
                        "Ouverture": t.get("opened_at"), "Clôture": t.get("closed_at")} for t in reversed(vp["closed_trades"])]
        st.dataframe(pd.DataFrame(closed_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("Aucune transaction clôturée pour le moment.")

    st.divider()
    st.subheader("Réinitialiser le portefeuille virtuel")
    st.write("Cette action supprime toutes les positions ouvertes et l'historique, puis remet le capital à 10 000 €. Le prochain cycle peut immédiatement ouvrir de nouvelles positions selon les signaux disponibles.")
    confirm_reset = st.checkbox("Je confirme la suppression de toutes les positions et la remise à zéro", key="vp_confirm_reset")
    if st.button("🧹 Vider tous les actifs et recommencer à 10 000 €", key="vp_reset_all", disabled=(not confirm_reset or not bool(_virtual_github_token())), use_container_width=True):
        vp = {"initial_capital": VIRTUAL_INITIAL_CAPITAL, "cash": VIRTUAL_INITIAL_CAPITAL,
              "positions": [], "closed_trades": [], "last_cycle": None}
        st.session_state.virtual_portfolio = vp
        if save_virtual_portfolio(vp):
            st.success("Portefeuille virtuel réinitialisé. Lance un cycle pour reprendre les positions.")
        else:
            st.error("Impossible de sauvegarder la réinitialisation.")
        st.rerun()

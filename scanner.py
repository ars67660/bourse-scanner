import streamlit as st
import pandas as pd
import yfinance as yf
import json
import os
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import urllib.parse
import urllib.request
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
        return {"portfolios": {"Banque Principale": []}, "favoris": []}
    
    favoris = data.get("favoris", [])
    if not isinstance(favoris, list):
        favoris = []
    favoris = [str(s) for s in favoris if isinstance(s, (str, int))]

    raw_portfolios = data.get("portfolios", data if "Banque Principale" in data or len(data) > 0 else {"Banque Principale": []})
    if not isinstance(raw_portfolios, dict):
        raw_portfolios = {"Banque Principale": []}
    
    cleaned_portfolios = {}
    for bank_name, items in raw_portfolios.items():
        if bank_name == "favoris":
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

    return {"portfolios": cleaned_portfolios, "favoris": favoris}

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
        data = {"portfolios": {"Banque Principale": []}, "favoris": []}

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

with st.sidebar.expander("🔌 Fournisseurs de cours & API", expanded=False):
    st.caption("Activez les sources et renseignez vos clés API. Yahoo Finance reste la source principale si activée.")
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
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Scanner & Indicateurs", 
    "Screener Global", 
    "⭐ Mes Favoris",
    "Banques & DCA", 
    "📊 Mesure & Performance", 
    "💾 Sauvegarde & Restauration"
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
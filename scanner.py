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

@st.cache_data(ttl=60)
def get_market_indicators(symbol, period="1y", interval="1d"):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty and interval in ["1h", "4h"]:
            df = ticker.history(period="1mo", interval="1h")
            
        if not df.empty and len(df) >= 5:
            current_price = float(df['Close'].iloc[-1])
            
            sma_200_value = df['Close'].rolling(window=200, min_periods=200).mean().iloc[-1]
            sma_200 = float(sma_200_value) if pd.notna(sma_200_value) else float('nan')
            sma_50_value = df['Close'].rolling(window=50, min_periods=50).mean().iloc[-1]
            sma_50 = float(sma_50_value) if pd.notna(sma_50_value) else float('nan')

            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi_series = 100 - (100 / (1 + rs))
            rsi_14 = float(rsi_series.iloc[-1]) if not rsi_series.empty and not np.isnan(rsi_series.iloc[-1]) else 50.0

            high_low = df['High'] - df['Low']
            high_close = np.abs(df['High'] - df['Close'].shift())
            low_close = np.abs(df['Low'] - df['Close'].shift())
            true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr_14 = float(true_range.rolling(window=14).mean().iloc[-1])
            
            if np.isnan(atr_14) or atr_14 <= 0:
                atr_14 = current_price * 0.015

            return current_price, sma_200, sma_50, rsi_14, atr_14, df
    except Exception:
        pass
    return None, float('nan'), float('nan'), 50.0, float('nan'), None

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
    * **Screener Global (Onglet 2) :** Analyse simultanément tous les actifs de la base de données selon l'horizon temporel choisi (1h, 1 jour, 1 mois, etc.). Vous pouvez filtrer par catégorie ou score, voir les graphiques détaillés et **exporter vos résultats en Excel**.
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
    
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    with col_f1:
        timeframe_label = st.selectbox("Horizon temporel :", ["1 heure", "4 heures", "1 jour", "1 mois", "3 mois", "6 mois", "1 an"], key="tf_select")
    with col_f2:
        filter_type = st.selectbox("Catégorie :", ["Tous"] + list(set(a["type"] for a in assets_db)), key="filter_screener")
    with col_f3:
        filter_score = st.selectbox("Score / Opportunité :", [
            "Tous les scores", 
            "🔥 Forts potentiels (Score ≥ 75)", 
            "🟢 Achats / Hausses (Score ≥ 55)", 
            "⚪ Neutres (26 - 54)", 
            "🔴 Ventes / Fortes baisses (Score ≤ 25)"
        ], key="filter_score_select")
    with col_f4:
        sort_order = st.selectbox("Trier par :", ["Ordre par défaut", "Score (Plus élevé au plus bas)", "Nom (A-Z)"], key="sort_order_select")

    tf_mapping = {
        "1 heure": ("5d", "1h"),
        "4 heures": ("1mo", "1h"),
        "1 jour": ("6mo", "1d"),
        "1 mois": ("1y", "1d"),
        "3 mois": ("2y", "1wk"),
        "6 mois": ("5y", "1wk"),
        "1 an": ("max", "1mo")
    }
    selected_period, selected_interval = tf_mapping[timeframe_label]

    st.markdown("---")

    screened_list = []
    excel_export_data = []

    for asset in assets_db:
        if filter_type != "Tous" and asset["type"] != filter_type:
            continue
        
        p, sma_200, sma_50, rsi, atr_val, history_df_scr = get_market_indicators(asset["symbol"], period=selected_period, interval=selected_interval)
        if p:
            res = compute_trading_setup(p, atr_val, {
                "l": asset["liquidity"], "v": asset["volatility"], 
                "t": asset["trend"], "r": asset["risk_reward"], "c": asset["catalyst"]
            }, sma_200, sma_50, rsi)
            
            score_val = res["score"]
            
            if filter_score == "🔥 Forts potentiels (Score ≥ 75)" and score_val < 75:
                continue
            elif filter_score == "🟢 Achats / Hausses (Score ≥ 55)" and score_val < 55:
                continue
            elif filter_score == "⚪ Neutres (26 - 54)" and not (26 <= score_val <= 54):
                continue
            elif filter_score == "🔴 Ventes / Fortes baisses (Score ≤ 25)" and score_val > 25:
                continue

            screened_list.append({
                "asset": asset,
                "res": res,
                "history_df": history_df_scr
            })

            excel_export_data.append({
                "Nom": asset["name"],
                "Ticker": asset["symbol"],
                "Catégorie": asset["type"],
                "Horizon": timeframe_label,
                "Cours (devise de cotation)": res["price"],
                "Entrée (devise de cotation)": res["entry"],
                "Stop Loss (devise de cotation)": res["sl"],
                "Take Profit CT (devise de cotation)": res["tp_ct"],
                "Take Profit LT (devise de cotation)": res["tp_lt"],
                "Signal": res["signal"],
                "Score (/100)": res["score"],
                "RSI (14)": res["rsi_14"],
                "ATR (14)": res["atr"]
            })

    if sort_order == "Score (Plus élevé au plus bas)":
        screened_list.sort(key=lambda x: x["res"]["score"], reverse=True)
        excel_export_data.sort(key=lambda x: x["Score (/100)"], reverse=True)
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

    for item in screened_list:
        asset = item["asset"]
        res = item["res"]
        history_df_scr = item["history_df"]
        score_val = res["score"]

        is_fav = asset["symbol"] in st.session_state.app_data["favoris"]
        signal_type = res["signal"]
        is_strong_signal = "FORT" in signal_type or score_val >= 75
        
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
            st.markdown(f"**{prefix}{asset['name']}**<br>`{asset['symbol']}`", unsafe_allow_html=True)
            
        with col_prices:
            st.markdown(f"Réel: **{res['price']} €**<br>Entrée: `{res['entry']} €`", unsafe_allow_html=True)
            
        with col_targets:
            st.markdown(f"SL: <span style='color:red;'>`{res['sl']} €`</span><br>TP CT: `{res['tp_ct']} €` | TP LT: `{res['tp_lt']} €`", unsafe_allow_html=True)
            
        with col_state:
            if "ACHAT FORT" in signal_type:
                sig_style = "background-color: #10b981; color: white; padding: 3px 8px; border-radius: 5px; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.1);"
            elif "VENTE FORTE" in signal_type:
                sig_style = "background-color: #ef4444; color: white; padding: 3px 8px; border-radius: 5px; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.1);"
            else:
                sig_style = "background-color: #f1f5f9; color: #334155; padding: 2px 6px; border-radius: 4px;"
            
            score_style = "color: #065f46; font-weight: bold;" if score_val >= 75 else ""
            st.markdown(f"<span style='{sig_style}'>{signal_type}</span><br><span style='{score_style}'>Score: {score_val}/100</span>", unsafe_allow_html=True)

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
                col_info2.metric("ATR (14)", res["atr"])
                col_info3.metric("Moyennes Mobiles", f"SMA50: {res['sma_50']} | SMA200: {res['sma_200']}")
                
                tv_s = asset["symbol"].replace("=X", "").replace("-USD", "USD").replace("=F", "")
                st.markdown(f"🔗 **[Ouvrir sur TradingView]** (https://www.tradingview.com/chart/?symbol={urllib.parse.quote(tv_s)})", unsafe_allow_html=True)
                
                if history_df_scr is not None:
                    plot_asset_chart(asset["name"], history_df_scr, res)
                else:
                    st.warning("Historique indisponible.")

        st.divider()

with tab3:
    st.header("⭐ Liste de vos Actifs Favoris")
    st.info("💡 Retrouvez vos favoris sous forme de liste avec accès direct au graphique technique (📈) et à TradingView (📊).")

    favoris_list = st.session_state.app_data["favoris"]
    if not favoris_list:
        st.warning("Aucun actif dans vos favoris pour le moment. Vous pouvez en ajouter depuis le 'Screener Global' ou le 'Scanner & Indicateurs'.")
    else:
        fav_assets_objs = [a for a in assets_db if a["symbol"] in favoris_list]

        for asset in fav_assets_objs:
            p, sma_200, sma_50, rsi, atr_val, history_df_fav = get_market_indicators(asset["symbol"], period="1y", interval="1d")
            if p:
                res = compute_trading_setup(p, atr_val, {
                    "l": asset["liquidity"], "v": asset["volatility"], 
                    "t": asset["trend"], "r": asset["risk_reward"], "c": asset["catalyst"]
                }, sma_200, sma_50, rsi)
                
                score_val = res["score"]
                signal_type = res["signal"]
                is_strong_signal = "FORT" in signal_type or score_val >= 75
                
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
                    if "ACHAT FORT" in signal_type:
                        sig_style = "background-color: #10b981; color: white; padding: 3px 8px; border-radius: 5px; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.1);"
                    elif "VENTE FORTE" in signal_type:
                        sig_style = "background-color: #ef4444; color: white; padding: 3px 8px; border-radius: 5px; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.1);"
                    else:
                        sig_style = "background-color: #f1f5f9; color: #334155; padding: 2px 6px; border-radius: 4px;"
                    
                    score_style = "color: #065f46; font-weight: bold;" if score_val >= 75 else ""
                    st.markdown(f"<span style='{sig_style}'>{signal_type}</span><br><span style='{score_style}'>Score: {score_val}/100</span>", unsafe_allow_html=True)

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
                        
                        if history_df_fav is not None:
                            plot_asset_chart(asset["name"], history_df_fav, res)
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
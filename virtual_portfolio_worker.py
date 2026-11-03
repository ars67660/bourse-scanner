"""Moteur headless du portefeuille virtuel, exécuté par GitHub Actions.

Les fonctions de scoring et la liste des actifs sont extraites directement de scanner.py
pour éviter de maintenir une deuxième version de la stratégie.
"""
import ast
import json
import os
import tempfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

PORTFOLIO_PATH = "portefeuille_virtuel.json"
MAX_POSITIONS = min(50, max(1, int(os.getenv("VP_MAX_POSITIONS", "50"))))
MIN_SCORE = min(100, max(0, int(os.getenv("VP_MIN_SCORE", "65"))))
RISK_PCT = max(0.05, min(5.0, float(os.getenv("VP_RISK_PCT", "1.0"))))
PERIOD = os.getenv("VP_PERIOD", "1y")
INTERVAL = os.getenv("VP_INTERVAL", "1d")
TIMEFRAME_LABEL = os.getenv("VP_TIMEFRAME_LABEL", "1 jour")


def load_strategy():
    with open("scanner.py", "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename="scanner.py")
    assets_node = None
    scoring_node = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "assets_db"
            for target in node.targets
        ):
            assets_node = node
        elif isinstance(node, ast.FunctionDef) and node.name == "compute_opportunity_analysis":
            scoring_node = node
    if assets_node is None or scoring_node is None:
        raise RuntimeError("Impossible d'extraire assets_db ou compute_opportunity_analysis depuis scanner.py")
    namespace = {"pd": pd, "np": np}
    module = ast.Module(body=[assets_node, scoring_node], type_ignores=[])
    exec(compile(module, "scanner.py", "exec"), namespace)
    return namespace["assets_db"], namespace["compute_opportunity_analysis"]


def load_portfolio():
    if not os.path.exists(PORTFOLIO_PATH):
        raise RuntimeError(
            "portefeuille_virtuel.json absent. Ouvre d'abord l'application Streamlit "
            "avec GITHUB_TOKEN configuré pour migrer le portefeuille local vers GitHub."
        )
    with open(PORTFOLIO_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("positions"), list):
        raise RuntimeError("Structure du portefeuille virtuel invalide; aucun écrasement effectué.")
    data.setdefault("initial_capital", 10000.0)
    data.setdefault("cash", data["initial_capital"])
    data.setdefault("positions", [])
    data.setdefault("closed_trades", [])
    return data


def market_history(symbol):
    try:
        frame = yf.Ticker(symbol).history(period=PERIOD, interval=INTERVAL, auto_adjust=False)
        if frame is None or frame.empty or "Close" not in frame:
            return None
        frame = frame.dropna(subset=["Close"])
        return frame if len(frame) >= 35 else None
    except Exception as exc:
        print(f"[WARN] {symbol}: récupération cours impossible ({type(exc).__name__})")
        return None


def mark_to_market(position, price):
    qty = float(position.get("qty", 0))
    entry = float(position.get("entry", 0))
    pnl = (price - entry) * qty if position.get("side") == "LONG" else (entry - price) * qty
    return float(position.get("capital", entry * qty)) + pnl


def close_position(position, exit_price, reason, portfolio):
    entry = float(position.get("entry", 0))
    qty = float(position.get("qty", 0))
    side = position.get("side", "LONG")
    pnl = (exit_price - entry) * qty if side == "LONG" else (entry - exit_price) * qty
    capital = float(position.get("capital", entry * qty))
    portfolio["cash"] = float(portfolio.get("cash", 0)) + capital + pnl
    closed = dict(position)
    closed.update({
        "exit": float(exit_price),
        "pnl_eur": float(pnl),
        "exit_reason": reason,
        "closed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    portfolio.setdefault("closed_trades", []).append(closed)


def save_portfolio(portfolio):
    portfolio["last_cycle"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    folder = os.path.dirname(os.path.abspath(PORTFOLIO_PATH))
    fd, temp_path = tempfile.mkstemp(prefix=".virtual-portfolio-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(portfolio, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, PORTFOLIO_PATH)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def main():
    assets, analyze = load_strategy()
    portfolio = load_portfolio()
    by_symbol = {asset["symbol"]: asset for asset in assets}
    cache = {}
    def get_data(symbol):
        if symbol not in cache:
            history = market_history(symbol)
            cache[symbol] = (history, analyze(history, direction_mode="both_watch") if history is not None else None)
        return cache[symbol]

    remaining = []
    closed_count = 0
    for position in portfolio.get("positions", []):
        symbol = position.get("symbol")
        history, opportunity = get_data(symbol) if symbol in by_symbol else (None, None)
        if history is None or opportunity is None:
            remaining.append(position)
            continue
        price = float(history["Close"].iloc[-1])
        candle = history.iloc[-1]
        high = float(candle.get("High", price))
        low = float(candle.get("Low", price))
        side = position.get("side", "LONG")
        stop = float(position.get("sl", 0))
        target = float(position.get("tp", 0))
        reason = None
        exit_price = price
        # Priorité prudente au stop si SL et TP sont touchés sur la même bougie.
        if side == "LONG":
            if low <= stop:
                reason, exit_price = "Stop-loss", stop
            elif high >= target:
                reason, exit_price = "Take-profit", target
        else:
            if high >= stop:
                reason, exit_price = "Stop-loss", stop
            elif low <= target:
                reason, exit_price = "Take-profit", target
        if reason is None and opportunity["score"] >= MIN_SCORE and opportunity["side"] != side:
            reason = "Signal opposé"
        if reason:
            close_position(position, exit_price, reason, portfolio)
            closed_count += 1
        else:
            position["last_price"] = price
            remaining.append(position)
    portfolio["positions"] = remaining

    candidates = []
    for asset in assets:
        history, opportunity = get_data(asset["symbol"])
        if history is None or opportunity is None:
            continue
        if opportunity["score"] >= MIN_SCORE and opportunity["side"] in ("LONG", "SHORT"):
            candidates.append({"asset": asset, "opp": opportunity})
    candidates.sort(
        key=lambda item: (
            item["opp"]["score"] *
            (0.65 + 0.35 * min(1.0, max(0.0, float(item["opp"].get("rr", 0)) / 2.0)))
        ),
        reverse=True,
    )

    existing = {position.get("symbol") for position in portfolio["positions"]}
    equity = float(portfolio.get("cash", 0)) + sum(
        mark_to_market(position, float(position.get("last_price", position.get("entry", 0))))
        for position in portfolio["positions"]
    )
    risk_budget = max(0.0, equity * RISK_PCT / 100.0)
    opened_count = 0
    for item in candidates:
        if len(portfolio["positions"]) >= MAX_POSITIONS:
            break
        asset, opportunity = item["asset"], item["opp"]
        symbol = asset["symbol"]
        if symbol in existing:
            continue
        entry = float(opportunity["price"])
        stop = float(opportunity["sl"])
        target = float(opportunity["tp_ct"])
        distance = abs(entry - stop)
        side = opportunity["side"]
        valid_levels = (
            entry > 0 and distance > 0 and
            ((side == "LONG" and stop < entry < target) or
             (side == "SHORT" and target < entry < stop))
        )
        if not valid_levels:
            continue
        # Pas de réserve minimale : le cash disponible peut être entièrement engagé,
        # sous réserve du budget de risque et du nombre maximal de positions.
        qty_by_risk = risk_budget / distance if risk_budget > 0 else 0
        qty_by_cash = float(portfolio.get("cash", 0)) / entry
        qty = min(qty_by_risk, qty_by_cash)
        if not np.isfinite(qty) or qty <= 0:
            continue
        capital = qty * entry
        portfolio["cash"] = float(portfolio.get("cash", 0)) - capital
        portfolio["positions"].append({
            "name": asset["name"], "symbol": symbol, "side": side,
            "score": int(opportunity["score"]), "entry": entry, "last_price": entry,
            "sl": stop, "tp": target, "tp_long": float(opportunity["tp_lt"]),
            "qty": qty, "capital": capital,
            "opened_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "timeframe": TIMEFRAME_LABEL,
        })
        existing.add(symbol)
        opened_count += 1
        risk_budget = max(0.0, risk_budget - qty * distance)

    save_portfolio(portfolio)
    print(
        f"Cycle terminé — clôtures: {closed_count}, ouvertures: {opened_count}, "
        f"positions: {len(portfolio['positions'])}/{MAX_POSITIONS}, "
        f"cash: {portfolio['cash']:.2f} EUR, dernier cycle: {portfolio['last_cycle']}"
    )


if __name__ == "__main__":
    main()

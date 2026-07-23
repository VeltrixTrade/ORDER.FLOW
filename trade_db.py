"""
Trade Journal Database Module
SQLite-based trade logging and retrieval for XAU/USD Trading Bot.
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class TradeDB:
    """SQLite trade journal database for logging and managing trades."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Initialize the TradeDB and create the trades table if it doesn't exist.

        Args:
            db_path: Path to the SQLite database file (defaults to DATABASE_PATH env var or trades.db).
        """
        import os
        if db_path is None:
            db_path = os.getenv("DATABASE_PATH", "trades.db")
        self.db_path = db_path
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._create_table()
            try:
                self.conn.execute("DELETE FROM trades WHERE strategy LIKE '%Test%' OR confluences LIKE '%Test%' OR confluences LIKE '%Pipeline%' OR strategy LIKE '%(Test Mode)%'")
                self.conn.commit()
            except Exception:
                pass
            logger.info("TradeDB initialized successfully with database: %s", self.db_path)
        except sqlite3.Error as e:
            logger.critical("Failed to initialize TradeDB: %s", e)
            raise

    def _create_table(self) -> None:
        """Create the trades, subscribers, candles, and live_prices tables if they don't exist."""
        create_sql = """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('BUY', 'SELL')),
            entry_price REAL NOT NULL,
            sl_price REAL NOT NULL,
            tp1_price REAL NOT NULL,
            tp2_price REAL,
            tp3_price REAL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'tp1_hit', 'tp2_hit', 'tp3_hit', 'sl_hit', 'closed')),
            result_pips REAL,
            trade_type TEXT NOT NULL CHECK(trade_type IN ('scalp', 'swing')),
            asset TEXT NOT NULL DEFAULT 'XAUUSD',
            close_price REAL,
            closed_at TEXT
        );
        """
        create_subs_sql = """
        CREATE TABLE IF NOT EXISTS subscribers (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            registered_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'none' CHECK(status IN ('active', 'expired', 'none')),
            expires_at TEXT,
            trading_mode TEXT DEFAULT 'OFF'
        );
        """
        create_candles_sql = """
        CREATE TABLE IF NOT EXISTS candles (
            symbol TEXT,
            timeframe TEXT,
            time TEXT,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER,
            delta REAL DEFAULT 0.0,
            footprint_data TEXT,
            ema10 REAL DEFAULT 0.0,
            ema34 REAL DEFAULT 0.0,
            ema50 REAL DEFAULT 0.0,
            PRIMARY KEY (symbol, timeframe, time)
        );
        """
        create_live_prices_sql = """
        CREATE TABLE IF NOT EXISTS live_prices (
            symbol TEXT PRIMARY KEY,
            bid REAL NOT NULL,
            ask REAL NOT NULL,
            spread REAL NOT NULL,
            server_time TEXT,
            ema10 REAL DEFAULT 0.0,
            ema34 REAL DEFAULT 0.0,
            ema50 REAL DEFAULT 0.0,
            updated_at TEXT NOT NULL
        );
        """
        create_rejected_signals_sql = """
        CREATE TABLE IF NOT EXISTS rejected_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            price_near_boundary INTEGER NOT NULL,
            volume_confirmed INTEGER NOT NULL,
            stacked_imbalance INTEGER NOT NULL,
            absorption INTEGER NOT NULL,
            reason TEXT NOT NULL,
            metrics_snapshot TEXT
        );
        """
        try:
            self.conn.execute(create_sql)
            self.conn.execute(create_subs_sql)
            self.conn.execute(create_candles_sql)
            self.conn.execute(create_live_prices_sql)
            self.conn.execute(create_rejected_signals_sql)
            self.conn.commit()
            
            # Migration to add strategy and confluences to trades table
            try:
                self.conn.execute("ALTER TABLE trades ADD COLUMN strategy TEXT")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                self.conn.execute("ALTER TABLE trades ADD COLUMN confluences TEXT")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass
            
            # Migration to add trading_mode if database already existed
            try:
                self.conn.execute("ALTER TABLE subscribers ADD COLUMN trading_mode TEXT DEFAULT 'OFF'")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass  # Already exists
                
            try:
                self.conn.execute("ALTER TABLE live_prices ADD COLUMN ema10 REAL DEFAULT 0.0")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                self.conn.execute("ALTER TABLE live_prices ADD COLUMN ema34 REAL DEFAULT 0.0")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                self.conn.execute("ALTER TABLE live_prices ADD COLUMN ema50 REAL DEFAULT 0.0")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass
                
            # Migration to add ema10, ema34 and ema50 to candles
            try:
                self.conn.execute("ALTER TABLE candles ADD COLUMN ema10 REAL DEFAULT 0.0")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                self.conn.execute("ALTER TABLE candles ADD COLUMN ema34 REAL DEFAULT 0.0")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                self.conn.execute("ALTER TABLE candles ADD COLUMN ema50 REAL DEFAULT 0.0")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass
                
            # Migration to add delta and footprint_data to candles
            try:
                self.conn.execute("ALTER TABLE candles ADD COLUMN delta REAL DEFAULT 0.0")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                self.conn.execute("ALTER TABLE candles ADD COLUMN footprint_data TEXT")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass
                
            logger.debug("Trades, Subscribers, Candles, and Live Prices tables verified/created.")
        except sqlite3.Error as e:
            logger.error("Failed to create database tables: %s", e)
            raise

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a sqlite3.Row to a plain dictionary."""
        return dict(row)

    def log_trade(
        self,
        direction: str,
        entry: float,
        sl: float,
        tp1: float,
        tp2: Optional[float] = None,
        tp3: Optional[float] = None,
        trade_type: str = "scalp",
        asset: str = "XAUUSD",
        strategy: str = "Trend Continuation",
        confluences: str = ""
    ) -> int:
        """
        Log a new trade to the database.

        Args:
            direction: Trade direction ('BUY' or 'SELL').
            entry: Entry price.
            sl: Stop loss price.
            tp1: First take profit price.
            tp2: Second take profit price (optional).
            tp3: Third take profit price (optional).
            trade_type: Type of trade ('scalp' or 'swing').
            asset: Trading asset (default: 'XAUUSD').
            strategy: The trading strategy name.
            confluences: The technical confluences.

        Returns:
            The ID of the newly created trade.

        Raises:
            ValueError: If direction or trade_type is invalid.
            sqlite3.Error: If database operation fails.
        """
        direction = direction.upper()
        trade_type = trade_type.lower()

        if direction not in ("BUY", "SELL"):
            raise ValueError(f"Invalid direction: {direction}. Must be 'BUY' or 'SELL'.")
        if trade_type not in ("scalp", "swing"):
            raise ValueError(f"Invalid trade_type: {trade_type}. Must be 'scalp' or 'swing'.")

        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        insert_sql = """
        INSERT INTO trades (timestamp, direction, entry_price, sl_price, tp1_price, tp2_price,
                            tp3_price, status, trade_type, asset, strategy, confluences)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
        """
        try:
            cursor = self.conn.execute(
                insert_sql, (timestamp, direction, entry, sl, tp1, tp2, tp3, trade_type, asset, strategy, confluences)
            )
            self.conn.commit()
            trade_id = cursor.lastrowid
            logger.info(
                "Trade logged: id=%d, %s %s @ %.2f, SL=%.2f, TP1=%.2f, type=%s",
                trade_id, direction, asset, entry, sl, tp1, trade_type,
            )
            return trade_id
        except sqlite3.Error as e:
            logger.error("Failed to log trade: %s", e)
            self.conn.rollback()
            raise

    def save_trade(self, trade: Dict[str, Any]) -> int:
        """Helper method to save a trade dictionary directly to the database."""
        direction = trade.get("type") or trade.get("direction") or "BUY"
        entry = float(trade.get("entry_price") or trade.get("entry") or 0.0)
        sl = float(trade.get("stop_loss") or trade.get("sl") or 0.0)
        tp1 = float(trade.get("take_profit_1") or trade.get("tp1") or 0.0)
        tp2 = float(trade.get("take_profit_2") or trade.get("tp2") or 0.0)
        tp3 = float(trade.get("take_profit_3") or trade.get("tp3") or 0.0)
        trade_type = trade.get("category") or trade.get("trade_type") or "scalp"
        strategy = trade.get("strategy") or "Trend Continuation"
        reasons = trade.get("reasons") or []
        confluences = ", ".join(reasons) if isinstance(reasons, list) else str(reasons)
        
        return self.log_trade(
            direction=direction,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            trade_type=trade_type,
            asset="XAUUSD",
            strategy=strategy,
            confluences=confluences
        )

    def update_trade_status(
        self,
        trade_id: int,
        status: str,
        result_pips: Optional[float] = None,
        close_price: Optional[float] = None,
    ) -> bool:
        """
        Update the status of an existing trade.

        Args:
            trade_id: The ID of the trade to update.
            status: New status value.
            result_pips: Realized pips result (optional).
            close_price: Price at which the trade was closed (optional).

        Returns:
            True if the trade was updated, False if trade not found.

        Raises:
            ValueError: If status is invalid.
            sqlite3.Error: If database operation fails.
        """
        valid_statuses = ("active", "tp1_hit", "tp2_hit", "tp3_hit", "sl_hit", "closed")
        status = status.lower()

        if status not in valid_statuses:
            raise ValueError(f"Invalid status: {status}. Must be one of {valid_statuses}.")

        closed_at = None
        if status != "active":
            closed_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        update_sql = """
        UPDATE trades
        SET status = ?, result_pips = ?, close_price = ?, closed_at = ?
        WHERE id = ?
        """
        try:
            cursor = self.conn.execute(
                update_sql, (status, result_pips, close_price, closed_at, trade_id)
            )
            self.conn.commit()

            if cursor.rowcount == 0:
                logger.warning("Trade id=%d not found for update.", trade_id)
                return False

            logger.info(
                "Trade updated: id=%d, status=%s, pips=%s, close_price=%s",
                trade_id, status, result_pips, close_price,
            )
            return True
        except sqlite3.Error as e:
            logger.error("Failed to update trade id=%d: %s", trade_id, e)
            self.conn.rollback()
            raise

    def get_active_trades(self) -> List[Dict[str, Any]]:
        """
        Retrieve all active (open) trades.

        Returns:
            List of trade dictionaries with status 'active'.
        """
        query = "SELECT * FROM trades WHERE status = 'active' ORDER BY timestamp DESC"
        try:
            rows = self.conn.execute(query).fetchall()
            trades = [self._row_to_dict(row) for row in rows]
            logger.debug("Retrieved %d active trades.", len(trades))
            return trades
        except sqlite3.Error as e:
            logger.error("Failed to retrieve active trades: %s", e)
            return []

    def get_trades_by_date(self, date_str: str) -> List[Dict[str, Any]]:
        """
        Retrieve all trades for a specific date.

        Args:
            date_str: Date string in 'YYYY-MM-DD' format.

        Returns:
            List of trade dictionaries for the given date.
        """
        query = """
        SELECT * FROM trades
        WHERE DATE(timestamp) = ?
        ORDER BY timestamp DESC
        """
        try:
            rows = self.conn.execute(query, (date_str,)).fetchall()
            trades = [self._row_to_dict(row) for row in rows]
            logger.debug("Retrieved %d trades for date %s.", len(trades), date_str)
            return trades
        except sqlite3.Error as e:
            logger.error("Failed to retrieve trades for date %s: %s", date_str, e)
            return []

    def get_trades_in_range(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        Retrieve all trades between two dates (inclusive).

        Args:
            start_date: Start date in 'YYYY-MM-DD' format.
            end_date: End date in 'YYYY-MM-DD' format.

        Returns:
            List of trade dictionaries within the date range.
        """
        query = """
        SELECT * FROM trades
        WHERE DATE(timestamp) >= ? AND DATE(timestamp) <= ?
        ORDER BY timestamp DESC
        """
        try:
            rows = self.conn.execute(query, (start_date, end_date)).fetchall()
            trades = [self._row_to_dict(row) for row in rows]
            logger.debug(
                "Retrieved %d trades from %s to %s.", len(trades), start_date, end_date
            )
            return trades
        except sqlite3.Error as e:
            logger.error("Failed to retrieve trades in range %s to %s: %s", start_date, end_date, e)
            return []

    def get_all_closed_trades(self) -> List[Dict[str, Any]]:
        """
        Retrieve all completed (non-active) trades.

        Returns:
            List of trade dictionaries with any closed status.
        """
        query = "SELECT * FROM trades WHERE status != 'active' ORDER BY timestamp DESC"
        try:
            rows = self.conn.execute(query).fetchall()
            trades = [self._row_to_dict(row) for row in rows]
            logger.debug("Retrieved %d closed trades.", len(trades))
            return trades
        except sqlite3.Error as e:
            logger.error("Failed to retrieve closed trades: %s", e)
            return []

    def get_trade_by_id(self, trade_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single trade by its ID.

        Args:
            trade_id: The ID of the trade.

        Returns:
            Trade dictionary if found, None otherwise.
        """
        query = "SELECT * FROM trades WHERE id = ?"
        try:
            row = self.conn.execute(query, (trade_id,)).fetchone()
            if row:
                trade = self._row_to_dict(row)
                logger.debug("Retrieved trade id=%d.", trade_id)
                return trade
            logger.warning("Trade id=%d not found.", trade_id)
            return None
        except sqlite3.Error as e:
            logger.error("Failed to retrieve trade id=%d: %s", trade_id, e)
            return None

    # ────────────────────────────────────────────────────────────
    # Subscriber Management Methods
    # ────────────────────────────────────────────────────────────

    def add_subscriber(self, user_id: int, username: Optional[str] = None, full_name: Optional[str] = None, status: str = 'none') -> None:
        """Add or update a subscriber in the database."""
        query = """
        INSERT INTO subscribers (user_id, username, full_name, registered_at, status)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = COALESCE(excluded.username, username),
            full_name = COALESCE(excluded.full_name, full_name)
        """
        registered_at = datetime.now().isoformat()
        try:
            self.conn.execute(query, (user_id, username, full_name, registered_at, status))
            self.conn.commit()
            logger.info(f"Subscriber {user_id} added/updated in DB with status '{status}'.")
        except sqlite3.Error as e:
            logger.error(f"Failed to add/update subscriber {user_id}: {e}")

    def get_subscriber(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a subscriber's details."""
        query = "SELECT * FROM subscribers WHERE user_id = ?"
        try:
            row = self.conn.execute(query, (user_id,)).fetchone()
            return self._row_to_dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Failed to retrieve subscriber {user_id}: {e}")
            return None

    def activate_subscription(self, user_id: int, days: int = 30) -> None:
        """Activate a user's subscription."""
        expires_at = (datetime.now() + timedelta(days=days)).isoformat()
        query = "UPDATE subscribers SET status = 'active', expires_at = ? WHERE user_id = ?"
        try:
            self.conn.execute(query, (expires_at, user_id))
            self.conn.commit()
            logger.info(f"Subscription activated for user {user_id} for {days} days.")
        except sqlite3.Error as e:
            logger.error(f"Failed to activate subscription for user {user_id}: {e}")

    def deactivate_subscription(self, user_id: int) -> None:
        """Deactivate/expire a user's subscription."""
        query = "UPDATE subscribers SET status = 'expired' WHERE user_id = ?"
        try:
            self.conn.execute(query, (user_id,))
            self.conn.commit()
            logger.info(f"Subscription deactivated for user {user_id}.")
        except sqlite3.Error as e:
            logger.error(f"Failed to deactivate subscription for user {user_id}: {e}")

    def get_all_subscribers(self) -> List[Dict[str, Any]]:
        """Retrieve all subscribers registered in the bot."""
        query = "SELECT * FROM subscribers ORDER BY registered_at DESC"
        try:
            rows = self.conn.execute(query).fetchall()
            return [self._row_to_dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Failed to retrieve subscribers list: {e}")
            return []

    def get_subscriber_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Retrieve a subscriber's details by their username."""
        username = username.lstrip('@').strip().lower()
        query = "SELECT * FROM subscribers WHERE LOWER(username) = ?"
        try:
            row = self.conn.execute(query, (username,)).fetchone()
            return self._row_to_dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Failed to retrieve subscriber by username {username}: {e}")
            return None

    def delete_subscriber(self, user_id: int) -> None:
        """Delete a subscriber from the database."""
        query = "DELETE FROM subscribers WHERE user_id = ?"
        try:
            self.conn.execute(query, (user_id,))
            self.conn.commit()
            logger.info(f"Subscriber {user_id} deleted from DB.")
        except sqlite3.Error as e:
            logger.error(f"Failed to delete subscriber {user_id}: {e}")

    def set_user_trading_mode(self, user_id: int, enabled: bool) -> None:
        """Set user's individual trading mode (ON/OFF)"""
        val = "ON" if enabled else "OFF"
        query = "UPDATE subscribers SET trading_mode = ? WHERE user_id = ?"
        try:
            self.conn.execute(query, (val, user_id))
            self.conn.commit()
            logger.info(f"User {user_id} trading mode set to {val}.")
        except sqlite3.Error as e:
            logger.error(f"Failed to set user {user_id} trading mode: {e}")

    def save_candle(self, symbol: str, timeframe: str, time_str: str, open_p: float, high_p: float, low_p: float, close_p: float, volume: int, delta: float = 0.0, footprint_data: str = None, ema10: float = 0.0, ema34: float = 0.0, ema50: float = 0.0) -> bool:
        """Insert or update a candle in the DB, preserving existing footprint_data or delta/volume/ema if needed."""
        try:
            # Check if candle already exists
            select_query = "SELECT footprint_data, delta, volume, ema10, ema34, ema50 FROM candles WHERE symbol = ? AND timeframe = ? AND time = ?"
            row = self.conn.execute(select_query, (symbol, timeframe, time_str)).fetchone()
            if row:
                # Preserve existing footprint_data if the new one is None or empty/dummy
                if footprint_data is None or footprint_data == "" or footprint_data == "{}":
                    footprint_data = row["footprint_data"]
                else:
                    old_fp_str = row["footprint_data"]
                    if old_fp_str and old_fp_str != "{}" and footprint_data != "{}":
                        try:
                            import json
                            old_fp = json.loads(old_fp_str)
                            new_fp = json.loads(footprint_data)
                            
                            # Merge new_fp into old_fp
                            for price_level, new_vals in new_fp.items():
                                new_ask = new_vals.get("ask", 0)
                                new_bid = new_vals.get("bid", 0)
                                new_vol = new_ask + new_bid
                                
                                if price_level in old_fp:
                                    old_vals = old_fp[price_level]
                                    old_ask = old_vals.get("ask", 0)
                                    old_bid = old_vals.get("bid", 0)
                                    old_vol = old_ask + old_bid
                                    
                                    if old_vol != new_vol:
                                        logger.info(f"🔄 [DATABASE FOOTPRINT UPDATE] Candle: {time_str} | Level: {price_level} | Old Vol: {old_vol} -> New Vol: {new_vol}")
                                else:
                                    logger.info(f"➕ [DATABASE FOOTPRINT INSERT] Candle: {time_str} | Level: {price_level} | Vol: {new_vol}")
                                    
                                old_fp[price_level] = new_vals
                                
                            footprint_data = json.dumps(old_fp)
                        except Exception as merge_err:
                            logger.error(f"Failed to merge footprint data: {merge_err}")

                # Preserve existing non-zero delta if the new one is 0.0
                if delta == 0.0 and row["delta"] is not None and row["delta"] != 0.0:
                    delta = row["delta"]
                # Preserve existing non-zero volume if the new one is 0
                if volume == 0 and row["volume"] is not None and row["volume"] > 0:
                    volume = row["volume"]
                # Preserve existing non-zero EMA values if new ones are 0.0
                if ema10 == 0.0 and row["ema10"] is not None and row["ema10"] > 0.0:
                    ema10 = row["ema10"]
                if ema34 == 0.0 and row["ema34"] is not None and row["ema34"] > 0.0:
                    ema34 = row["ema34"]
                if ema50 == 0.0 and row["ema50"] is not None and row["ema50"] > 0.0:
                    ema50 = row["ema50"]

            query = """
            INSERT OR REPLACE INTO candles (symbol, timeframe, time, open, high, low, close, volume, delta, footprint_data, ema10, ema34, ema50)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            self.conn.execute(query, (symbol, timeframe, time_str, open_p, high_p, low_p, close_p, volume, delta, footprint_data, ema10, ema34, ema50))
            self.conn.commit()
            
            # Prune to keep only the latest 300 candles per symbol and timeframe
            try:
                self.conn.execute("""
                    DELETE FROM candles 
                    WHERE symbol = ? AND timeframe = ? 
                    AND time NOT IN (
                        SELECT time FROM candles 
                        WHERE symbol = ? AND timeframe = ? 
                        ORDER BY time DESC LIMIT 300
                    )
                """, (symbol, timeframe, symbol, timeframe))
                self.conn.commit()
            except Exception as prune_err:
                logger.warning(f"Failed to prune old candles: {prune_err}")
                
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to save candle: {e}")
            return False

    def get_candles(self, symbol: str, timeframe: str, limit: int = 300) -> List[Dict[str, Any]]:
        """Get recent candles for a symbol and timeframe sorted chronologically."""
        query = """
        SELECT * FROM candles 
        WHERE symbol = ? AND timeframe = ? 
        ORDER BY time DESC LIMIT ?
        """
        try:
            rows = self.conn.execute(query, (symbol, timeframe, limit)).fetchall()
            # Reverse to get chronological order
            candles = [dict(row) for row in rows]
            candles.reverse()
            return candles
        except sqlite3.Error as e:
            logger.error(f"Failed to retrieve candles: {e}")
            return []

    def save_live_price(self, symbol: str, bid: float, ask: float, spread: float, server_time: str, ema10: float = 0.0, ema34: float = 0.0, ema50: float = 0.0) -> bool:
        """Save/update the latest live price for a symbol."""
        query = """
        INSERT OR REPLACE INTO live_prices (symbol, bid, ask, spread, server_time, ema10, ema34, ema50, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        updated_at = datetime.utcnow().isoformat()
        try:
            self.conn.execute(query, (symbol, bid, ask, spread, server_time, ema10, ema34, ema50, updated_at))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to save live price: {e}")
            return False

    def get_live_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get the latest cached live price for a symbol."""
        query = "SELECT * FROM live_prices WHERE symbol = ?"
        try:
            row = self.conn.execute(query, (symbol,)).fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Failed to retrieve live price: {e}")
    def log_rejected_signal(
        self,
        signal_type: str,
        price_near_boundary: bool,
        volume_confirmed: bool,
        stacked_imbalance: bool,
        absorption: bool,
        reason: str,
        metrics_snapshot: Optional[str] = None
    ) -> int:
        """Logs a rejected signal in the database for audit trail."""
        sql = """
        INSERT INTO rejected_signals (
            timestamp, signal_type, price_near_boundary, volume_confirmed,
            stacked_imbalance, absorption, reason, metrics_snapshot
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """
        now_str = datetime.utcnow().isoformat() + "Z"
        if metrics_snapshot is not None and not isinstance(metrics_snapshot, str):
            try:
                import json
                metrics_snapshot = json.dumps(metrics_snapshot)
            except Exception:
                metrics_snapshot = str(metrics_snapshot)
        try:
            cursor = self.conn.cursor()
            cursor.execute(sql, (
                now_str,
                signal_type,
                1 if price_near_boundary else 0,
                1 if volume_confirmed else 0,
                1 if stacked_imbalance else 0,
                1 if absorption else 0,
                reason,
                metrics_snapshot
            ))
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Failed to log rejected signal: {e}")
            return 0

    def get_rejected_signals(self, limit: int = 50, time_filter: str = 'all') -> List[Dict[str, Any]]:
        """Retrieve recent rejected signals from the database, optionally filtered by time."""
        try:
            if time_filter == 'today':
                today_start = datetime.utcnow().strftime("%Y-%m-%dT00:00:00")
                query = "SELECT * FROM rejected_signals WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?"
                rows = self.conn.execute(query, (today_start, limit)).fetchall()
            elif time_filter == 'week':
                week_start = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00")
                query = "SELECT * FROM rejected_signals WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?"
                rows = self.conn.execute(query, (week_start, limit)).fetchall()
            else: # all
                query = "SELECT * FROM rejected_signals ORDER BY timestamp DESC LIMIT ?"
                rows = self.conn.execute(query, (limit,)).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Failed to retrieve rejected signals: {e}")
            return []

    def get_all_rejected_signals(self) -> List[Dict[str, Any]]:
        """Alias for get_rejected_signals."""
        return self.get_rejected_signals(limit=1000)

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent trades (both active and completed/failed)."""
        query = "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?"
        try:
            rows = self.conn.execute(query, (limit,)).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Failed to retrieve recent trades: {e}")
            return []

    def close(self) -> None:
        """Close the database connection."""
        try:
            self.conn.close()
            logger.info("TradeDB connection closed.")
        except sqlite3.Error as e:
            logger.error("Error closing TradeDB connection: %s", e)

    def __del__(self) -> None:
        """Ensure database connection is closed on garbage collection."""
        try:
            if hasattr(self, "conn") and self.conn:
                self.conn.close()
        except Exception:
            pass

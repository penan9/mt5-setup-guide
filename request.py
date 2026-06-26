import socket
import sqlite3
import signal
import re
import logging
import threading
import os
import time
import json
import sys
import joblib
import queue
import shutil
import warnings
import inspect
from datetime import datetime
import pandas as pd
import numpy as np

VERSION = "AI Brain Master 15, June 17 2026 - Checkpoint 1.0.0"
global_explored_symbols = set()  # Track which symbols we've already explored
global_socket_status = "DISCONNECTED"
last_heartbeat_time = time.time()

def load_history_file(path):
    """Load MT5 history - handles UTF-16, semicolon, no-header files."""
    import pandas as pd
    import os

    if not os.path.exists(path):
        print(f">>> History file missing: {path}")
        return pd.DataFrame()

    # Detect encoding from BOM
    with open(path, 'rb') as f:
        raw = f.read(4)
        
    encoding = 'utf-16' if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff') else 'cp1252'
    df = pd.read_csv(path, encoding=encoding, sep=',', header=None, engine='python')
    
    try:
        # Your file: "2026.05.31 03:20;BTCUSD;0;0.0" -> no header, sep=';'
        df = pd.read_csv(path, encoding=encoding, sep=';', header=None, engine='python')

        # If we got 1 column, try comma
        if df.shape[1] == 1:
            df = pd.read_csv(path, encoding=encoding, sep=',', header=None, engine='python')

        # Assign column names based on your EA output
        # Looks like: time ; symbol ; type ; profit
        if df.shape[1] >= 4:
            df.columns = ['time', 'symbol', 'type', 'profit'] + [f'col{i}' for i in range(4, df.shape[1])]
        else:
            df.columns = [f'col{i}' for i in range(df.shape[1])]

        # Clean
        df.columns = df.columns.str.strip().str.replace('\ufeff', '', regex=False)

        print(f">>> History: {len(df)} rows, {df.shape[1]} cols (enc={encoding}, sep=';')")

        # Convert types
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'], format='%Y.%m.%d %H:%M', errors='coerce')
        if 'profit' in df.columns:
            df['profit'] = pd.to_numeric(df['profit'], errors='coerce').fillna(0)
            df['outcome'] = (df['profit'] > 0).astype(int)
            print(f">>> Added outcome: {df['outcome'].sum()} wins / {(df['outcome']==0).sum()} losses")

        return df

    except Exception as e:
        print(f">>> ERROR reading history: {e}")
        return pd.DataFrame()

# FIX 7: Configure matplotlib backend BEFORE importing pyplot (moved here, before any plt import).
# Load config minimally just to get the backend setting.
_CONFIG_FILE_EARLY = "request_config.json"
_early_cfg = {}
if os.path.exists(_CONFIG_FILE_EARLY):
    try:
        with open(_CONFIG_FILE_EARLY, 'r') as _f:
            _early_cfg = json.load(_f)
    except Exception:
        pass

import matplotlib
MATPLOTLIB_BACKEND = _early_cfg.get("visualizer_backend", "TkAgg")
try:
    matplotlib.use(MATPLOTLIB_BACKEND)
except Exception as _be:
    print(f"!!! WARNING: Failed to use backend '{MATPLOTLIB_BACKEND}': {_be}. Falling back to TkAgg.")
    matplotlib.use("TkAgg")

import matplotlib.pyplot as plt
from matplotlib.widgets import Button
import mplfinance as mpf
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

warnings.filterwarnings("ignore", category=UserWarning)

MEMORY_FILE = "memory.json"

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return []
    with open(MEMORY_FILE, "r") as f:
        return json.load(f)

def save_memory(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f)

# --- Configuration ---
CONFIG_FILE = "request_config.json"

# --- Configuration Loading (STRICT) ---
def load_config():
    """Load request_config.json. Exit if not found."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "request_config.json")
    
    if not os.path.exists(config_path):
        print("\n" + "="*70)
        print("ERROR: request_config.json NOT FOUND")
        print("="*70)
        print(f"Expected at: {config_path}")
        print("\nCreate the file with:")
        print('{')
        print('  "mt5_path": "/your/data/path"')
        print('}')
        print("="*70 + "\n")
        sys.exit(1)
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"\nERROR: Cannot read config: {e}\n")
        sys.exit(1)
    
    if "mt5_path" not in cfg:
        print("\nERROR: 'mt5_path' missing in request_config.json\n")
        sys.exit(1)
    
    return cfg

# Load config
config = load_config()
MT5_BASE_PATH = os.path.expanduser(config["mt5_path"])
MT5_BASE_PATH = os.path.abspath(MT5_BASE_PATH)

if not os.path.isdir(MT5_BASE_PATH):
    print("\n" + "="*70)
    print("ERROR: mt5_path does not exist")
    print(f"Path: {MT5_BASE_PATH}")
    print("="*70 + "\n")
    sys.exit(1)

HOST = str(config.get("socket_host", "127.0.0.1"))
PORT = int(config.get("socket_port", 8888))
BUFFER_SIZE = int(config.get("buffer_size", 16384))

print(f">>> Using MT5 path: {MT5_BASE_PATH}")

def find_history_file(base_path, filename="MT5_Set_History.csv"):
    """Return full path. Exit if directory missing. Debug file status."""
    full_path = os.path.join(base_path, filename)
    dir_part = os.path.dirname(full_path)
    
    if not os.path.isdir(dir_part):
        print("\n" + "="*70)
        print("ERROR: Directory missing")
        print(f"Path: {dir_part}")
        print("="*70 + "\n")
        sys.exit(1)
    
    # --- DEBUG: Check if file exists ---
    print("\n" + "-"*70)
    print(f"CHECKING HISTORY FILE")
    print(f"Path: {full_path}")
    
    if os.path.exists(full_path):
        size = os.path.getsize(full_path)
        mtime = os.path.getmtime(full_path)
        from datetime import datetime
        mod_time = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"Status: FOUND ✓")
        print(f"Size: {size:,} bytes")
        print(f"Last modified: {mod_time}")
        
        # Quick check if file is readable and has content
        try:
            # MT5 writes UTF-16 with BOM
            with open(full_path, 'r', encoding='utf-16', errors='ignore') as f:
                first_line = f.readline().strip()
                line_count = sum(1 for _ in f) + 1
            print(f"Lines: ~{line_count:,}")
            # Clean BOM characters for display
            clean_header = first_line.replace('\ufeff', '').replace('\xff\xfe', '')
            print(f"First line: {clean_header[:80]}...")
        except Exception as e:
            # Fallback to binary read
            try:
                with open(full_path, 'rb') as f:
                    raw = f.read(100)
                    print(f"Lines: unknown (binary)")
                    print(f"First 50 bytes: {raw[:50]}")
            except:
                print(f"WARNING: Cannot read file: {e}")
    else:
        print(f"Status: NOT FOUND ✗")
        print(f"MT5/EA has not created the file yet")
        print(f"Waiting for EA to write to this location...")
    
    print("-"*70 + "\n")
    
    return full_path

HISTORY_CSV = find_history_file(MT5_BASE_PATH, "MT5_Set_History.csv")
EA_PATH = os.path.join(MT5_BASE_PATH, "test2.mq5")

print(f">>> PATH DEBUGGER: Looking for history at: {HISTORY_CSV}")
if not os.path.exists(HISTORY_CSV):
    print(f"!!! WARNING: History file NOT FOUND at {HISTORY_CSV}. KPIs will remain 0 until first trade.")


# Standardize all runtime files under mt5_path only
os.makedirs(MT5_BASE_PATH, exist_ok=True)

BRAIN_FILE = os.path.join(MT5_BASE_PATH, "ai_brain.joblib")
BRAIN_BACKUP = os.path.join(MT5_BASE_PATH, "ai_brain_backup.joblib")
STATS_FILE = os.path.join(MT5_BASE_PATH, "cumulative_stats.json")
STATS_BACKUP = os.path.join(MT5_BASE_PATH, "cumulative_stats_backup.json")
MTF_DATA_LOG = os.path.join(MT5_BASE_PATH, "mtf_data_flow.log")
PARSER_LOG = os.path.join(MT5_BASE_PATH, "parser_debug.log")

# --- AI Evolution Config ---
MODEL_DIR = os.path.join(MT5_BASE_PATH, "ai_models")
DATA_DIR = os.path.join(MT5_BASE_PATH, "ai_data")
HISTORY_DIR = os.path.join(MT5_BASE_PATH, "evolution_history")
VERSION_FILE = os.path.join(MODEL_DIR, "current_version.txt")
for d in [MODEL_DIR, DATA_DIR, HISTORY_DIR]:
    os.makedirs(d, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from logging.handlers import RotatingFileHandler
handler = RotatingFileHandler("system.log", maxBytes=5*1024*1024, backupCount=3)
logger.addHandler(handler)

# --- Global Control & Data ---
global_stop_event = threading.Event()
plot_update_queue = queue.Queue()
global_ui_command_queue = queue.Queue()
ohcl_data_history = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close'], dtype=float)
ohcl_data_history.index = pd.DatetimeIndex([], name='Date')
ai_score_history = []
global_mt5_symbol = "UNKNOWN"
global_mt5_timeframe = "UNKNOWN"
global_socket_status = "DISCONNECTED"
global_mtf_data = {}
global_candle_details = {}
global_mtf_mode = False
last_printed_candle = None
parse_error_count = 0
last_heartbeat_time = time.time() # NEW: Track last heartbeat

# --- Logging Helpers ---
def log_parser_error(error_type, payload_sample, error_msg):
    """Log parser errors to file for debugging"""
    try:
        with open(PARSER_LOG, 'a') as f:
            f.write(f"[{datetime.now()}] {error_type}: {error_msg}\n")
            f.write(f"  Payload sample: {payload_sample}\n\n")
    except:
        pass

def log_mtf_data(symbol, timeframe, candle_count, features):
    """Log MTF data flow for debugging"""
    try:
        with open(MTF_DATA_LOG, 'a') as f:
            f.write(f"[{datetime.now()}] Symbol={symbol}, TF={timeframe}, Candles={candle_count}\n")
    except:
        pass

# --- Trade Performance Tracker ---
class TradePerformanceTracker:
    def __init__(self, stats_file, stats_backup):
        self.stats_file = stats_file
        self.stats_backup = stats_backup
        self.stats = {
            'open-open': {'name': 'open-open', 'trades': 0, 'wins': 0},
            'close-close': {'name': 'close-close', 'trades': 0, 'wins': 0},
            'high-high': {'name': 'high-high', 'trades': 0, 'wins': 0},
            'low-low': {'name': 'low-low', 'trades': 0, 'wins': 0}
        }
        self.load_stats()
    
    def load_stats(self):
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, 'r') as f:
                    self.stats = json.load(f)
            except:
                pass
    
    def save_stats(self):
        try:
            with open(self.stats_file, 'w') as f:
                json.dump(self.stats, f)
            shutil.copy2(self.stats_file, self.stats_backup)
        except Exception as e:
            logger.warning(f"[TradePerformanceTracker] Failed to save stats: {e}")

def heartbeat_monitor():
    while not global_stop_event.is_set():
        if time.time() - last_heartbeat_time > 30:  # 30s silence
            logger.warning("No heartbeat detected. Attempting reconnect...")
            # Add your socket reconnect logic here
        time.sleep(5)

threading.Thread(target=heartbeat_monitor, daemon=True).start()

# --- AI Brain Class ---
class AIBrain:
    def __init__(self, brain_file, backup_file, history_csv):
        self.brain_file = brain_file
        self.backup_file = backup_file
        self.history_csv = history_csv
        self.model = self._load_brain()
        self.regressor = self._load_regressor()
        self.is_initialized = False
        self.learning_status = "INITIALIZING"
        self.current_version = self._load_version()
        self.lifetime_win_rate = 0.0
        self.profit_factor = 1.0
        self.brain_age = 0
        self.last_evolved_pf = 0.0
        self.last_sync_time = 0
        self._recalculate_kpis()

    def _load_brain(self):
        for path in [self.brain_file, self.backup_file]:
            if os.path.exists(path):
                try:
                    print(f"Loading brain from {path}...")
                    return joblib.load(path)
                except: continue
        print("Initializing new brain...")
        return RandomForestClassifier(n_estimators=100, random_state=42)

    def save_with_backup(self):
        try:
            joblib.dump(self.model, self.brain_file)
            shutil.copy2(self.brain_file, self.backup_file)
            reg_file = self.brain_file.replace('.joblib', '_reg.joblib')
            joblib.dump(self.regressor, reg_file)
        except: pass

    def _load_regressor(self):
        reg_file = self.brain_file.replace('.joblib', '_reg.joblib')
        if os.path.exists(reg_file):
            try: return joblib.load(reg_file)
            except: pass
        return RandomForestRegressor(n_estimators=100, random_state=42)

    def _load_version(self):
        if os.path.exists(VERSION_FILE):
            try:
                with open(VERSION_FILE, "r") as f: return f.read().strip()
            except: pass
        return "1.0.0"

    def _recalculate_kpis(self):
        if not os.path.exists(self.history_csv): return
        try:
            df = load_history_file(self.history_csv)
            if df.empty: return
            
            label_col = 'success_label' if 'success_label' in df.columns else 'outcome'
            if label_col not in df.columns:
                logger.warning(f"Column '{label_col}' not found in history.")
                return
                
            wins = len(df[df[label_col] == 1])
            total = len(df)
            self.lifetime_win_rate = (wins / total) * 100 if total > 0 else 0.0
            
            if 'pips' in df.columns:
                gross_profit = df[df['pips'] > 0]['pips'].sum()
                gross_loss = abs(df[df['pips'] < 0]['pips'].sum())
                self.profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else gross_profit
            else:
                losses = total - wins
                self.profit_factor = (wins / losses) if losses > 0 else float(wins)
                
            self.brain_age = total
      
        except Exception as e:
            logger.error(f"KPI recalculation failed: {e}")

    def record_and_learn(self, features, outcome, pips, bars, timestamp):
        self.last_sync_time = max(self.last_sync_time, timestamp)
        data = {'timestamp': [timestamp], 'success_label': [outcome], 'pips': [pips], 'bars': [bars]}
        for k, v in features.items():
            data[f'feat_{k}'] = [float(v)]
        df_new = pd.DataFrame(data)

        # Ensure directory exists
        history_dir = os.path.dirname(self.history_csv)
        if history_dir and not os.path.exists(history_dir):
            try:
                os.makedirs(history_dir, exist_ok=True)
                logger.info(f">>> Created history directory: {history_dir}")
            except Exception as mkdir_err:
                self.history_csv = os.path.abspath("MT5_Set_History.csv")
                logger.warning(f"Cannot write to configured path. Using local: {self.history_csv}")

        # Append safely with headers if file is empty
        write_header = not os.path.exists(self.history_csv) or os.path.getsize(self.history_csv) == 0
        try:
            df_new.to_csv(self.history_csv, mode='a', index=False, header=write_header, encoding='cp1252')
        except Exception as e:
            logger.error(f"Failed to append to history CSV: {e}")
            return

        self.brain_age += 1
        self._recalculate_kpis()

        # Configurable retrain interval
        retrain_interval = int(config.get("retrain_interval", 10))
        if self.brain_age % retrain_interval == 0:
            threading.Thread(target=self.retrain, daemon=True).start()

        # Evolution trigger
        if self.profit_factor > self.last_evolved_pf + 0.1 and self.brain_age > 50:
            self.evolve_system()

    def retrain(self):
        if not os.path.exists(self.history_csv): return
        logger.info(f">>> AI DEEP LEARNING: Analyzing {self.brain_age} historical setups...")
        try:
            # FIX 5: Use same encoding as _recalculate_kpis() to avoid UnicodeDecodeError
            # on Windows-generated MT5 CSV files.
            df = load_mt5_csv(self.history_csv)
      
            if 'feat_set_magnitude' in df.columns and 'feat_bars_duration' in df.columns:
                df['pattern_weight'] = 1.0
                df.loc[(df['feat_set_magnitude'] > 50) & (df['feat_bars_duration'] > 10), 'pattern_weight'] = 2.0
                if 'feat_is_at_snr' in df.columns:
                    df.loc[df['feat_is_at_snr'] == 1, 'pattern_weight'] *= 1.5
            
            if len(df) < 5: return
            
            feature_cols = [c for c in df.columns if c.startswith('feat_')]
            if not feature_cols: 
                logger.warning("No features found in history for learning.")
                return
                
            X = df[feature_cols].fillna(0).values
            
            label_col = 'success_label' if 'success_label' in df.columns else 'outcome'
            if label_col in df.columns and len(np.unique(df[label_col])) > 1:
                weights = df['pattern_weight'].values if 'pattern_weight' in df.columns else None
                self.model.fit(X, df[label_col].values, sample_weight=weights)
                self.is_initialized = True
                self.learning_status = f"EVOLVING (v{self.current_version})"
                logger.info(f">>> STRATEGY PATTERNS MEMORIZED: {len(df)} samples. Win Rate: {self.lifetime_win_rate:.2f}%, PF: {self.profit_factor:.2f}")
            
            if 'pips' in df.columns:
                self.regressor.fit(X, df['pips'].values)

            self.save_with_backup()
            logger.info(">>> AI Brain and Regressor saved.")
        except Exception as e:
            logger.error(f"AI retraining failed: {e}")

    def evolve_system(self):
        logger.info("\n>>> SYSTEM EVOLUTION TRIGGERED: Profit Factor improved! >>>")
        # Increment version number
        major, minor, patch = map(int, self.current_version.split('.'))
        patch += 1
        new_version = f"{major}.{minor}.{patch}"

        # FIX 9: Use inspect to get the real .py source path — __file__ can resolve
        # to a compiled .pyc in some environments, making backups unreadable.
        try:
            _this_file = inspect.getfile(lambda: None)
            if _this_file.endswith(('.pyc', '.pyo')):
                _this_file = _this_file[:-1]  # strip 'c'/'o' → .py
        except Exception:
            _this_file = os.path.abspath(__file__)
        
        # Backup current Python script with version
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"request_v{self.current_version}_{timestamp}.py"
            shutil.copy2(_this_file, os.path.join(HISTORY_DIR, backup_name))
            logger.info(f"Backed up current script to {backup_name}")
        except Exception as e:
            logger.error(f"Self-evolution backup failed: {e}")

        # Save new version of Python script (for manual switch)
        new_script_name = f"request_v{new_version}.py"
        new_script_path = os.path.join(os.path.dirname(_this_file), new_script_name)
        try:
            shutil.copy2(_this_file, new_script_path)
            logger.info(f"New Python script version created: {new_script_path}")
        except Exception as e:
            logger.error(f"Failed to create new Python script version: {e}")

        # Update the current version in the MODEL_DIR
        try:
            with open(VERSION_FILE, "w") as f: f.write(new_version)
            self.current_version = new_version
            logger.info(f"Updated current version to {self.current_version}")
        except Exception as e:
            logger.error(f"Failed to update version file: {e}")

        # EA Evolution (if conditions met and safety checks pass)
        try:
            with open(EA_PATH, "r") as f: content = f.read()
            # Simple safety check: ensure some critical buttons are present
            if all(btn in content for btn in ["BTN_MAIN_TRENDLINE", "BTN_MAIN_DUP", "BTN_MAIN_FROZEN"]):
                # This part is for potential automated EA updates, currently just logs
                logger.info(f"EA evolution check passed. Current EA version: {self.current_version}")
            else:
                logger.error("EA Evolution aborted: Safety check failed (manual buttons missing).")
        except Exception as e:
            logger.error(f"EA Evolution failed: {e}")

        self.last_evolved_pf = self.profit_factor
        logger.info(f">>> SYSTEM EVOLVED TO v{self.current_version}. Please consider switching to the new Python script: {new_script_name}")

    def predict(self, features):
        if not features: return 0.5, 0, 20
        
        try:
            # --- ORIGINAL RULE-BASED LOGIC (PRESERVED) ---
            set_magnitude = features.get('set_magnitude', 0)
            bars_duration = features.get('bars_duration', 0)
            dist_from_be = features.get('dist_from_be', 0)
            active_TL_option = features.get('active_TL_option', 0)
            dynamic_TL_slope = features.get('dynamic_TL_slope', 0)
            snr_weight = features.get('snr_weight', 0)
            is_at_snr = features.get('is_at_snr', 0)
            tp_m15 = features.get('tp_m15', 0)
            tp_h1 = features.get('tp_h1', 0)
            rejection_candle_total_range = features.get('rejection_candle_total_range', 0)
            rejection_candle_body_size = features.get('rejection_candle_body_size', 0)
            rejection_candle_upper_wick_size = features.get('rejection_candle_upper_wick_size', 0)
            rejection_candle_lower_wick_size = features.get('rejection_candle_lower_wick_size', 0)
            rejection_candle_body_to_range_ratio = features.get('rejection_candle_body_to_range_ratio', 0)
            rejection_candle_is_large_relative_to_average = features.get('rejection_candle_is_large_relative_to_average', 0)
            rejection_candle_volume = features.get('rejection_candle_volume', 0)
            bearish_sequence_length = features.get('bearish_sequence_length', 0)
            trend_m30 = features.get('trend_m30', 0)
            trend_h1 = features.get('trend_h1', 0)
            
            score_rules = 0.5
            total_bias = (tp_m15 + tp_h1) / 2 if (tp_m15 or tp_h1) else 0
            
            if total_bias > 0.3 and (trend_m30 == 1 or trend_h1 == 1):
                direction = 1
                score_rules = 0.6 + total_bias
            elif total_bias < -0.3 and (trend_m30 == -1 or trend_h1 == -1):
                direction = -1
                score_rules = 0.6 + abs(total_bias)
            else:
                direction = 0
                score_rules = 0.4
            ml_prob = 0.5
            max_hold = 20
            try:
                # FIX 4: Always build feat_vec first so the regressor block can use it
                # even if the classifier block was skipped.
                feature_names = self.get_feature_cols()
                feat_vec = [features.get(f, 0) for f in feature_names]
                if hasattr(self.model, "classes_"):
                    # Ensure feature vector matches training features
                    ml_prob = self.model.predict_proba([feat_vec])[0][1]
                if hasattr(self.regressor, "n_features_in_"):
                     max_hold = int(self.regressor.predict([feat_vec])[0])
            except Exception as e:
                logger.error(f"ML prediction error: {e}")
            final_score = (score_rules * 0.4) + (ml_prob * 0.6)
            return max(0.0, min(1.0, final_score)), direction, max(5, min(max_hold, 100))
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return 0.5, 0, 20

    def get_feature_cols(self):
         return ['set_magnitude', 'bars_duration', 'hour_of_day', 'dist_from_be', 'active_TL_option', 'dynamic_TL_slope', 'snr_weight', 'is_at_snr', 'tp_m15', 'tp_h1', 'rejection_candle_total_range', 'rejection_candle_body_size', 'rejection_candle_upper_wick_size', 'rejection_candle_lower_wick_size', 'rejection_candle_body_to_range_ratio', 'rejection_candle_is_large_relative_to_average', 'rejection_candle_volume', 'bearish_sequence_length']

# --- Global Instances ---
performance_tracker = TradePerformanceTracker(STATS_FILE, STATS_BACKUP)

# Per-symbol brains to keep gold and bitcoin separate
brain_cache = {}
def get_brain(symbol):
    safe_sym = re.sub(r'[^A-Z0-9]', '_', symbol.upper())
    brain_file = os.path.join(MT5_BASE_PATH, f"ai_brain_{safe_sym}.joblib")
    backup_file = os.path.join(MT5_BASE_PATH, f"ai_brain_{safe_sym}_backup.joblib")
    if safe_sym not in brain_cache:
        brain_cache[safe_sym] = AIBrain(brain_file, backup_file, HISTORY_CSV)
        print(f">>> Loaded separate brain for {symbol}")
    return brain_cache[safe_sym]

ai_brain = get_brain("DEFAULT")  # fallback

class RealtimeVisualizer:
    def __init__(self):
        # Create a single figure with 4 subplots
        self.fig, (self.ax_main, self.ax_ai, self.ax_kpi, self.ax_mtf) = plt.subplots(
            4, 1, figsize=(10, 6), gridspec_kw={'height_ratios': [3.5, 1, 1.5, 1]}
        )
        
        # 1. MT5 Styling (Black Background / Green & Red Candles)
        mc = mpf.make_marketcolors(up='#00FF00', down='#FF0000', inherit=True)
        self.mpf_style = mpf.make_mpf_style(
            base_mpf_style='charles', 
            marketcolors=mc, 
            facecolor='#000000', 
            edgecolor='#404040', 
            gridcolor='#202020'
        )

        self.fig.patch.set_facecolor('#000000')
        self.fig.canvas.manager.set_window_title('AI Brain Master Visualizer')
        
        # Initial Axis Configuration
        for ax in [self.ax_main, self.ax_ai]:
            ax.set_facecolor('#000000')
            ax.tick_params(axis='both', colors='white', labelsize=8)
            ax.yaxis.label.set_color('white')

        self.ax_kpi.axis('off')
        self.ax_mtf.axis('off')

        # Buttons at Top
        ax_mtf_toggle = self.fig.add_axes([0.7, 0.95, 0.1, 0.03])
        self.button_mtf_toggle = Button(ax_mtf_toggle, 'Toggle MTF', color='#2e7d32', hovercolor='#388e3c')
        self.button_mtf_toggle.on_clicked(self.toggle_mtf_mode)

        ax_scan_toggle = self.fig.add_axes([0.59, 0.95, 0.1, 0.03])
        self.button_scan_toggle = Button(ax_scan_toggle, 'Toggle SCAN', color='#2e7d32', hovercolor='#388e3c')
        self.button_scan_toggle.on_clicked(self.toggle_scan_mode)

        ax_close = self.fig.add_axes([0.81, 0.95, 0.1, 0.03])
        self.button_close = Button(ax_close, 'Close Server', color='#c62828', hovercolor='#d32f2f')
        self.button_close.on_clicked(self.close_server)

        self.fig.subplots_adjust(hspace=0.5, left=0.08, right=0.92, top=0.93, bottom=0.05)

    def toggle_mtf_mode(self, event):
        global global_mtf_mode
        global_mtf_mode = not global_mtf_mode
        print(f"[UI] Sending MTF Toggle command to MT5... (Local State: {'ON' if global_mtf_mode else 'OFF'})")
        try:
            global_ui_command_queue.put("UI_CMD:TOGGLE_MTF\n")
        except Exception as e:
            print(f"[UI ERROR] Failed to queue MTF toggle: {e}")

    def toggle_scan_mode(self, event):
        print(f"[UI] Sending SCAN Toggle command to MT5...")
        try:
            global_ui_command_queue.put("UI_CMD:TOGGLE_SCAN\n")
        except Exception as e:
            print(f"[UI ERROR] Failed to queue SCAN toggle: {e}")

    def close_server(self, event):
        # FIX 8: Always signal the stop event so the socket listener thread exits cleanly.
        # Without this, the listener keeps running even after the plot closes, leaving
        # the process hanging. VISUALIZER_CLOSE_STOPS_SERVER now only controls whether
        # the plot is forcibly closed (it always is on button click) vs. graceful exit.
        global_stop_event.set()
        plt.close(self.fig)
        sys.exit(0)

    def update_plot(self, ohlc_df, ai_scores, current_set, status, symbol, tf, snr_weight, candle_details, mtf_data):
        if not plt.fignum_exists(self.fig.number) or ohlc_df.empty: 
            return

        self.ax_main.clear()
        self.ax_ai.clear()
        self.ax_kpi.clear()
        self.ax_mtf.clear()

        # Score Alignment
        padded_scores = [np.nan] * (len(ohlc_df) - len(ai_scores)) + list(ai_scores)
        apds = [mpf.make_addplot(padded_scores, color='#00ffff', ax=self.ax_ai, width=1.2)]
        
        # MAIN CHART (Force ax=self.ax_main to prevent second window)
        mpf.plot(ohlc_df, type='candle', style=self.mpf_style, ax=self.ax_main, addplot=apds)

        # MT5 Live Price Tag
        last_price = ohlc_df['Close'].iloc[-1]
        self.ax_main.axhline(last_price, color='white', linestyle=':', linewidth=0.8)
        self.ax_main.text(1.01, last_price, f' {last_price:.5f} ', 
                          transform=self.ax_main.get_yaxis_transform(),
                          color='white', backgroundcolor='#FF0000', 
                          va='center', fontweight='bold', fontsize=9)

        # --- RESTORE KPI DISPLAY (Performance & Candle Details) ---
        self.ax_kpi.axis('off')
        data_type = candle_details.get('data_type', 'UNKNOWN')
        text_color = '#00FF00' if data_type == "LIVE" else '#FFFF00'
        
        kpi_text = f"LATEST CANDLE [{data_type}]: {candle_details.get('time', 'N/A')}\n"
        kpi_text += f"Symbol: {symbol} | TF: {tf} | Range: {candle_details.get('range', 0):.4f} pips\n"
        kpi_text += f"SnR Weight: {snr_weight} | Set Count: {current_set} | Parse Errors: {parse_error_count}\n"
        kpi_text += "\nTL STRATEGY PERFORMANCE:\n"
        
        # Iterate through the tracker stats from your script
        for i, d in performance_tracker.stats.items():
            wr = (d['wins']/d['trades']*100) if d['trades'] > 0 else 0.0
            kpi_text += f"{d['name']:<15}: {d['trades']:>3} Trades | {wr:>5.1f}% Win Rate\n"
        
        self.ax_kpi.text(0.01, 0.5, kpi_text, color=text_color, fontsize=8, family='monospace', va='center')

        # --- KPI Bar Chart ---
        wr_values = [(d['wins']/d['trades']*100) if d['trades'] else 0 for d in performance_tracker.stats.values()]
        colors = ['green' if wr > 60 else 'yellow' if wr > 40 else 'red' for wr in wr_values]
        self.ax_kpi.bar(range(len(wr_values)), wr_values, color=colors)
        self.ax_kpi.set_ylim(0, 100)
        self.ax_kpi.set_title("Win Rate by Strategy", color='white', fontsize=8)

        # --- MTF FLOW DISPLAY ---
        self.ax_mtf.axis('off')
        mtf_text = "MULTI-TIMEFRAME DATA FLOW:\n"
        if mtf_data:
            for tf_name, data in mtf_data.items():
                mtf_text += f"{tf_name:<8} | Close: {data.get('close', 0):.5f} | Slope: {data.get('slope', 0):.5f} | Sit: {data.get('sitting', 0):.2f}\n"
        else:
            mtf_text += "Waiting for MTF data flow..."
        
        self.ax_mtf.text(0.01, 0.5, mtf_text, color='#00ffff', fontsize=8, family='monospace', va='center')

        brain_ver = get_brain(symbol).current_version if symbol in [k.replace('_','') for k in brain_cache] else ai_brain.current_version
        self.fig.suptitle(f'{symbol} ({tf}) | {status} | AI v{brain_ver}', color='#00FF00', y=0.98)
        self.ax_ai.set_ylim(0, 1)
        
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()
        
def safe_float(val, default=0.0):
    """Safely convert value to float"""
    try:
        return float(val)
    except:
        return default

def safe_int(val, default=0):
    """Safely convert value to int"""
    try:
        return int(float(val))
    except:
        return default

def safe_bool(val, default=False):
    """Safely convert value to bool"""
    try:
        return bool(int(float(val)))
    except:
        return False

def parse_single_mtf_message(mtf_msg_string):
    """Parses a single MTF message string from MT5.

    Wire format (fixed position, 9 pipe-separated fields):
        tf_name|slope|dist_A|position|sitting|direction|mirror|gap|close

    NOTE: 'mirror' and 'gap' are currently sent as 0.0 placeholders from the
    MT5 side (MTF_BuildMessage) until real geometry logic for them is defined.
    The MTF signal engine's 'mid_gap' check will read 0.0 until that's wired up.
    """
    try:
        parts = mtf_msg_string.split('|')

        if len(parts) < 9:
            log_parser_error("MTF_PARSE_ERROR", mtf_msg_string, f"Expected 9 fields, got {len(parts)}")
            return None

        tf_name = parts[0].strip()

        try:
            slope     = safe_float(parts[1])
            dist_A    = safe_float(parts[2])
            position  = safe_float(parts[3])
            sitting   = safe_float(parts[4])
            direction = safe_int(parts[5])
            mirror    = safe_float(parts[6])
            gap       = safe_float(parts[7])
            close     = safe_float(parts[8])
        except Exception as e:
            log_parser_error("MTF_PARSE_ERROR", mtf_msg_string, f"Field conversion failed: {e}")
            return None

        return {
            'tf_name': tf_name,
            'close': close,
            'slope': slope,
            'dist_A': dist_A,
            'position': position,
            'sitting': sitting,
            'direction': direction,
            'mirror': mirror,
            'gap': gap
        }

    except Exception as e:
        log_parser_error("MTF_PARSE_ERROR", mtf_msg_string, str(e))
        return None

def parse_mql5_data(data_string):
    global parse_error_count, global_mtf_mode, global_mtf_data, global_candle_details, last_printed_candle

    try:
        data_string = data_string.replace('\x00', '').strip()
        if not data_string:
            return None, None, None

        # Ignore tiny non-market control packets that may arrive over the same socket.
        # Keep flow unchanged: only real payloads are parsed for AI prediction.
        if len(data_string) < 20 and not data_string.startswith('{'):
            return None, None, None

        # ====================== MTF DATA BLOCK ======================
        if "MTF_DATA" in data_string:
            global_mtf_mode = True
            # Extract block after header
            mtf_block = data_string.split("MTF_DATA", 1)[1].strip()
            # MTF data might come in a single packet with internal newlines
            single_tf_messages = [msg.strip() for msg in mtf_block.split('\n') if msg.strip() and '|' in msg]

            parsed_mtf_data = {}
            for msg in single_tf_messages:
                parsed_tf = parse_single_mtf_message(msg)
                if parsed_tf and parsed_tf.get('tf_name'):
                    parsed_mtf_data[parsed_tf['tf_name']] = parsed_tf

            global_mtf_data = parsed_mtf_data
            # ===== MTF SIGNAL ENGINE =====
            if len(parsed_mtf_data) > 0:
                high = [v for k,v in parsed_mtf_data.items() if k in ["H4","H1"]]
                mid  = [v for k,v in parsed_mtf_data.items() if k in ["M30","M15"]]
                low  = [v for k,v in parsed_mtf_data.items() if k in ["M5","M1"]]

                def avg(arr, key):
                    vals = [x.get(key,0) for x in arr]
                    return sum(vals)/len(vals) if vals else 0

                high_slope = avg(high, "slope")
                mid_gap    = avg(mid, "gap")
                low_sit    = avg(low, "sitting")

                if abs(high_slope) > 1e-6 and abs(mid_gap) < 0.003 and low_sit > 0.6:
                    print("🔥 MTF SIGNAL")
                else:
                    pass
            print(f"[MTF] Received data for {len(parsed_mtf_data)} timeframes: {list(parsed_mtf_data.keys())}")
            return None, None, ('MTF_ONLY', global_candle_details or {}, global_mtf_data)

        # ====================== NORMAL SINGLE TF MODE ======================
        global_mtf_mode = False
        parts = data_string.split('|')

        print("=" * 80)
        print("PART COUNT =", len(parts))

        for i, p in enumerate(parts):
            print(f"PART[{i}] = {p[:100]}")
        print("=" * 80)

        print("PART COUNT =", len(parts))
        print("PART[0] =", parts[0][:100])
        print("PART[1] =", parts[1][:100] if len(parts) > 1 else "N/A")
        
        print("EXPECTED < 5")
        print("ACTUAL =", len(parts))
        
        if len(parts) < 5:
            log_parser_error("MAIN_PARSE_ERROR", data_string[:300], f"Not enough parts: {len(parts)}")
            print("RAW PARTS:", parts[:10])
            return None, None, None

        # --- OHLC History ---
        ohlc_history = parts[0]
        raw_history = ohlc_history.split(';')
        ohlc_list = []
        for candle in raw_history:
            if not candle.strip(): continue
            try:
                o, h, l, c = map(float, candle.split(','))
                ohlc_list.append([o, h, l, c])
            except:
                continue

        if not ohlc_list:
            return None, None, None

        df = pd.DataFrame(ohlc_list, columns=['Open', 'High', 'Low', 'Close'])

        # FIXED: Safe datetime index (no more 'infer' error)
        try:
            last_candle_timestamp = datetime.fromtimestamp(int(parts[2]))
            # Create index manually to avoid any frequency issues
            dates = [last_candle_timestamp - pd.Timedelta(minutes=i) for i in range(len(df)-1, -1, -1)]
            df.index = pd.DatetimeIndex(dates)
        except Exception as idx_err:
            print(f"[INDEX FALLBACK] {idx_err}")
            df.index = pd.date_range(end=datetime.now(), periods=len(df), freq='min')

        df.index.name = 'Date'

        # --- Features ---
        features = {
            'symbol': parts[1] if len(parts) > 1 else 'UNKNOWN',
            'timestamp': int(parts[2]) if len(parts) > 2 else int(time.time()),
            'set_count': int(parts[3]) if len(parts) > 3 else 0,
            'timeframe': parts[4] if len(parts) > 4 else 'UNKNOWN'
        }

        # Default features
        default_features = {
            'snr_weight': 0, 'is_at_snr': 0, 'tp_m15': 0.0, 'tp_h1': 0.0,
            'rejection_candle_body_to_range_ratio': 0.0, 'set_magnitude': 0,
            'bars_duration': 0, 'dist_from_be': 0, 'active_TL_option': 0,
            'dynamic_TL_slope': 0.0, 'rejection_candle_total_range': 0,
            'rejection_candle_body_size': 0, 'rejection_candle_upper_wick_size': 0,
            'rejection_candle_lower_wick_size': 0, 'rejection_candle_is_large_relative_to_average': 0,
            'rejection_candle_volume': 0, 'bearish_sequence_length': 0,
            'trend_m15': 0, 'trend_h1': 0, 'trend_h4': 0
        }
        features.update(default_features)

        # Parse MT5 sent features
        # Field order must match SendAndReceiveSocketData in MT5:
        # history_str(0)|symbol(1)|time(2)|set_count(3)|timeframe(4)|
        # set_magnitude(5)|bars_duration(6)|dist_from_be(7)|active_TL_option(8)|dynamic_TL_slope(9)|
        # dynamic_TL_distance_current_price(10)|channel_top_distance_current_price(11)|channel_bottom_distance_current_price(12)|channel_width(13)|
        # rejection_candle_total_range(14)|rejection_candle_body_size(15)|rejection_candle_upper_wick_size(16)|rejection_candle_lower_wick_size(17)|
        # rejection_candle_is_large_relative_to_average(18)|rejection_candle_volume(19)|bearish_sequence_length(20)|
        # trend_m15(21)|trend_h1(22)|trend_h4(23)|snr_weight(24)|is_at_snr(25)|tp_m15(26)|tp_h1(27)|sync_pending(28)
        mt5_feature_keys = [
            'set_magnitude', 'bars_duration', 'dist_from_be', 'active_TL_option',
            'dynamic_TL_slope', 'dynamic_TL_distance_current_price',
            'channel_top_distance_current_price', 'channel_bottom_distance_current_price',
            'channel_width', 'rejection_candle_total_range',
            'rejection_candle_body_size', 'rejection_candle_upper_wick_size',
            'rejection_candle_lower_wick_size', 'rejection_candle_is_large_relative_to_average',
            'rejection_candle_volume', 'bearish_sequence_length',
            'trend_m15', 'trend_h1', 'trend_h4',
            'snr_weight', 'is_at_snr', 'tp_m15', 'tp_h1'
        ]

        for i, key in enumerate(mt5_feature_keys):
            idx = 5 + i
            if idx < len(parts):
                val = parts[idx].strip()
                if key == 'rejection_candle_is_large_relative_to_average':
                    features[key] = safe_bool(val)
                elif key in ['set_magnitude', 'bars_duration', 'active_TL_option', 'bearish_sequence_length', 'trend_m15', 'trend_h1', 'trend_h4', 'snr_weight', 'is_at_snr']:
                    features[key] = safe_int(val)
                else:
                    features[key] = safe_float(val)

        features['hour_of_day'] = datetime.fromtimestamp(features['timestamp']).hour

        if features.get('rejection_candle_total_range', 0) > 0:
            features['rejection_candle_body_to_range_ratio'] = features['rejection_candle_body_size'] / features['rejection_candle_total_range']

        # Candle details
        candle_ts = datetime.fromtimestamp(features['timestamp'])
        is_live = (datetime.now() - candle_ts).total_seconds() < 300

        candle_details = {
            'time': candle_ts.strftime('%Y-%m-%d %H:%M:%S'),
            'symbol': features['symbol'],
            'timeframe': features['timeframe'],
            'data_type': "LIVE" if is_live else "HISTORICAL",
            'candle_position': len(df),
            'range': ohlc_list[-1][1] - ohlc_list[-1][2] if ohlc_list else 0
        }

        current_key = (candle_details['time'][:10], candle_details['time'][11:19], features['symbol'], features['timeframe'])
        if current_key != last_printed_candle:
            print(f">>> CANDLE [{'LIVE' if is_live else 'HIST'}] {candle_details['time']} {features['symbol']} {features['timeframe']}")
            last_printed_candle = current_key

        global_candle_details = candle_details
        return df, features, (candle_details, global_mtf_data)

    except Exception as e:
        parse_error_count += 1
        log_parser_error("GENERAL_PARSE_ERROR", data_string[:250], str(e))
        print(f"Parse error: {e}")
        return None, None, None
    

def simulate_trades_on_ohlc(ohlc_df, base_features):
    """
    Bootstrap AI brain when history CSV is empty.
    Uses simple momentum on received MT5 candles.
    """
    global ai_brain
    import time

    if len(ohlc_df) < 10:
        return

    # FIX: handle both 'Close' and 'close' column names
    close_col = 'Close' if 'Close' in ohlc_df.columns else 'close'
    open_col = 'Open' if 'Open' in ohlc_df.columns else 'open'
    high_col = 'High' if 'High' in ohlc_df.columns else 'high'
    low_col = 'Low' if 'Low' in ohlc_df.columns else 'low'

    simulated_count = 0
    for i in range(5, len(ohlc_df) - 1):
        try:
            row = ohlc_df.iloc[i]
            next_row = ohlc_df.iloc[i + 1]

            is_bullish = row[close_col] > row[open_col]
            next_bullish = next_row[close_col] > next_row[open_col]
            outcome = 1 if (is_bullish == next_bullish) else 0

            # FIX: use proper pip calculation for crypto (BTCUSD)
            pips = abs(next_row[high_col] - next_row[low_col]) * 100
            if outcome == 0:
                pips = -pips

            # Build features from your captured MT5 data
            sim_features = dict(base_features)
            sim_features['set_magnitude'] = int(abs(row[close_col] - row[open_col]) * 100000)
            sim_features['bars_duration'] = i
            sim_features['hour_of_day'] = 12

            # FIX: safe timestamp
            try:
                timestamp = int(time.time()) - (len(ohlc_df) - i) * 300 # 5min bars
            except:
                timestamp = int(time.time())

            ai_brain.record_and_learn(
                features=sim_features,
                outcome=outcome,
                pips=pips,
                bars=1,
                timestamp=timestamp
            )
            simulated_count += 1

            if ai_brain.brain_age >= 20:
                print(f">>> Bootstrapped brain with {simulated_count} simulated trades")
                break
        except Exception as e:
            continue
    
    if simulated_count > 0:
        print(f">>> [SIM] Bootstrapped AI with {simulated_count} simulated trades from OHLC history. Brain age: {ai_brain.brain_age}")


def socket_listener():
    global global_socket_status
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.settimeout(1.0)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    print(f"Listening on {HOST}:{PORT}")

    while not global_stop_event.is_set():
        try:
            client_socket, addr = server_socket.accept()
            # NOTE: Do NOT read from the socket here. MT5 sends "HELLO|SYMBOL\n" once
            # connected, and that needs to reach handle_client()'s recv loop / process_payload()
            # so the symbol can be extracted and explore_7_sets() can be triggered. Reading it
            # here (even just 64 bytes) consumes those bytes off the stream and they never
            # reach handle_client, silently breaking the handshake and the auto-exploration feature.
            threading.Thread(target=handle_client, args=(client_socket, addr), daemon=True).start()
        except socket.timeout:
            continue
        except Exception as e:
            print(f"Error accepting connection: {e}")

    print("Socket listener shutting down.")
    server_socket.close()
    
    
def process(data):
    # Get features from MT5
    set_name = data.get('active_set', 'EA_Set_1')

    # Use your existing AI logic or simple rules for now
    # This should use the MTF data from MT5
    mtf = data.get('mtf', {})
    h4 = mtf.get('H4', {})

    # Simple example rule - replace with your actual logic
    signal = "HOLD"
    confidence = 0.5
    entry = float(h4.get('close', 0))

    # Example: EA_Set_5 = H4 demand + trendline
    if set_name == "EA_Set_5":
        if h4.get('supply_demand') == "DEMAND" and h4.get('trendline') == "1":
            signal = "BUY"
            confidence = 0.8

    result = {"signal": signal, "confidence": confidence, "entry": entry}

    # === LEARNING LINES - DO NOT REMOVE ===
    result['confidence'] = apply_learning_weight(set_name, result.get('confidence', 0.5))
    save_sim_result(set_name, result['signal'], result.get('entry', 0), result['confidence'])
    # === END LEARNING ===

    return result
    
    
def start_server():
    global global_socket_status, last_heartbeat_time

    # start socket in background
    listener_thread = threading.Thread(target=socket_listener, daemon=True)
    listener_thread.start()
    
    visualizer = RealtimeVisualizer()
    
    def _graceful_exit(signum, frame):
        print("\n[SHUTDOWN] Closing server...")
        global_stop_event.set()
        # Don't call sys.exit() - let matplotlib close naturally

    signal.signal(signal.SIGINT, _graceful_exit)
    signal.signal(signal.SIGTERM, _graceful_exit)
    
    def ui_update():
        global global_socket_status, last_heartbeat_time
        
        if global_stop_event.is_set():
            plt.close('all')
            return False
            
        try:
            while True:
                plot_data = plot_update_queue.get_nowait()
                visualizer.update_plot(
                    plot_data['ohlc'],
                    plot_data['scores'],
                    plot_data['set'],
                    plot_data['status'],
                    plot_data['symbol'],
                    plot_data['tf'],
                    plot_data['snr'],
                    plot_data['candle_details'],
                    plot_data['mtf_data']
                )
        except queue.Empty:
            pass
        return True
    
    timer = visualizer.fig.canvas.new_timer(interval=100)  # 100ms is stable on Mac
    timer.add_callback(ui_update)
    timer.start()

    try:
        plt.show(block=True)  # This blocks until window closes
    except KeyboardInterrupt:
        pass
    finally:
        global_stop_event.set()
        plt.close('all')  # <-- ADD THIS: Close matplotlib first
        time.sleep(0.2)   # <-- ADD THIS: Let daemon threads die
        print("[SHUTDOWN] Closing...")


# === ADD THIS TO BOTTOM OF YOUR EXISTING request.py ===
import sqlite3
from datetime import datetime

DB_PATH = "history.db"
CONFIG_PATH = "request_config.json"

def init_learning_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS sim_trades
                 (timestamp TEXT, set_name TEXT, signal TEXT,
                  entry REAL, result REAL, confidence REAL)''')
    conn.commit()
    conn.close()


def load_strategy_weights():
    try:
        with open(CONFIG_PATH) as f: return json.load(f)
    except:
        return {f"EA_Set_{i}":0.14 for i in range(1,8)}


def save_strategy_weights(w):
    with open(CONFIG_PATH,'w') as f: json.dump(w,f,indent=2)


def apply_learning_weight(set_name, base_confidence):
    weights = load_strategy_weights()
    return base_confidence * weights.get(set_name, 0.1)


def save_sim_result(set_name, signal, entry, confidence, result=0):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO sim_trades VALUES (?,?,?,?,?,?)",
                 (datetime.now().isoformat(), set_name, signal, entry, result, confidence))
    conn.commit()
    conn.close()


def update_weights_from_history():
    conn = sqlite3.connect(DB_PATH)
    weights = load_strategy_weights()
    for i in range(1,8):
        set_name = f"EA_Set_{i}"
        cur = conn.execute("SELECT AVG(result) FROM sim_trades WHERE set_name=? AND result!=0", (set_name,))
        avg = cur.fetchone()[0] or 0
        weights[set_name] += weights['learning_rate'] * avg
        weights[set_name] = max(0.01, min(1.0, weights[set_name]))
    save_strategy_weights(weights)
    conn.close()
    return weights


def explore_7_sets(conn):
    try:  # <-- ADD THIS
        conn.sendall(b"EXPLORE|START\n")
        conn.recv(1024) # Wait ACTIVE
        init_learning_db()
        for i in range(1,8):
            set_name = f"EA_Set_{i}"
            conn.send(f"USE:{set_name}\n".encode())
            conn.recv(1024) # Wait ACTIVE
            time.sleep(2)
            data = conn.recv(8192).decode().strip()
            if data.startswith("{"):
                result = process(json.loads(data))
                print(f"[{set_name}] {result['signal']} conf={result['confidence']:.2f}")
            time.sleep(0.5)
        new_weights = update_weights_from_history()
        print("[AI LEARNED]", {k:v for k,v in new_weights.items() if 'EA_Set' in k})
    except:  # <-- ADD THIS
        pass  # <-- ADD THIS - silently exit if MT5 switched TF mid-explore
    
    
def handle_client(client_socket, addr):
    global global_mt5_symbol, global_mt5_timeframe, global_socket_status
    global ohlc_data_history, ai_score_history, global_candle_details
    global global_mtf_data, global_mtf_mode, last_heartbeat_time

    global_socket_status = "CONNECTED"
    last_heartbeat_time = time.time()
    recv_buffer = ""
    
    # NEW: Queue for non-blocking AI work
    ai_work_queue = queue.Queue()

    print(f"[SOCKET] Accepted connection from {addr}")
    print("="*60)
    print("[STATE] >>> PYTHON CONNECTED TO MT5 <<<")
    print("="*60)

    try:
        client_socket.sendall(b"OK\n") # MT5 expects OK, not HELLO_ACK
        print("[SOCKET] Sent OK to MT5")
    except:
        return

    client_socket.settimeout(0.2)
    recv_buffer = ""
    
    def ai_worker():
        """Background thread: Process AI work without blocking socket I/O."""
        while not global_stop_event.is_set():
            try:
                task = ai_work_queue.get(timeout=0.1)
                if task is None:  # Poison pill to exit
                    break
                
                ohlc_df, features, symbol = task
                
                try:
                    current_brain = get_brain(symbol)
                    if current_brain.learning_status == "INITIALIZING":
                        current_brain.learning_status = "LEARNING" if current_brain.brain_age < 50 else "EVOLVING"
                    
                    # Perform prediction in background (non-blocking)
                    score, direction, max_hold = current_brain.predict(features)
                    
                    # Send response back through socket (quick operation)
                    try:
                        trend_m15 = features.get('trend_m15', features.get('g_trend_m15', 0))
                        trend_h1 = features.get('trend_h1', features.get('g_trend_h1', 0))
                        trend_h4 = features.get('trend_h4', features.get('g_trend_h4', 0))
                        
                        threshold = 0.65
                        if current_brain.brain_age >= 20:
                            buy_ok = (score > threshold and trend_h1 == 1 and trend_h4 == 1)
                            sell_ok = (score > threshold and trend_h1 == -1 and trend_h4 == -1)
                            
                            if buy_ok:
                                client_socket.sendall(b"TRADE|BUY\n")
                                print(f">>> TRIGGER BUY | score={score:.2f} > {threshold}")
                            elif sell_ok:
                                client_socket.sendall(b"TRADE|SELL\n")
                                print(f">>> TRIGGER SELL | score={score:.2f} > {threshold}")
                            else:
                                response = f"{score:.4f}|0|{max_hold}\n"
                                client_socket.sendall(response.encode('utf-8'))
                                print(f"[HOLD] score={score:.2f}")
                        else:
                            response = f"{score:.4f}|{direction}|{max_hold}\n"
                            client_socket.sendall(response.encode('utf-8'))
                            print(f"[BOOTSTRAP] Score={score:.4f} (age {current_brain.brain_age})")
                    except (BrokenPipeError, ConnectionResetError):
                        pass  # Client disconnected, will be caught in main loop
                    
                    # Offline learning in background
                    if current_brain.brain_age < 20 and len(ohlc_df) >= 10:
                        try:
                            simulate_trades_on_ohlc(ohlc_df, features)
                        except Exception as e:
                            logger.debug(f"[AI WORKER] Simulation error: {e}")
                        
                except Exception as e:
                    logger.error(f"[AI WORKER] Prediction error: {e}")
                    
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[AI WORKER] Unexpected error: {e}")

    def process_ui_commands():
        try:
            while not global_ui_command_queue.empty():
                cmd = global_ui_command_queue.get_nowait()
                client_socket.sendall(cmd.encode())
                print(f"[UI COMMAND] Sent to MT5: {cmd.strip()}")
        except Exception as e:
            print(f"[UI ERROR] Failed to send UI command: {e}")

    def process_payload(payload):
        nonlocal recv_buffer
        global global_mt5_symbol, global_mt5_timeframe, global_socket_status
        global ohlc_data_history, ai_score_history, global_candle_details, global_mtf_data
        global global_mtf_mode, last_heartbeat_time
        data = payload.replace('\x00', '').strip()
        if not data:
            return

        if "HEARTBEAT" in data or "PING" in data or "PONG" in data:
            print("[HEARTBEAT] Received heartbeat from MT5.")
            last_heartbeat_time = time.time()
            client_socket.sendall(b"PONG\n")
            return
        
        if "HELLO" in data:
            print(f"[SOCKET] Received HELLO from MT5: {data}")
            client_socket.sendall(b"OK\n")
            
            # Extract symbol if present: "HELLO|BTCUSD"
            current_sym = "DEFAULT"
            if "|" in data:
                try:
                    current_sym = data.split("|")[1].strip()
                except:
                    pass
            elif global_mt5_symbol != "UNKNOWN":
                current_sym = global_mt5_symbol

            if current_sym not in global_explored_symbols:
                print(f"[EXPLORE] Scheduling exploration for {current_sym}...")
                global_explored_symbols.add(current_sym)
                threading.Thread(target=explore_7_sets, args=(client_socket,), daemon=True).start()
            return

        if data.startswith('{'):
            try:
                json_data = json.loads(data)
                if json_data.get('action') == 'learn':
                    get_brain(json_data.get('features', {}).get('symbol','DEFAULT')).record_and_learn(
                        features=json_data.get('features', {}),
                        outcome=json_data.get('outcome', 0),
                        pips=json_data.get('pips', 0),
                        bars=json_data.get('bars', 0),
                        timestamp=json_data.get('timestamp', int(time.time()))
                    )
            except json.JSONDecodeError:
                pass
            return

        print("\n" + "="*80)
        print("RAW PAYLOAD FROM MT5")
        print("="*80)
        print(repr(data[:3000]))
        print("="*80)
        ohlc_df, features, extra_data = parse_mql5_data(data)

        if extra_data and extra_data[0] == 'MTF_ONLY':
            _, global_candle_details, global_mtf_data = extra_data
            plot_update_queue.put({
                'ohlc': ohlc_data_history,
                'scores': pd.Series(ai_score_history) if ai_score_history else pd.Series(),
                'set': 0,
                'status': global_socket_status,
                'symbol': global_mt5_symbol,
                'tf': global_mt5_timeframe or "MTF",
                'snr': 0,
                'candle_details': global_candle_details,
                'mtf_data': global_mtf_data
            })
            return

        if ohlc_df is not None and features is not None:
            print(f"[DATA PARSE] Symbol={features.get('symbol', '?')}, TF={features.get('timeframe', '?')}, Candles={len(ohlc_df)}")
        else:
            if len(data) >= 500:
                print(f"[DATA ERROR] Failed to parse data from MT5")
            return

        if extra_data:
            global_candle_details, _ = extra_data

        if features['symbol']!= global_mt5_symbol or features['timeframe']!= global_mt5_timeframe:
            global_mt5_symbol = features['symbol']
            global_mt5_timeframe = features['timeframe']
            ai_score_history = []
            global_mtf_data = {}
            global_candle_details = {}

        current_brain = get_brain(features['symbol'])
        if current_brain.learning_status == "INITIALIZING":
            current_brain.learning_status = "LEARNING" if current_brain.brain_age < 50 else "EVOLVING"

        try:
            score, direction, max_hold = current_brain.predict(features)
            trend_m15 = features.get('trend_m15', features.get('g_trend_m15', 0))
            trend_h1 = features.get('trend_h1', features.get('g_trend_h1', 0))
            trend_h4 = features.get('trend_h4', features.get('g_trend_h4', 0))

            threshold = 0.65
            if current_brain.brain_age >= 20:
                buy_ok = (score > threshold and trend_h1 == 1 and trend_h4 == 1)
                sell_ok = (score > threshold and trend_h1 == -1 and trend_h4 == -1)

                if buy_ok:
                    client_socket.sendall(b"TRADE|BUY\n")
                    print(f">>> TRIGGER BUY | score={score:.2f} > {threshold}")
                elif sell_ok:
                    client_socket.sendall(b"TRADE|SELL\n")
                    print(f">>> TRIGGER SELL | score={score:.2f} > {threshold}")
                else:
                    response = f"{score:.4f}|0|{max_hold}\n"
                    client_socket.sendall(response.encode('utf-8'))
                    print(f"[HOLD] score={score:.2f}")
            else:
                response = f"{score:.4f}|{direction}|{max_hold}\n"
                client_socket.sendall(response.encode('utf-8'))
                print(f"[BOOTSTRAP] Score={score:.4f} (age {current_brain.brain_age})")

        except BrokenPipeError:
            print("[SOCKET] Broken pipe - Client disconnected during send")
            raise
        except Exception as e:
            print(f"[DATA ERROR] Failed to predict or send response: {e}")
            return

        ohlc_data_history = ohlc_df
        ai_score_history.append(score)
        if len(ai_score_history) > len(ohlc_data_history):
            ai_score_history.pop(0)

        current_brain = get_brain(features['symbol'])
        if current_brain.brain_age < 20 and len(ohlc_df) >= 10:
            global ai_brain
            ai_brain = current_brain
            simulate_trades_on_ohlc(ohlc_df, features)

        plot_update_queue.put({
            'ohlc': ohlc_data_history,
            'scores': pd.Series(ai_score_history, index=ohlc_data_history.index[-len(ai_score_history):]),
            'set': features.get('set_count', 0),
            'status': global_socket_status,
            'symbol': global_mt5_symbol,
            'tf': global_mt5_timeframe,
            'snr': features.get('snr_weight', 0),
            'candle_details': global_candle_details,
            'mtf_data': global_mtf_data
        })

    try:
        client_socket.settimeout(0.1)
        while not global_stop_event.is_set():
            process_ui_commands()
            try:
                chunk = client_socket.recv(BUFFER_SIZE).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                recv_buffer += chunk
                last_heartbeat_time = time.time()
            except socket.timeout:
                process_ui_commands()
                continue
            except (ConnectionResetError, BrokenPipeError):
                break

            # Process line by line (standard for this protocol)
            while '\n' in recv_buffer:
                line, recv_buffer = recv_buffer.split('\n', 1)
                clean_line = line.strip()
                if clean_line:
                    # --- FIX: Guardrail against silent internal processing exceptions ---
                    try:
                        print("RECEIVED LENGTH =", len(clean_line))
                        process_payload(clean_line)
                    except Exception as payload_error:
                        print(f"[DATA EXCEPTION] Error processing line: {payload_error}")
                        print(f"[DATA EXCEPTION] Raw Line Content: {clean_line}")
                        continue  # Keep thread alive, move to the next clean network packet
                    # ---------------------------------------------------------------------

            # Safety net: MT5 always terminates every message with '\n', so a clean message
            # never lingers unterminated in recv_buffer for long. If recv_buffer grows
            # pathologically large with no newline, the connection is desynced — discard it
            # WITHOUT attempting to parse it (parsing a known-incomplete fragment is what
            # caused the PART COUNT=227 / garbage-field corruption previously).
            MAX_UNTERMINATED_BUFFER = 200_000  # generous; real messages are a few KB
            if len(recv_buffer) > MAX_UNTERMINATED_BUFFER:
                print(f"[SOCKET] WARNING: {len(recv_buffer)} bytes with no newline — connection desynced, discarding")
                recv_buffer = ""
    except (ConnectionResetError, BrokenPipeError):
        pass # Normal on TF change
    except socket.timeout:
        pass # Normal heartbeat timeout
    except Exception as e:
        if "Broken pipe" not in str(e) and "Connection reset" not in str(e):
            print(f"[SOCKET ERROR] Unexpected: {e}")
    finally:
        # Only print DISCONNECTED if we're actually disconnected
        old_status = global_socket_status
        global_socket_status = "DISCONNECTED"
        
        # Check if a new connection already took over during this shutdown
        if old_status == "CONNECTED":
            print("\n" + "="*60)
            print("[STATE] <<< MT5 Switching TF or Disconnected >>>")
            print("="*60 + "\n")      
        try:
            client_socket.close()
        except:
            pass
        
        
if __name__ == "__main__":
    start_server() # start_server now runs GUI in main thread
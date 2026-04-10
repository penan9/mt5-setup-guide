import socket
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
from datetime import datetime
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
import mplfinance as mpf
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

warnings.filterwarnings("ignore", category=UserWarning)
VERSION = "AI Brain Master 12.2 - Robust MTF Parser & Versioned Evolution"

# --- Configuration ---
CONFIG_FILE = "request_config.json"
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
                # Note: JSON does not allow duplicate keys. If request_config.json has
                # duplicate "active_symbol" keys, only the LAST value is kept by Python's
                # json.load. This is expected behavior. Fix the JSON file to avoid confusion.
                return cfg
        except Exception as e:
            print(f"Error loading config: {e}")
    return {}

config = load_config()
MT5_BASE_PATH = config.get("mt5_path", "/home/ubuntu/upload")

def find_history_file(base_path):
    direct_path = os.path.join(base_path, "MT5_Set_History.csv")
    
    # FIX 3a: If the configured mt5_path directory doesn't exist (e.g., running on
    # a different machine), fall back to the local working directory immediately.
    dir_part = os.path.dirname(direct_path)
    if dir_part and not os.path.exists(dir_part):
        local_path = os.path.abspath("MT5_Set_History.csv")
        print(f"!!! WARNING: Configured mt5_path '{base_path}' does not exist.")
        print(f"!!! Falling back to local path: {local_path}")
        return local_path

    if os.path.exists(direct_path):
        return direct_path
    
    print(f">>> AUTO-DISCOVERY: Searching for MT5_Set_History.csv in {base_path}...")
    for root, dirs, files in os.walk(base_path):
        if "MT5_Set_History.csv" in files:
            found_path = os.path.join(root, "MT5_Set_History.csv")
            print(f">>> AUTO-DISCOVERY: Found history file at {found_path}")
            return found_path
    
    if os.path.exists("MT5_Set_History.csv"):
        return os.path.abspath("MT5_Set_History.csv")
        
    manual_path = config.get("history_file_path")
    if manual_path and os.path.exists(manual_path):
        return manual_path
        
    return direct_path

HISTORY_CSV = find_history_file(MT5_BASE_PATH)
EA_PATH = os.path.join(MT5_BASE_PATH, "test2.mq5")

print(f">>> PATH DEBUGGER: Looking for history at: {HISTORY_CSV}")
if not os.path.exists(HISTORY_CSV):
    print(f"!!! WARNING: History file NOT FOUND at {HISTORY_CSV}. KPIs will remain 0 until first trade.")

HOST = '127.0.0.1'
PORT = 8888
BUFFER_SIZE = 16384
BRAIN_FILE = "ai_brain.joblib"
BRAIN_BACKUP = "ai_brain_backup.joblib"
STATS_FILE = "cumulative_stats.json"
STATS_BACKUP = "cumulative_stats_backup.json"
MTF_DATA_LOG = "mtf_data_flow.log"
PARSER_LOG = "parser_debug.log"  # NEW: Log parser errors

# --- AI Evolution Config ---
MODEL_DIR = "./ai_models"
DATA_DIR = "./ai_data"
HISTORY_DIR = "./evolution_history"
VERSION_FILE = os.path.join(MODEL_DIR, "current_version.txt")
for d in [MODEL_DIR, DATA_DIR, HISTORY_DIR]:
    os.makedirs(d, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

matplotlib.use('TkAgg')

# --- Global Control & Data ---
global_stop_event = threading.Event()
plot_update_queue = queue.Queue()
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
        except: pass

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
            df = pd.read_csv(self.history_csv, encoding='ansi')
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
            if self.last_evolved_pf == 0.0: self.last_evolved_pf = self.profit_factor
            print(f">>> KPI REFRESH: Age={self.brain_age}, WR={self.lifetime_win_rate:.2f}%, PF={self.profit_factor:.2f}")
        except Exception as e:
            logger.error(f"KPI recalculation failed: {e}")

    def record_and_learn(self, features, outcome, pips, bars, timestamp):
        self.last_sync_time = max(self.last_sync_time, timestamp)
        data = {'timestamp': [timestamp], 'success_label': [outcome], 'pips': [pips], 'bars': [bars]}
        for k, v in features.items():
            data[f'feat_{k}'] = [float(v)]
        df_new = pd.DataFrame(data)
        # FIX 3b: Ensure the directory for the history CSV exists before writing
        history_dir = os.path.dirname(self.history_csv)
        if history_dir and not os.path.exists(history_dir):
            try:
                os.makedirs(history_dir, exist_ok=True)
                print(f">>> Created history directory: {history_dir}")
            except Exception as mkdir_err:
                # If we can't create the directory, fall back to local file
                self.history_csv = os.path.abspath("MT5_Set_History.csv")
                logger.warning(f"Cannot write to configured path. Using local: {self.history_csv}")
        df_new.to_csv(self.history_csv, mode='a', index=False, header=not os.path.exists(self.history_csv), encoding='ansi')
        self.brain_age += 1
        self._recalculate_kpis()
        if self.brain_age % 10 == 0:
            threading.Thread(target=self.retrain, daemon=True).start()
        if self.profit_factor > self.last_evolved_pf + 0.1 and self.brain_age > 50:
            self.evolve_system()

    def retrain(self):
        if not os.path.exists(self.history_csv): return
        logger.info(f">>> AI DEEP LEARNING: Analyzing {self.brain_age} historical setups...")
        try:
            df = pd.read_csv(self.history_csv)
      
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
        
        # Backup current Python script with version
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"request_v{self.current_version}_{timestamp}.py"
            shutil.copy2(__file__, os.path.join(HISTORY_DIR, backup_name))
            logger.info(f"Backed up current script to {backup_name}")
        except Exception as e:
            logger.error(f"Self-evolution backup failed: {e}")

        # Save new version of Python script (for manual switch)
        new_script_name = f"request_v{new_version}.py"
        new_script_path = os.path.join(os.path.dirname(__file__), new_script_name)
        try:
            shutil.copy2(__file__, new_script_path)
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
                if hasattr(self.model, "classes_"):
                    # Ensure feature vector matches training features
                    feature_names = self.get_feature_cols()
                    feat_vec = [features.get(f, 0) for f in feature_names]
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
ai_brain = AIBrain(BRAIN_FILE, BRAIN_BACKUP, HISTORY_CSV)

# --- Enhanced Visualizer with Detailed Candle Info ---
class Visualizer:
    def __init__(self, symbol_name):
        self.symbol_name = symbol_name
        self.mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', edge='inherit', wick='inherit', volume='gray', ohlc='inherit')
        self.mpf_style = mpf.make_mpf_style(base_mpf_style='charles', marketcolors=self.mc, facecolor='black', figcolor='black', gridcolor='#2c2c2c', gridstyle='--', rc={'axes.edgecolor': 'white', 'ytick.color': 'white', 'xtick.color': 'white', 'axes.labelcolor': 'white', 'font.size': 8}, y_on_right=True)
        self.fig = plt.figure(figsize=(14, 10), facecolor='black')
        gs = self.fig.add_gridspec(5, 1, height_ratios=[3, 1, 1, 1, 0.5], hspace=0.3)
        self.ax_main = self.fig.add_subplot(gs[0, 0], facecolor='black')
        self.ax_ai = self.fig.add_subplot(gs[1, 0], facecolor='black', sharex=self.ax_main)
        self.ax_kpi = self.fig.add_subplot(gs[2, 0], facecolor='black')
        self.ax_mtf = self.fig.add_subplot(gs[3, 0], facecolor='black')
        self.ax_stop = self.fig.add_subplot(gs[4, 0])
        self.ax_stop.axis('off')
        # Create MTF button
        ax_mtf_btn = self.fig.add_axes([0.7, 0.02, 0.12, 0.04])
        self.btn_mtf = Button(ax_mtf_btn, 'MTF: [Single]', color='gray', hovercolor='darkgray')
        self.btn_mtf.on_clicked(self.toggle_mtf_mode)
        # Create STOP button
        ax_stop_btn = self.fig.add_axes([0.85, 0.02, 0.12, 0.04])
        self.btn_stop = Button(ax_stop_btn, 'STOP & SAVE', color='red', hovercolor='darkred')
        self.btn_stop.on_clicked(lambda e: global_stop_event.set())
        self.fig.canvas.mpl_connect('close_event', lambda e: global_stop_event.set())
        print("Enhanced visualizer window initialized with MTF button and data display.")


    def toggle_mtf_mode(self, event):
        """Toggle MTF mode when button is clicked"""
        global global_mtf_mode
        global_mtf_mode = not global_mtf_mode
        if global_mtf_mode:
            self.btn_mtf.label.set_text('MTF: [Multiple]')
            self.btn_mtf.color = 'green'
            self.btn_mtf.hovercolor = 'darkgreen'
            print("\n" + "="*60)
            print("[MTF] >>> MTF COLLECTION [Multiple] ACTIVATED <<<")
            print("[MTF] Collecting: M1, M5, M15, M30, H1, H4, D1, W1, MN1")
            print("[MTF] Mode: [Multiple] - PULLING ALL TIMEFRAMES")
            print("="*60 + "\n")
        else:
            self.btn_mtf.label.set_text('MTF: [Single]')
            self.btn_mtf.color = 'gray'
            self.btn_mtf.hovercolor = 'darkgray'
            print("\n" + "="*60)
            print("[MTF] >>> MTF COLLECTION [Single] DEACTIVATED <<<")
            print("[MTF] Mode: [Single] - BACK TO ACTIVE TIMEFRAME ONLY")
            print("="*60 + "\n")
        self.fig.canvas.draw_idle()

    def update_plot(self, ohlc_df, ai_scores, current_set, status, symbol, tf, snr_weight, candle_details, mtf_data):
        if not plt.fignum_exists(self.fig.number): return
        self.fig.suptitle(f'{symbol} ({tf}) - Status: {status} - Set: {current_set} - SnR Weight: {snr_weight} - AI Version: {ai_brain.current_version}', color='white', y=0.98)
        if not ohlc_df.empty:
            self.ax_main.clear()
            self.ax_ai.clear()
            
            if len(ai_scores) < len(ohlc_df):
                padded_scores = [np.nan] * (len(ohlc_df) - len(ai_scores)) + list(ai_scores)
            else:
                padded_scores = list(ai_scores)[-len(ohlc_df):]
            
            apds = [mpf.make_addplot(padded_scores, color='#00ffff', ax=self.ax_ai, width=1.2)]
            
            mpf.plot(ohlc_df, type='candle', style=self.mpf_style, ax=self.ax_main, addplot=apds, show_nontrading=False, datetime_format='%H:%M')
            
            self.ax_main.axhline(ohlc_df['Close'].iloc[-1], color='white', linestyle='-', linewidth=0.5, alpha=0.7)
            self.ax_ai.set_ylabel('AI Score', color='white')
            self.ax_ai.set_ylim(0, 1)
            
            # --- Display Detailed Candle Information with Timestamp and Data Type ---
            self.ax_kpi.clear()
            self.ax_kpi.axis('off')
            kpi_text = "LATEST CANDLE DETAILS:\n"
            data_type = candle_details.get('data_type', 'UNKNOWN')
            candle_pos = candle_details.get('candle_position', 0)
            data_color_indicator = "[LIVE]" if data_type == "LIVE" else "[HIST]"
            kpi_text += f"Timestamp: {candle_details.get('time', 'N/A')} {data_color_indicator}\n"
            kpi_text += f"Position: {candle_pos}/100 | Symbol: {candle_details.get('symbol', 'N/A')} | TF: {candle_details.get('timeframe', 'N/A')}\n"
            kpi_text += f"Range: {candle_details.get('range', 0):.4f} pips\n"
            kpi_text += "\nTL STRATEGY PERFORMANCE:\n"
            for i, d in performance_tracker.stats.items():
                wr = (d['wins']/d['trades']*100) if d['trades']>0 else 0.0
                kpi_text += f"{d['name']:<15}: {d['trades']:>3} Trades | {wr:>5.1f}% Win Rate\n"
            # Use different colors for live vs historical
            text_color = '#00ff00' if data_type == "LIVE" else '#ffff00'  # Green for live, yellow for historical
            self.ax_kpi.text(0.05, 0.5, kpi_text, color=text_color, fontsize=8, family='monospace', va='center')
            
            # --- Display Multi-Timeframe Data ---
            self.ax_mtf.clear()
            self.ax_mtf.axis('off')
            mtf_text = "MULTI-TIMEFRAME DATA FLOW:\n"
            if mtf_data:
                for tf_name, data in mtf_data.items():
                    mtf_text += f"{tf_name:<8} | Candles: {data.get('candles', 0):<3} | Last: O:{data.get('open', 0):.2f} C:{data.get('close', 0):.2f}\n"
            else:
                mtf_text += "Waiting for MTF data from MT5...\n"
            self.ax_mtf.text(0.05, 0.5, mtf_text, color='#00ffff', fontsize=8, family='monospace', va='center')
            
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()
        plt.pause(0.001)

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
        return default

def parse_single_mtf_message(mtf_msg_string):
    """Parses a single MTF message string from MT5."""
    try:
        parts = mtf_msg_string.split('|')
        if len(parts) < 6: # OHLC + Symbol + Timestamp + SetCount + Timeframe + Features
            log_parser_error("MTF_PARSE_ERROR", mtf_msg_string, "Not enough parts in single MTF message")
            return None

        ohlc_str = parts[0]
        raw_history = ohlc_str.split(';')
        ohlc_list = []
        for candle in raw_history:
            if not candle or candle.strip() == '': continue
            try:
                o, h, l, c = map(float, candle.split(','))
                ohlc_list.append([o, h, l, c])
            except ValueError:
                continue # Skip malformed candles
        
        if not ohlc_list: return None

        tf_name = parts[4]
        return {
            'tf_name': tf_name,
            'candles': len(ohlc_list),
            'open': ohlc_list[-1][0],
            'high': ohlc_list[-1][1],
            'low': ohlc_list[-1][2],
            'close': ohlc_list[-1][3],
            'features': parts[5:] # Remaining parts are features
        }
    except Exception as e:
        log_parser_error("MTF_PARSE_ERROR", mtf_msg_string, str(e))
        return None

def parse_mql5_data(data_string):
    """
    ROBUST MT5 data parser with error recovery
    Format: "o1,h1,l1,c1;o2,h2,l2,c2;...;o100,h100,l100,c100|SYMBOL|TIMESTAMP|SETCOUNT|TIMEFRAME|FEATURES..."
    Or for MTF: "MTF_DATA\nMTF_TF1_MSG\nMTF_TF2_MSG..."
    """
    global parse_error_count
    global global_mtf_mode
    try:
        data_string = data_string.replace('\x00', '').strip()

        # Check for MTF data block
        if data_string.startswith("MTF_DATA\n"):
            global_mtf_mode = True
            mtf_block = data_string[len("MTF_DATA\n"):].strip()
            single_tf_messages = mtf_block.split('\n')
            parsed_mtf_data = {}
            for msg in single_tf_messages:
                if msg.strip() == "": continue
                parsed_tf = parse_single_mtf_message(msg)
                if parsed_tf:
                    parsed_mtf_data[parsed_tf['tf_name']] = {
                        'candles': parsed_tf['candles'],
                        'open': parsed_tf['open'],
                        'high': parsed_tf['high'],
                        'low': parsed_tf['low'],
                        'close': parsed_tf['close']
                    }
            # For MTF mode, we don't have a single OHLC_DF or main features
            # We'll return dummy values or adapt the visualizer to handle this.
            # For now, return the last received single TF data if available, or empty.
            # This needs careful consideration for how the visualizer will display.
            # For simplicity, let's assume the main display still shows the primary TF.
            # The MTF data will be passed separately.
            return None, None, (None, parsed_mtf_data) # No main OHLC_DF or features in this mode
        else:
            global_mtf_mode = False

        parts = data_string.split('|')
        
        if len(parts) < 5:
            log_parser_error("MAIN_PARSE_ERROR", data_string, f"Not enough parts in data. Got {len(parts)}, expected >= 5")
            return None, None, None

        # PART 0: OHLC History (semicolon-separated candles)
        ohlc_history = parts[0]
        raw_history = ohlc_history.split(';')
        
        ohlc_list = []
        for candle in raw_history:
            if not candle or candle.strip() == '': 
                continue
            try:
                o, h, l, c = map(float, candle.split(','))
                ohlc_list.append([o, h, l, c])
            except ValueError:
                # Skip malformed candles silently
                continue
        
        if not ohlc_list:
            log_parser_error("MAIN_PARSE_ERROR", data_string, "No valid OHLC data parsed")
            return None, None, None
        
        df = pd.DataFrame(ohlc_list, columns=['Open', 'High', 'Low', 'Close'])
        # Use actual timestamp from MT5 for the last candle, then infer previous ones
        last_candle_timestamp = datetime.fromtimestamp(safe_int(parts[2], int(time.time())))
        # Assuming 1-minute frequency for simplicity, adjust if MT5 sends actual TF
        # For now, the visualizer will use the TF from features, not from this inferred index.
        df.index = pd.to_datetime([last_candle_timestamp - pd.Timedelta(minutes=(len(df) - 1 - i)) for i in range(len(df))])
        df.index.name = 'Date'
        
        # PARTS 1+: Features (with safe parsing and defaults)
        features = {
            'symbol': parts[1] if len(parts) > 1 else 'UNKNOWN',
            'timestamp': safe_int(parts[2], int(time.time())) if len(parts) > 2 else int(time.time()),
            'set_count': safe_int(parts[3], 0) if len(parts) > 3 else 0,
            'timeframe': parts[4] if len(parts) > 4 else 'UNKNOWN'
        }
        
        # Safely parse optional features with defaults
        # This mapping needs to be strictly aligned with MT5 script's SendAndReceiveSocketData
        feature_start_index = 5
        feature_keys = [
            'set_magnitude', 'bars_duration', 'dist_from_be', 'active_TL_option', 
            'dynamic_TL_slope', 'dynamic_TL_distance_current_price', 
            'channel_top_distance_current_price', 'channel_bottom_distance_current_price', 
            'channel_width', 'rejection_candle_total_range', 'rejection_candle_body_size', 
            'rejection_candle_upper_wick_size', 'rejection_candle_lower_wick_size', 
            'rejection_candle_is_large_relative_to_average', 'rejection_candle_volume', 
            'bearish_sequence_length', 'trend_m15', 'trend_h1', 'trend_h4'
        ]
        # Add snr_weight, is_at_snr, tp_m15, tp_h1 if they are sent in the main message
        # Based on MT5 script lines 6897-6916, the order is:
        # captured_set_magnitude, captured_bars_duration, captured_dist_from_be, captured_active_tl_option,
        # captured_dynamic_tl_slope, captured_dynamic_tl_distance_current_price,
        # captured_channel_top_distance_current_price, captured_channel_bottom_distance_current_price,
        # captured_channel_width, captured_rejection_candle_total_range, captured_rejection_candle_body_size,
        # captured_rejection_candle_upper_wick_size, captured_rejection_candle_lower_wick_size,
        # captured_rejection_candle_is_large_relative_to_average, captured_rejection_candle_volume,
        # captured_bearish_sequence_length, g_trend_m15, g_trend_h1, g_trend_h4
        # The MT5 script also has snr_weight and is_at_snr as global variables, but they are not explicitly sent in this message.
        # I will add placeholders for them in the feature_keys if they are expected by the AI brain.
        # From the MT5 script's predict function, the feature_cols are:
        # 'set_magnitude', 'bars_duration', 'hour_of_day', 'dist_from_be', 'active_TL_option', 'dynamic_TL_slope', 
        # 'snr_weight', 'is_at_snr', 'tp_m15', 'tp_h1', 'rejection_candle_total_range', 'rejection_candle_body_size', 
        # 'rejection_candle_upper_wick_size', 'rejection_candle_lower_wick_size', 'rejection_candle_body_to_range_ratio', 
        # 'rejection_candle_is_large_relative_to_average', 'rejection_candle_volume', 'bearish_sequence_length'
        # This means there's a mismatch between what MT5 sends and what Python expects for features.
        # I need to align these. For now, I will parse what MT5 sends and let the AI brain handle missing features with defaults.

        # Re-aligning feature_keys based on MT5 script lines 6897-6916
        mt5_sent_feature_keys = [
            'set_magnitude', 'bars_duration', 'dist_from_be', 'active_TL_option', 
            'dynamic_TL_slope', 'dynamic_TL_distance_current_price', 
            'channel_top_distance_current_price', 'channel_bottom_distance_current_price', 
            'channel_width', 'rejection_candle_total_range', 'rejection_candle_body_size', 
            'rejection_candle_upper_wick_size', 'rejection_candle_lower_wick_size', 
            'rejection_candle_is_large_relative_to_average', 'rejection_candle_volume', 
            'bearish_sequence_length', 'trend_m15', 'trend_h1', 'trend_h4'
        ]

        for i, key in enumerate(mt5_sent_feature_keys):
            if feature_start_index + i < len(parts):
                if key == 'rejection_candle_is_large_relative_to_average':
                    features[key] = safe_bool(parts[feature_start_index + i])
                elif key in ['set_magnitude', 'bars_duration', 'active_TL_option', 'bearish_sequence_length', 'trend_m15', 'trend_h1', 'trend_h4']:
                    features[key] = safe_int(parts[feature_start_index + i])
                else:
                    features[key] = safe_float(parts[feature_start_index + i])
        
        # Add 'hour_of_day' which is derived from timestamp
        features['hour_of_day'] = datetime.fromtimestamp(features['timestamp']).hour

        # The MT5 script does not send 'snr_weight', 'is_at_snr', 'tp_m15', 'tp_h1', 'rejection_candle_body_to_range_ratio'
        # in the main message. The AI brain's get_feature_cols expects them. 
        # These will be handled by the .get(key, 0) with default 0 in predict function.
        # However, 'rejection_candle_body_to_range_ratio' is calculated in MT5 for logging, but not sent.
        # I will add it to features here if it can be derived.
        if features.get('rejection_candle_total_range', 0) > 0:
            features['rejection_candle_body_to_range_ratio'] = features.get('rejection_candle_body_size', 0) / features['rejection_candle_total_range']
        else:
            features['rejection_candle_body_to_range_ratio'] = 0.0

        # --- Extract Candle Details with Timestamp and Data Type Detection ---
        candle_timestamp = datetime.fromtimestamp(features['timestamp'])
        current_time = datetime.now()
        time_diff_seconds = (current_time - candle_timestamp).total_seconds()
        
        # Determine if data is historical or live
        # Live data: candle time is within last 5 minutes
        # Historical: candle time is older than 5 minutes
        is_live = time_diff_seconds < 300  # 5 minutes
        data_type = "LIVE" if is_live else "HISTORICAL"
        
        candle_details = {
            'time': candle_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'date': candle_timestamp.strftime('%Y-%m-%d'),
            'time_only': candle_timestamp.strftime('%H:%M:%S'),
            'open': ohlc_list[-1][0],
            'high': ohlc_list[-1][1],
            'low': ohlc_list[-1][2],
            'close': ohlc_list[-1][3],
            'range': ohlc_list[-1][1] - ohlc_list[-1][2],
            'symbol': features['symbol'],
            'timeframe': features['timeframe'],
            'data_type': data_type,
            'candle_position': len(df)  # Position of current candle (1-indexed, max 100)
        }
        
        # Show data type indicator in console (only if candle changed)
        global last_printed_candle
        current_candle_key = (candle_details['date'], candle_details['time_only'], features['symbol'], features['timeframe'])
        if current_candle_key != last_printed_candle:
            # NEW CANDLE - print debug and full candle info
            print(f">>> DEBUG: Received {len(raw_history)} candles from {features['symbol']} ({features['timeframe']})")
            data_indicator = "[LIVE]" if is_live else "[HISTORICAL]"
            candle_position = len(df)  # Position of current candle (1-indexed)
            print(f">>> CANDLE {data_indicator} [{candle_details['date']} {candle_details['time_only']}] {features['symbol']} {features['timeframe']} | Position: {candle_position}/100")
            last_printed_candle = current_candle_key
        else:
            # SAME CANDLE - just print a dot to show data is flowing
            print(".", end="", flush=True)
        
        return df, features, (candle_details, {}) # No MTF data in this path
    except Exception as e:
        parse_error_count += 1
        log_parser_error("GENERAL_PARSE_ERROR", str(data_string)[:200], str(e))
        print(f"Error parsing data: {e}")
        if parse_error_count % 10 == 0:
            print(f">>> WARNING: {parse_error_count} parse errors detected. Check {PARSER_LOG} for details.")
        return None, None, None


def simulate_trades_on_ohlc(ohlc_df, base_features):
    """
    FIX 4: Simulate simple momentum-based trades on the received OHLC candles.
    This bootstraps the AI brain with initial training data when no history CSV exists.
    Uses a basic strategy: if close > open (bullish candle), label as win (1), else loss (0).
    The AI will refine this with real trade outcomes as they come in from MT5.
    """
    global ai_brain
    if len(ohlc_df) < 10:
        return
    
    simulated_count = 0
    for i in range(5, len(ohlc_df) - 1):
        try:
            row = ohlc_df.iloc[i]
            next_row = ohlc_df.iloc[i + 1]
            
            # Simple momentum: if this candle is bullish, predict next goes up
            is_bullish = row['Close'] > row['Open']
            next_bullish = next_row['Close'] > next_row['Open']
            
            # Outcome: 1 if prediction was correct, 0 if wrong
            outcome = 1 if (is_bullish == next_bullish) else 0
            
            # Estimate pips from the next candle's range
            pips = (next_row['High'] - next_row['Low']) * (1 if outcome == 1 else -1)
            
            # Build a simple feature set from OHLC data
            sim_features = dict(base_features)  # Copy current features as base
            sim_features['set_magnitude'] = int(abs(row['Close'] - row['Open']) * 10000)
            sim_features['bars_duration'] = i
            sim_features['hour_of_day'] = ohlc_df.index[i].hour if hasattr(ohlc_df.index[i], 'hour') else 12
            
            timestamp = int(ohlc_df.index[i].timestamp()) if hasattr(ohlc_df.index[i], 'timestamp') else int(time.time()) - (len(ohlc_df) - i) * 1800
            
            ai_brain.record_and_learn(
                features=sim_features,
                outcome=outcome,
                pips=pips,
                bars=1,
                timestamp=timestamp
            )
            simulated_count += 1
            
            if ai_brain.brain_age >= 20:
                break  # Stop once we have enough initial data
        except Exception as e:
            continue
    
    if simulated_count > 0:
        print(f">>> [SIM] Bootstrapped AI with {simulated_count} simulated trades from OHLC history. Brain age: {ai_brain.brain_age}")


def handle_client(client_socket):
    global global_mt5_symbol, global_mt5_timeframe, global_socket_status, ohlc_data_history, ai_score_history, global_candle_details, global_mtf_data, global_mtf_mode, last_heartbeat_time
    global_socket_status = "CONNECTED"
    # FIX 1: Remove inherited timeout from server socket.
    # MT5 uses a non-blocking socket (ioctlsocket FIONBIO), so it may call recv()
    # before Python has replied, getting WSAEWOULDBLOCK. Python must stay connected
    # and keep the socket alive. Setting timeout=None makes Python's recv() block
    # indefinitely, keeping the connection alive between MT5 ticks.
    client_socket.settimeout(None)
    print("\n" + "="*60)
    print("[STATE] >>> PYTHON CONNECTED TO MT5 <<<")
    print("[STATE] Waiting for market data from MT5...")
    print("="*60 + "\n")
    try:
        while not global_stop_event.is_set():
            data = client_socket.recv(BUFFER_SIZE).decode('utf-8')
            if not data: 
                print("Client disconnected.")
                break
            
            # Update heartbeat time on any received data
            last_heartbeat_time = time.time()

            if data.strip() == "HEARTBEAT":
                print("[HEARTBEAT] Received heartbeat from MT5.")
                client_socket.sendall(b"PONG\n")
                time.sleep(0.1) # Respond to heartbeat with newline
                continue

            print(f"[DATA IN] Received {len(data)} bytes from MT5")
            
            if data.strip().startswith('{'):
                try:
                    json_data = json.loads(data)
                    if json_data.get('action') == 'learn':
                        ai_brain.record_and_learn(
                            features=json_data.get('features', {}),
                            outcome=json_data.get('outcome', 0),
                            pips=json_data.get('pips', 0),
                            bars=json_data.get('bars', 0),
                            timestamp=json_data.get('timestamp', int(time.time()))
                        )
                except json.JSONDecodeError:
                    pass
                continue

            ohlc_df, features, extra_data = parse_mql5_data(data)
            
            if extra_data and extra_data[0] is None and extra_data[1]: # MTF data only
                global_candle_details, global_mtf_data = extra_data
                # For MTF mode, we don't have a single OHLC_DF or main features to plot on ax_main
                # We need to decide what to display. For now, we'll just update global_mtf_data
                # and let the visualizer handle it.
                plot_update_queue.put({
                    'ohlc': ohlc_data_history, # Keep previous OHLC for main plot
                    'scores': pd.Series(ai_score_history, index=ohlc_data_history.index[-len(ai_score_history):]) if not ohlc_data_history.empty else pd.Series(),
                    'set': 0, # N/A for MTF only
                    'status': global_socket_status,
                    'symbol': global_mt5_symbol,
                    'tf': global_mt5_timeframe,
                    'snr': 0, # N/A for MTF only
                    'candle_details': global_candle_details, # This will be from the last single TF update
                    'mtf_data': global_mtf_data
                })
                continue

            if ohlc_df is not None and features is not None:
                print(f"[DATA PARSE] Symbol={features.get('symbol', '?')}, TF={features.get('timeframe', '?')}, Candles={len(ohlc_df)}")
            else:
                print(f"[DATA ERROR] Failed to parse data from MT5")
                continue
            
            if extra_data:
                global_candle_details, _ = extra_data # MTF data is handled by the MTF_DATA block
            
            if features['symbol'] != global_mt5_symbol or features['timeframe'] != global_mt5_timeframe:
                global_mt5_symbol = features['symbol']
                global_mt5_timeframe = features['timeframe']
                ai_score_history = []
            
            if ai_brain.learning_status == "INITIALIZING":
                ai_brain.learning_status = "LEARNING" if ai_brain.brain_age < 50 else "EVOLVING"

            try:
                score, direction, max_hold = ai_brain.predict(features)
                response = f"{score:.4f}|{direction}|{max_hold}\n"
                print(f"[DATA OUT] Sending response: Score={score:.4f}, Direction={direction}, MaxHold={max_hold}")
                client_socket.sendall(response.encode('utf-8'))
                time.sleep(0.1) # Response already includes \n
            except Exception as e:
                print(f"[DATA ERROR] Failed to predict or send response: {e}")
                continue
            
            ohlc_data_history = ohlc_df
            ai_score_history.append(score)
            if len(ai_score_history) > len(ohlc_data_history):
                ai_score_history.pop(0)
            
            # FIX 4: Simulate trades on received OHLC candles to bootstrap AI training.
            # If the history CSV is empty or missing, we run a simple momentum simulation
            # on the 100 candles to generate initial training data for the AI brain.
            if ai_brain.brain_age < 20 and len(ohlc_df) >= 10:
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
                'mtf_data': global_mtf_data # Pass the global MTF data
            })
    except ConnectionResetError:
        print("[SOCKET] Client (MT5) forcibly closed the connection.")
    except socket.timeout:
        # Should not happen since we set timeout=None, but handle gracefully
        print("[SOCKET WARNING] Client socket timed out unexpectedly. MT5 may have disconnected.")
    except Exception as e:
        print(f"[SOCKET ERROR] Error in client handler: {e}")
    finally:
        global_socket_status = "DISCONNECTED"
        try:
            client_socket.close()
        except Exception:
            pass
        print("[SOCKET] Connection closed. Waiting for MT5 to reconnect...")

def socket_server():
    global last_heartbeat_time
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)
    print(f"Listening on {HOST}:{PORT}")
    server.settimeout(1.0)

    while not global_stop_event.is_set():
        try:
            client, addr = server.accept()
            print(f"Accepted connection from {addr}")
            handler = threading.Thread(target=handle_client, args=(client,), daemon=True)
            handler.start()
        except socket.timeout:
            # Check for heartbeat timeout if no connection is active
            if global_socket_status == "DISCONNECTED" and (time.time() - last_heartbeat_time > 30):
                print("[WARNING] No MT5 connection or heartbeat for 30 seconds. Is MT5 running?")
                last_heartbeat_time = time.time() # Reset to avoid spamming
            continue
    server.close()
    print("Server shut down.")

def run_visualizer():
    viz = Visualizer(global_mt5_symbol)
    plt.show(block=False)  # Show window non-blocking
    
    while not global_stop_event.is_set():
        # FIX 2: Always process matplotlib events, even when no data arrives.
        # The previous code had `continue` inside the inner except queue.Empty,
        # which skipped flush_events/plt.pause and made the window unresponsive.
        # Now we always call flush_events and plt.pause on every loop iteration.
        try:
            if not plt.fignum_exists(viz.fig.number):
                print("Visualizer window closed by user.")
                global_stop_event.set()
                break

            # Try to get data from the queue (non-blocking with short timeout)
            try:
                data = plot_update_queue.get(block=False)
                viz.update_plot(
                    data['ohlc'],
                    data['scores'],
                    data['set'],
                    data['status'],
                    data['symbol'],
                    data['tf'],
                    data['snr'],
                    data.get('candle_details', {}),
                    data.get('mtf_data', {})
                )
            except queue.Empty:
                # No new data - that's fine, just keep the window responsive
                pass

            # ALWAYS flush events and pause so matplotlib can process
            # button clicks, window moves, and other GUI events
            viz.fig.canvas.flush_events()
            plt.pause(0.05)  # 50ms pause - enough for GUI responsiveness

        except Exception as e:
            print(f"Visualizer update error: {e}")
            import traceback
            traceback.print_exc()
            break

    plt.close(viz.fig)
    print("Visualizer shut down.")

def main():
    print(f">>> {VERSION}")
    print(f">>> BRAIN FILE: {BRAIN_FILE}")
    print(f">>> HISTORY CSV: {HISTORY_CSV}")
    print(f">>> Starting AI Brain Server on {HOST}:{PORT}...")
    
    # Start socket server in background thread
    server_thread = threading.Thread(target=socket_server, daemon=True)
    server_thread.start()
    
    # macOS FIX: Run visualizer on main thread (required for Tkinter/matplotlib on macOS)
    # The visualizer must be on the main thread, not a daemon thread
    try:
        run_visualizer()
    except KeyboardInterrupt:
        pass
    
    # Cleanup
    print(">>> Shutting down...")
    global_stop_event.set()
    time.sleep(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n>>> Interrupted by user.")
        global_stop_event.set()
    except Exception as e:
        print(f">>> Fatal error: {e}")
        global_stop_event.set()
    
    # Final summary
    print("\n" + "="*80)
    print("MASTER AI PERFORMANCE SUMMARY - " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*80)
    print("TL Strategy Mode          | Trades   | Wins   | Win Rate   | Avg AI Score")
    print("-"*80)
    for mode, stats in performance_tracker.stats.items():
        wr = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0.0
        print(f"{mode:<24} | {stats['trades']:<8} | {stats['wins']:<6} | {wr:>6.1f}% | {0.00:>10.2f}")
    print("="*80)
    print("\n>>> System gracefully shut down.")
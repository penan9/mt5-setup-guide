import socket
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
from sklearn.ensemble import RandomForestClassifier

warnings.filterwarnings("ignore", category=UserWarning)
VERSION = "AI Brain Master 10.0 - SnR Validation & Multi-TF TP Scaling"

# --- Configuration ---
HOST = '127.0.0.1'
PORT = 8888
BUFFER_SIZE = 8192
BRAIN_FILE = "ai_brain.joblib"
BRAIN_BACKUP = "ai_brain_backup.joblib"
STATS_FILE = "cumulative_stats.json"
STATS_BACKUP = "cumulative_stats_backup.json"
HISTORY_CSV = "MT5_Set_History.csv"

# macOS Stability Settings
matplotlib.use('TkAgg')

# --- Global Control & Data ---
global_stop_event = threading.Event()
plot_update_queue = queue.Queue()
ohlc_data_history = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close'], dtype=float)
ohlc_data_history.index = pd.DatetimeIndex([], name='Date')
ai_score_history = []
global_mt5_symbol = "UNKNOWN"
global_mt5_timeframe = "UNKNOWN"
global_socket_status = "DISCONNECTED"

# --- Robust Performance Tracker ---
class TradePerformanceTracker:
    def __init__(self, stats_file, backup_file):
        self.stats_file = stats_file
        self.backup_file = backup_file
        self.stats = self.load_with_recovery()
        
    def load_with_recovery(self):
        for path in [self.stats_file, self.backup_file]:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                        print(f"Loaded stats from {path}")
                        restored_stats = {int(k): v for k, v in data.items()}
                        original_names = {0: 'open-open', 1: 'close-close', 2: 'high-high', 3: 'low-low'}
                        for i, name in original_names.items():
                            if i not in restored_stats:
                                restored_stats[i] = {'name': name, 'trades': 0, 'wins': 0, 'total_score': 0}
                            elif 'TL Option' in restored_stats[i]['name']:
                                restored_stats[i]['name'] = name
                        return restored_stats
                except: continue
        return {0: {'name': 'open-open', 'trades': 0, 'wins': 0, 'total_score': 0},
                1: {'name': 'close-close', 'trades': 0, 'wins': 0, 'total_score': 0},
                2: {'name': 'high-high', 'trades': 0, 'wins': 0, 'total_score': 0},
                3: {'name': 'low-low', 'trades': 0, 'wins': 0, 'total_score': 0}}

    def save_with_backup(self):
        try:
            with open(self.stats_file, 'w') as f:
                json.dump(self.stats, f, indent=4)
            shutil.copy2(self.stats_file, self.backup_file)
        except: pass

    def log_trade(self, tl_option, success, score):
        if tl_option in self.stats:
            self.stats[tl_option]['trades'] += 1
            if success: self.stats[tl_option]['wins'] += 1
            self.stats[tl_option]['total_score'] += score
            self.save_with_backup()

    def print_summary(self):
        print("\n" + "="*85)
        print(f"MASTER AI PERFORMANCE SUMMARY - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*85)
        print(f"{'TL Strategy Mode':<25} | {'Trades':<8} | {'Wins':<6} | {'Win Rate':<10} | {'Avg AI Score':<12}")
        print("-" * 85)
        for tl_opt, data in self.stats.items():
            trades = data['trades']
            wr = (data['wins'] / trades * 100) if trades > 0 else 0.0
            avg = (data['total_score'] / trades) if trades > 0 else 0.0
            print(f"{data['name']:<25} | {trades:<8} | {data['wins']:<6} | {wr:>8.1f}% | {avg:>11.2f}")
        print("="*85 + "\n")

# --- Persistent AI Brain ---
class AIBrain:
    def __init__(self, brain_file, backup_file, history_csv):
        self.brain_file = brain_file
        self.backup_file = backup_file
        self.history_csv = history_csv
        self.model = self.load_with_recovery()
        self.feature_cols = [
            'set_magnitude', 'bars_duration', 'hour_of_day', 'dist_from_be', 
            'active_TL_option', 'dynamic_TL_slope', 'snr_weight', 
            'is_at_snr', 'tp_m15', 'tp_h1', 'rejection_candle_total_range', 
            'rejection_candle_body_size', 'rejection_candle_upper_wick_size', 
            'rejection_candle_lower_wick_size', 'rejection_candle_body_to_range_ratio', 
            'rejection_candle_is_large_relative_to_average', 'rejection_candle_volume', 
            'bearish_sequence_length'
        ]

    def load_with_recovery(self):
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
        except: pass

    def predict(self, features):
        score_rules = 0.5
        direction = 0
        
        # 1. SN-R / ZONE VALIDATION (Exhaustion Rule)
        snr_weight = features.get('snr_weight', 0)
        is_at_snr = features.get('is_at_snr', False)
        snr_factor = (snr_weight * 0.1) if is_at_snr else -0.2
        
        # 2. MULTI-TF TREND CONFLUENCE (Mandatory Alignment)
        trend_m30 = features.get('trend_m30', 0)
        trend_h1 = features.get('trend_h1', 0)
        trend_h4 = features.get('trend_h4', 0)
        
        # 3. REJECTION PRECISION (Sharp Wick at Boundary)
        rejection_factor = 0.0
        if features.get('rejection_candle_total_range', 0) > 0:
            upper = features.get('rejection_candle_upper_wick_size', 0)
            lower = features.get('rejection_candle_lower_wick_size', 0)
            total = features.get('rejection_candle_total_range', 1)
            if upper > (total * 0.6): rejection_factor = -0.4 # Sharp Bearish
            elif lower > (total * 0.6): rejection_factor = 0.4 # Sharp Bullish
            
        # 4. FINAL BIAS CALCULATION
        total_bias = snr_factor + rejection_factor
        
        # Mandatory Trend Filter: Must align with at least one higher TF
        if total_bias > 0.3 and (trend_m30 == 1 or trend_h1 == 1):
            direction = 1
            score_rules = 0.6 + abs(total_bias)
        elif total_bias < -0.3 and (trend_m30 == -1 or trend_h1 == -1):
            direction = -1
            score_rules = 0.6 + abs(total_bias)
        else:
            direction = 0
            score_rules = 0.4 # Low confidence if no alignment or SnR
            
        # 5. ML BRAIN PREDICTION
        ml_prob = 0.5
        try:
            if hasattr(self.model, "classes_"):
                hour = datetime.fromtimestamp(features.get('timestamp', time.time())).hour
                feat_vec = [features.get('set_magnitude', 0), features.get('bars_duration', 0), hour, features.get('dist_from_be', 0), features.get('active_TL_option', 0), features.get('dynamic_TL_slope', 0), features.get('snr_weight', 0), features.get('is_at_snr', 0), features.get('tp_m15', 0), features.get('tp_h1', 0), features.get('rejection_candle_total_range', 0), features.get('rejection_candle_body_size', 0), features.get('rejection_candle_upper_wick_size', 0), features.get('rejection_candle_lower_wick_size', 0), features.get('rejection_candle_body_to_range_ratio', 0), int(features.get('rejection_candle_is_large_relative_to_average', False)), features.get('rejection_candle_volume', 0), features.get('bearish_sequence_length', 0)]
                ml_prob = self.model.predict_proba([feat_vec])[0][1]
        except: pass
        
        final_score = (score_rules * 0.4) + (ml_prob * 0.6)
        return max(0.0, min(1.0, final_score)), direction

# --- Global Instances ---
performance_tracker = TradePerformanceTracker(STATS_FILE, STATS_BACKUP)
ai_brain = AIBrain(BRAIN_FILE, BRAIN_BACKUP, HISTORY_CSV)

# --- Restored MT5-Style Visualizer ---
class Visualizer:
    def __init__(self, symbol_name):
        self.symbol_name = symbol_name
        self.mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', edge='inherit', wick='inherit', volume='gray', ohlc='inherit')
        self.mpf_style = mpf.make_mpf_style(base_mpf_style='charles', marketcolors=self.mc, facecolor='black', figcolor='black', gridcolor='#2c2c2c', gridstyle='--', rc={'axes.edgecolor': 'white', 'ytick.color': 'white', 'xtick.color': 'white', 'axes.labelcolor': 'white', 'font.size': 8}, y_on_right=True)
        self.fig = plt.figure(figsize=(10, 8), facecolor='black')
        gs = self.fig.add_gridspec(4, 1, height_ratios=[3, 1, 1, 0.5], hspace=0.2)
        self.ax_main = self.fig.add_subplot(gs[0, 0], facecolor='black')
        self.ax_ai = self.fig.add_subplot(gs[1, 0], facecolor='black', sharex=self.ax_main)
        self.ax_kpi = self.fig.add_subplot(gs[2, 0], facecolor='black')
        self.ax_stop = self.fig.add_subplot(gs[3, 0])
        self.btn_stop = Button(self.ax_stop, 'STOP & SAVE', color='red', hovercolor='darkred')
        self.btn_stop.on_clicked(lambda e: global_stop_event.set())
        self.fig.canvas.mpl_connect('close_event', lambda e: global_stop_event.set())
        print("Visualizer window initialized.")

    def update_plot(self, ohlc_df, ai_scores, current_set, status, symbol, tf, snr_weight):
        if not plt.fignum_exists(self.fig.number): return
        self.fig.suptitle(f'{symbol} ({tf}) - Status: {status} - Set: {current_set} - SnR Weight: {snr_weight}', color='white', y=0.98)
        if not ohlc_df.empty:
            self.ax_main.clear()
            self.ax_ai.clear()
            apds = [mpf.make_addplot(ai_scores, color='#00ffff', ax=self.ax_ai, width=1.2)]
            mpf.plot(ohlc_df, type='candle', style=self.mpf_style, ax=self.ax_main, addplot=apds, show_nontrading=False, datetime_format='%H:%M')
            self.ax_main.axhline(ohlc_df['Close'].iloc[-1], color='white', linestyle='-', linewidth=0.5, alpha=0.7)
            self.ax_ai.set_ylabel('AI Score', color='white')
            self.ax_ai.set_ylim(0, 1)
            
            # KPI Table Overlay
            self.ax_kpi.clear()
            self.ax_kpi.axis('off')
            kpi_text = "TL STRATEGY PERFORMANCE (MASTER V5):\n"
            for i, d in performance_tracker.stats.items():
                wr = (d['wins']/d['trades']*100) if d['trades']>0 else 0.0
                kpi_text += f"{d['name']:<15}: {d['trades']:>3} Trades | {wr:>5.1f}% Win Rate\n"
            self.ax_kpi.text(0.05, 0.5, kpi_text, color='lime', fontsize=9, family='monospace', va='center')
            
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()

def parse_mql5_data(data_string):
    try:
        parts = data_string.replace('\x00', '').strip().split('|')
        if len(parts) < 5: return None, None
        raw_history = parts[0].strip(';').split(';')
        ohlc_list = []
        for candle in raw_history:
            if not candle: continue
            o, h, l, c = map(float, candle.split(','))
            ohlc_list.append([o, h, l, c])
        df = pd.DataFrame(ohlc_list, columns=['Open', 'High', 'Low', 'Close'])
        df.index = pd.date_range(end=datetime.now(), periods=len(df), freq='15min')
        
        features = {'symbol': parts[1], 'timestamp': int(float(parts[2])), 'set_count': int(float(parts[3])), 'timeframe': parts[4]}
        if len(parts) >= 21:
            features.update({
                'set_magnitude': float(parts[5]), 'bars_duration': int(float(parts[6])), 'dist_from_be': float(parts[7]),
                'active_TL_option': int(float(parts[8])), 'dynamic_TL_slope': float(parts[9]), 'snr_weight': int(float(parts[10])),
                'is_at_snr': bool(int(float(parts[11]))), 'tp_m15': float(parts[12]), 'tp_h1': float(parts[13]),
                'rejection_candle_total_range': float(parts[14]), 'rejection_candle_body_size': float(parts[15]),
                'rejection_candle_upper_wick_size': float(parts[16]), 'rejection_candle_lower_wick_size': float(parts[17]),
                'rejection_candle_is_large_relative_to_average': bool(int(float(parts[18]))), 'rejection_candle_volume': float(parts[19]),
                'bearish_sequence_length': int(float(parts[20]))
            })
            features['rejection_candle_body_to_range_ratio'] = features['rejection_candle_body_size'] / features['rejection_candle_total_range'] if features['rejection_candle_total_range'] > 0 else 0.0
        if len(parts) >= 24:
            features.update({'trend_m30': int(float(parts[21])), 'trend_h1': int(float(parts[22])), 'trend_h4': int(float(parts[23]))})
        return df, features
    except: return None, None

def handle_client(conn, addr):
    global ohlc_data_history, ai_score_history, global_mt5_symbol, global_mt5_timeframe, global_socket_status
    global_socket_status = "CONNECTED"
    print(f"MT5 Connected from {addr}")
    try:
        while not global_stop_event.is_set():
            data = conn.recv(BUFFER_SIZE)
            if not data: break
            df, features = parse_mql5_data(data.decode('utf-8', errors='ignore'))
            if features:
                score, direction = ai_brain.predict(features)
                conn.sendall(f"{score:.4f}|{direction}|20".encode('utf-8'))
                ohlc_data_history = df
                ai_score_history = [score] * len(df)
                global_mt5_symbol = features['symbol']
                global_mt5_timeframe = features['timeframe']
                # INSTANT TF DETECTION: Clear old history if timeframe changes
                if global_mt5_timeframe != features['timeframe']:
                    ohlc_data_history = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close'], dtype=float)
                    ai_score_history = []
                    while not plot_update_queue.empty():
                        try: plot_update_queue.get_nowait()
                        except: break
                
                if score >= 0.70:
                    performance_tracker.log_trade(features.get('active_TL_option', 0), True, score)
                
                plot_update_queue.put((ohlc_data_history, ai_score_history, features['set_count'], global_socket_status, global_mt5_symbol, global_mt5_timeframe, features.get('snr_weight', 0)))
    except Exception as e: print(f"Client error: {e}")
    finally: global_socket_status = "DISCONNECTED"; conn.close(); print("MT5 Disconnected.")

def socket_server():
    print(f"Socket server listening on {HOST}:{PORT}...")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT)); s.listen(); s.settimeout(1.0)
        while not global_stop_event.is_set():
            try:
                conn, addr = s.accept()
                threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
            except socket.timeout: continue

def main():
    print(f"Starting {VERSION}...")
    visualizer = Visualizer("MT5 AI Master V5")
    threading.Thread(target=socket_server, daemon=True).start()
    
    last_summary = time.time()
    try:
        while not global_stop_event.is_set():
            if time.time() - last_summary > 60:
                performance_tracker.print_summary()
                last_summary = time.time()
            
            try:
                item = plot_update_queue.get_nowait()
                visualizer.update_plot(*item)
            except queue.Empty: pass
            
            plt.pause(0.01)
    except KeyboardInterrupt: global_stop_event.set()
    
    print("Shutting down...")
    ai_brain.save_with_backup()
    performance_tracker.save_with_backup()
    print("Master AI Data Saved. Shutdown complete.")

if __name__ == "__main__": main()
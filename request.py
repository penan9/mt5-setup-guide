import socket
import threading
import os
import time
import json
import sys
from datetime import datetime, timezone
import pandas as pd
import mplfinance as mpf
import matplotlib
from matplotlib.widgets import Button
import matplotlib.pyplot as plt
import numpy as np
import queue # For thread-safe plot updates
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
VERSION = "Working socket 1.0.4 with set 7 strategy"

# --- Configuration ---
HOST = '127.0.0.1' # Standard loopback interface address (localhost)
PORT = 8888 # Port to listen on (non-privileged ports are > 1023)
BUFFER_SIZE = 8192 # Must match MQL5's buf size

# macOS Stability Settings
matplotlib.use('TkAgg')

# --- Global Data Storage for Visualization ---
ohlc_data_history = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume'], dtype=float)
ohlc_data_history.index = pd.DatetimeIndex([], name='Date')

ai_score_history = []
ai_direction_history = []
last_processed_timestamp = 0

# --- NEW: Shutdown Control ---
global_stop_event = threading.Event()

# --- NEW: Initialize the queue globally ---
plot_update_queue = queue.Queue() # For thread-safe plot updates

# --- Rules-Based AI Engine ---
class AI_Model:
    def __init__(self):
        print("AI_Model: Rules-Based Engine Initialized.")

    def predict(self, features):
        """
        Hierarchical AI Scoring: HTF Context + LTF Setup (7-Set Rejection)
        """
        score = 0.5
        direction = 0
        
        # 1. HTF Context (H1 & H4) - Acts as a Multiplier/Filter
        htf_bias = 0
        htf_bias += features.get('trend_h4', 0) * 0.15
        htf_bias += features.get('trend_h1', 0) * 0.15
        htf_bias += features.get('trend_m15', 0) * 0.10
        
        # 2. LTF Setup (7-Set Logic)
        set_count = features.get('set_count', 0)
        set_factor = 0.0
        if set_count == 7:
            set_factor = 0.3  # Huge boost for the target setup
        elif set_count > 4:
            set_factor = 0.1
            
        # 3. Rejection Quality (at Set-7)
        rejection_factor = 0.0
        if features.get('rejection_candle_total_range', 0) > 0:
            upper_wick = features.get('rejection_candle_upper_wick_size', 0)
            lower_wick = features.get('rejection_candle_lower_wick_size', 0)
            total_range = features.get('rejection_candle_total_range', 1)
            
            # Long Upper Wick (Bearish Rejection)
            if upper_wick > (total_range * 0.5):
                rejection_factor = -0.3
            # Long Lower Wick (Bullish Rejection)
            elif lower_wick > (total_range * 0.5):
                rejection_factor = 0.3

        # --- FINAL CALCULATION ---
        # Combine factors: Bias + Setup + Rejection
        total_bias = htf_bias + (set_factor * (1 if rejection_factor > 0 else -1 if rejection_factor < 0 else 0)) + rejection_factor
        
        # Filtering: Only allow high score if setup aligns with HTF
        if total_bias > 0.2:
            direction = 1  # BUY
            score = 0.6 + abs(total_bias)
        elif total_bias < -0.2:
            direction = -1 # SELL
            score = 0.6 + abs(total_bias)
        else:
            direction = 0
            score = 0.4 # Low confidence if no alignment
            
        return max(0.0, min(1.0, score)), direction

# --- Socket Communication Globals ---
global_socket_status = "DISCONNECTED"
global_current_set_count = 0
global_current_price = 0.0
global_ai_model = AI_Model() # Initialize the engine
global_mt5_symbol = "UNKNOWN"
global_mt5_timeframe = "UNKNOWN"

class Visualizer:
    def __init__(self, symbol_name):
        self.symbol_name = symbol_name
        self.fig = None
        self.ax_main = None
        self.ax_volume = None
        self.ax_ai = None
        self.mpf_style = None
        self.initial_plot_done = False
        self.create_figure()

    def on_close(self, event):
        """Handle the window 'X' click event."""
        print("Window closed. Shutting down gracefully...")
        global_stop_event.set()

    def create_figure(self):
        # 1. Define MT5-Specific Colors
        self.mc = mpf.make_marketcolors(
            up='#00ff00',       # MT5 Green
            down='#ff0000',     # MT5 Red
            edge='inherit',     # Edges match candle body
            wick='inherit', 
            volume='gray',
            ohlc='inherit'
        )

        # 2. Define the "MetaTrader 5 Black" Style
        self.mpf_style = mpf.make_mpf_style(
            base_mpf_style='charles', 
            marketcolors=self.mc,
            facecolor='black',
            figcolor='black',
            gridcolor='#2c2c2c',  # Subtle dark grid
            gridstyle='--',
            rc={
                'axes.edgecolor': 'white',
                'ytick.color': 'white',
                'xtick.color': 'white',
                'axes.labelcolor': 'white',
                'font.size': 8
            },
            y_on_right=True       # Price on the right side
        )

        self.fig = plt.figure(figsize=(10, 8), facecolor='black')
        self.fig.canvas.mpl_connect('close_event', self.on_close) # Connect close event
        
        gs = self.fig.add_gridspec(3, 1, height_ratios=[3, 1, 1], hspace=0.1)

        self.ax_main = self.fig.add_subplot(gs[0, 0])
        self.ax_volume = self.fig.add_subplot(gs[1, 0], sharex=self.ax_main)
        self.ax_ai = self.fig.add_subplot(gs[2, 0], sharex=self.ax_main)

        self.ax_main.set_facecolor('black')
        self.ax_main.tick_params(axis='y', labelcolor='white')
        self.ax_main.tick_params(axis='x', labelcolor='white')
        self.ax_main.grid(True, linestyle='--', alpha=0.6, color='gray')

        self.ax_volume.set_facecolor('black')
        self.ax_volume.tick_params(axis='y', labelcolor='white')
        self.ax_volume.tick_params(axis='x', labelcolor='white')
        self.ax_volume.set_ylabel('Volume', color='white')
        self.ax_volume.grid(True, linestyle='--', alpha=0.6, color='gray')

        self.ax_ai.set_facecolor('black')
        self.ax_ai.tick_params(axis='y', labelcolor='white')
        self.ax_ai.tick_params(axis='x', labelcolor='white')
        self.ax_ai.set_ylabel('AI Score', color='white')
        self.ax_ai.grid(True, linestyle='--', alpha=0.6, color='gray')

        self.fig.suptitle(f'{self.symbol_name} ({global_mt5_timeframe}) - Status: {global_socket_status}', color='white', y=0.98)
        self.fig.subplots_adjust(top=0.92, bottom=0.08, left=0.10, right=0.95, hspace=0.3)
        self.fig.canvas.draw_idle()
        plt.show(block=False)

    def update_plot(self, ohlc_df, ai_scores, ai_directions, current_set, socket_status):
        if not plt.fignum_exists(self.fig.number):
            return # Don't update if window is closed

        self.fig.suptitle(f'{self.symbol_name} ({global_mt5_timeframe}) - Status: {socket_status} - Set: {current_set}', color='white', y=0.98)

        if not ohlc_df.empty:
            # Clear for fresh render
            self.ax_main.clear()
            self.ax_ai.clear()
            self.ax_volume.set_visible(False) # Volume hidden

            # Addplot for AI Score (Cyan line)
            apds = [
                mpf.make_addplot(ai_scores, color='#00ffff', ax=self.ax_ai, width=1.2)
            ]

            # Formatting axes to stay black
            for ax in [self.ax_main, self.ax_ai]:
                ax.set_facecolor('black')
                ax.tick_params(axis='both', colors='white')
                ax.grid(True, linestyle='--', alpha=0.3, color='gray')

            # Execute MT5-Style Plot
            mpf.plot(
                ohlc_df,
                type='candle',
                style=self.mpf_style,
                ax=self.ax_main,
                volume=False,
                addplot=apds,
                show_nontrading=False,
                datetime_format='%H:%M'
            )

            # Draw a horizontal "Current Price" line (White/Blue like MT5)
            current_price = ohlc_df['Close'].iloc[-1]
            self.ax_main.axhline(current_price, color='white', linestyle='-', linewidth=0.5, alpha=0.7)

            self.fig.canvas.draw_idle()
            self.fig.canvas.flush_events()
                
        else:
            # Handle empty data state
            self.ax_main.clear()
            self.ax_main.text(0.5, 0.5, "Waiting for 100 bars of data...", 
                              transform=self.ax_main.transAxes, color='white',
                              fontsize=12, ha='center', va='center')
            self.fig.canvas.draw_idle()

def parse_mql5_data(data_string):
    try:
        # 1. Clean up null bytes and whitespace only
        clean_data = data_string.replace('\x00', '').strip()
        
        # 2. Split the main blocks (History | Symbol | Time | Set | TF | Features)
        parts = clean_data.split('|')

        if len(parts) < 4:
            return None

        # 3. Process the 100 semicolon-separated candles
        raw_history = parts[0].strip(';').split(';')
        history_list = []
        
        for candle in raw_history:
            if not candle: continue
            prices = [float(p) for p in candle.split(',')]
            history_list.append(prices + [0.0]) 

        # 4. Extract basic metadata
        features = {
            'type': 'trade_data',
            'history_list': history_list,
            'symbol': parts[1],
            'timestamp': int(float(parts[2])),
            'set_count': int(float(parts[3])),
            'timeframe': parts[4] if len(parts) > 4 else "UNK"
        }

        # 5. Extract captured features if available
        if len(parts) >= 21: # History | Symbol | Time | Set | TF | 16 Features
            features.update({
                'set_magnitude': int(float(parts[5])),
                'bars_duration': int(float(parts[6])),
                'dist_from_be': float(parts[7]),
                'active_TL_option': int(float(parts[8])),
                'dynamic_TL_slope': float(parts[9]),
                'dynamic_TL_distance_current_price': float(parts[10]),
                'channel_top_distance_current_price': float(parts[11]),
                'channel_bottom_distance_current_price': float(parts[12]),
                'channel_width': float(parts[13]),
                'rejection_candle_total_range': float(parts[14]),
                'rejection_candle_body_size': float(parts[15]),
                'rejection_candle_upper_wick_size': float(parts[16]),
                'rejection_candle_lower_wick_size': float(parts[17]),
                'rejection_candle_is_large_relative_to_average': bool(int(float(parts[18]))),
                'rejection_candle_volume': float(parts[19]),
                'bearish_sequence_length': int(float(parts[20]))
            })
            
            # 6. Extract MTF Trend Data (if available)
            if len(parts) >= 24:
                features.update({
                    'trend_m15': int(float(parts[21])),
                    'trend_h1': int(float(parts[22])),
                    'trend_h4': int(float(parts[23]))
                })
            # Add calculated ratio
            if features['rejection_candle_total_range'] > 0:
                features['rejection_candle_body_to_range_ratio'] = features['rejection_candle_body_size'] / features['rejection_candle_total_range']
            else:
                features['rejection_candle_body_to_range_ratio'] = 0.0

        return features
    except Exception as e:
        print(f"Parsing Error: {e}")
        return None
    
def handle_client(conn, addr, visualizer_instance):
    global ohlc_data_history, ai_score_history, ai_direction_history, last_processed_timestamp
    global global_socket_status, global_current_set_count, global_current_price
    global global_mt5_symbol, global_mt5_timeframe, plot_update_queue

    print(f"Connected by {addr}")
    global_socket_status = "CONNECTED"
    conn.settimeout(1.0) # Small timeout for responsiveness to stop event

    try:
        while not global_stop_event.is_set():
            try:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break

                # 1. Decode and Parse
                received_str = data.decode('utf-8', errors='ignore')
                features = parse_mql5_data(received_str)

                if not features:
                    continue

                # 2. Handle Heartbeats
                if features.get('type') == 'heartbeat':
                    conn.sendall(b"0.0|0")
                    continue

                # 3. Handle Trade Data (The 100-candle block)
                if features.get('type') == 'trade_data':
                    # Update globals for the visualizer title
                    global_current_set_count = features.get('set_count', 0)
                    global_mt5_symbol = features.get('symbol', 'XAUUSD')
                    global_mt5_timeframe = features.get('timeframe', 'UNK')

                    # Create a fresh timestamp index for the 100 candles
                    end_ts = features['timestamp']
                    # Assume 60 seconds (M1) per candle
                    start_ts = end_ts - (99 * 60)
                    new_date_range = pd.to_datetime(np.linspace(start_ts, end_ts, 100), unit='s', utc=True)
                    
                    # Overwrite history with the 100 candles sent from MT5
                    ohlc_data_history = pd.DataFrame(
                        features['history_list'],
                        columns=['Open', 'High', 'Low', 'Close', 'Volume'],
                        index=new_date_range
                    )
                    
                    # Get AI Prediction (Score)
                    score = 0.5
                    direction = 0
                    if global_ai_model:
                        score, direction = global_ai_model.predict(features)

                    # Sync AI score history to match the 100 candles
                    ai_score_history = [score] * 100
                    ai_direction_history = [direction] * 100

                    # 4. Send Response back to MT5
                    response = f"{score:.4f}|{direction}"
                    conn.sendall(response.encode('utf-8'))

                    # 5. Update Visualizer Queue
                    plot_update_queue.put({
                        'ohlc_df': ohlc_data_history.copy(),
                        'ai_scores': list(ai_score_history),
                        'ai_directions': list(ai_direction_history),
                        'current_set': global_current_set_count,
                        'socket_status': "CONNECTED"
                    })

                    # --- NEW: Only print when Symbol or Timeframe changes ---
                    static_last_state = getattr(handle_client, 'last_state', None)
                    current_state = f"{global_mt5_symbol}_{global_mt5_timeframe}"
                    
                    if static_last_state != current_state:
                        print(f"Success! {global_mt5_symbol} ({global_mt5_timeframe}) processed.")
                        handle_client.last_state = current_state
            except socket.timeout:
                continue

    except Exception as e:
        if not global_stop_event.is_set():
            print(f"Client Handling Error: {e}")
    finally:
        conn.close()
        global_socket_status = "DISCONNECTED"
        print(f"Disconnected from {addr}")

def start_server(visualizer_instance):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen()
        s.settimeout(1.0) # Small timeout for responsiveness to stop event
        print(f"Python Server listening on {HOST}:{PORT}: Version {VERSION}")
        while not global_stop_event.is_set():
            try:
                conn, addr = s.accept()
                client_thread = threading.Thread(target=handle_client, args=(conn, addr, visualizer_instance))
                client_thread.daemon = True
                client_thread.start()
            except socket.timeout:
                continue
    print("Socket Server stopped.")

def main():
    # 1. Initialize Visualizer
    viz = Visualizer("Waiting for MT5...")

    # 2. Start Socket Server in a background thread
    server_thread = threading.Thread(target=start_server, args=(viz,))
    server_thread.daemon = True
    server_thread.start()

    # 3. Main Loop: Update Plot from Queue (Thread-Safe)
    try:
        while not global_stop_event.is_set():
            try:
                # Check for updates every 100ms
                update_data = plot_update_queue.get(timeout=0.1)
                viz.update_plot(
                    update_data['ohlc_df'],
                    update_data['ai_scores'],
                    update_data['ai_directions'],
                    update_data['current_set'],
                    update_data['socket_status']
                )
            except queue.Empty:
                plt.pause(0.01) # Keep the UI responsive
                continue
    except KeyboardInterrupt:
        print("KeyboardInterrupt detected. Shutting down...")
        global_stop_event.set()
    
    # Wait for background threads if needed
    print("Program exited.")
    sys.exit(0)

if __name__ == "__main__":
    main()
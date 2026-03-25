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

# --- NEW: Initialize the queue globally ---
plot_update_queue = queue.Queue() # For thread-safe plot updates

# --- Socket Communication Globals ---
global_socket_status = "DISCONNECTED"
global_current_set_count = 0
global_current_price = 0.0
global_ai_model = None
global_mt5_symbol = "UNKNOWN"
global_mt5_timeframe = "UNKNOWN"

# --- Stub AI Model ---
class AI_Model:
    def __init__(self):
        print("AI_Model: Initialized (This is a stub).")

    def predict(self, features):
        ai_score = 0.0
        ai_direction = 0

        if 'g_current_set' in features:
            if features['g_current_set'] >= 5:
                ai_score = 0.85
                ai_direction = -1
            elif features['g_current_set'] >= 2:
                ai_score = 0.60
                ai_direction = 1
            else:
                ai_score = 0.40
                ai_direction = 0

        if 'rejection_candle_total_range' in features and features['rejection_candle_total_range'] > 0.007:
             if features['close'] > features['open']:
                 # This part of the code was truncated in the provided file.
                 # Assuming it would be used to modify ai_score/direction based on rejection candle.
                 pass

        return ai_score, ai_direction

# (Keep all your imports and global variables as they are)

# --- Stub AI Model ---
# (Keep your AI_Model class as it is)

class Visualizer:
    # (Keep your Visualizer class as it is, no changes needed here)
    def __init__(self, symbol_name):
        self.symbol_name = symbol_name
        self.fig = None
        self.ax_main = None
        self.ax_volume = None
        self.ax_ai = None
        self.mpf_style = None
        self.initial_plot_done = False
        self.create_figure()

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

        self.fig.suptitle(f'{self.symbol_name} - {global_mt5_timeframe} - Status: {global_socket_status}', color='white', y=0.98)
        self.fig.subplots_adjust(top=0.92, bottom=0.08, left=0.10, right=0.95, hspace=0.3)
        self.fig.canvas.draw_idle()
        plt.show(block=False)

    def update_plot(self, ohlc_df, ai_scores, ai_directions, current_set, socket_status):
        self.fig.suptitle(f'{self.symbol_name} - Status: {socket_status} - Set: {current_set}', color='white', y=0.98)

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
        
        # 2. Split the main blocks (History | Symbol | Time | Set)
        parts = clean_data.split('|')

        if len(parts) < 4:
            return None

        # 3. Process the 100 semicolon-separated candles
        # Each candle looks like "4557.00,4557.54,4556.43,4557.11"
        raw_history = parts[0].strip(';').split(';')
        history_list = []
        
        for candle in raw_history:
            if not candle: continue
            # Split by COMMA to get the 4 prices
            prices = [float(p) for p in candle.split(',')]
            # Add 0.0 for volume to keep the 5-column DataFrame structure
            history_list.append(prices + [0.0]) 

        return {
            'type': 'trade_data',
            'history_list': history_list,
            'symbol': parts[1],
            'timestamp': int(float(parts[2])),
            'set_count': int(float(parts[3]))
        }
    except Exception as e:
        print(f"Parsing Error: {e}")
        return None
    
def handle_client(conn, addr, visualizer_instance):
    global ohlc_data_history, ai_score_history, ai_direction_history, last_processed_timestamp
    global global_socket_status, global_current_set_count, global_current_price
    global global_mt5_symbol, global_mt5_timeframe, plot_update_queue

    print(f"Connected by {addr}")
    global_socket_status = "CONNECTED"

    try:
        while True:
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
                
                # Update globals for the visualizer title
                global_current_set_count = features.get('set_count', 0)
                global_mt5_symbol = features.get('symbol', 'XAUUSD')
                
                # Get AI Prediction (Score)
                score = 0.5
                direction = 0
                if global_ai_model:
                    score, direction = global_ai_model.predict(features)

                # Sync AI score history to match the 100 candles
                # (Simple approach: fill with current score for the visualizer)
                ai_score_history = [score] * 100
                ai_direction_history = [direction] * 100

                # 4. Send Response back to MT5
                response = f"{score:.4f}|{direction}"
                conn.sendall(response.encode('utf-8'))

                # 5. Update Visualizer Queue
                # Note: 'Volume' is in the DataFrame as 0.0, 
                # but update_plot will hide the axis because of the change we made.
                plot_update_queue.put({
                    'ohlc_df': ohlc_data_history.copy(),
                    'ai_scores': list(ai_score_history),
                    'ai_directions': list(ai_direction_history),
                    'current_set': global_current_set_count,
                    'socket_status': "CONNECTED"
                })

                print(f"Success! {global_mt5_symbol} (100 bars) processed. Score: {score:.2f} | Set: {global_current_set_count}")

    except Exception as e:
        print(f"Error handling client {addr}: {e}")
    finally:
        global_socket_status = "DISCONNECTED"
        conn.close()

def main():
    global global_ai_model, global_mt5_timeframe, plot_update_queue

    global_ai_model = AI_Model()
    viz = Visualizer(global_mt5_symbol)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen()
        print(f"Python server listening on {HOST}:{PORT}")
        global_socket_status = "LISTENING"

        while True:
            # Check if the visualizer window was closed
            if not plt.fignum_exists(viz.fig.number):
                print("Visualizer window closed. Exiting server.")
                break

            # --- Handle plot updates from the queue in the main thread ---
            try:
                # Use a non-blocking get to allow the loop to continue if no plot data
                update_data = plot_update_queue.get(block=False)
                viz.update_plot(update_data['ohlc_df'],
                                update_data['ai_scores'],
                                update_data['ai_directions'],
                                update_data['current_set'],
                                update_data['socket_status'])
            except queue.Empty:
                pass # No plot updates in the queue, continue loop

            # Accept new connections or handle existing ones
            server_socket.settimeout(0.1) # Short timeout to allow queue processing
            try:
                conn, addr = server_socket.accept()
                client_thread = threading.Thread(target=handle_client, args=(conn, addr, viz))
                client_thread.daemon = True
                client_thread.start()
            except socket.timeout:
                pass # No new connection, just continue checking queue and figure status

    except Exception as e:
        print(f"An error occurred in main: {e}")
    finally:
        server_socket.close()
        print("Python server shut down.")
        plt.close(viz.fig) # Ensure the matplotlib figure is closed

if __name__ == "__main__":
    main()
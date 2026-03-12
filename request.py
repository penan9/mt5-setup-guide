from logging import config
import os
import time
import json
import sys
from datetime import datetime, timezone
import pandas as pd
import mplfinance as mpf
import matplotlib
from matplotlib.widgets import Button
import warnings
matplotlib.use('TkAgg') # Or 'MacOSX'
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore", category=UserWarning)

# macOS Stability Backend
matplotlib.use('TkAgg') 

import pandas as pd
from xgboost import XGBClassifier

# --- ADD THIS TO YOUR PYTHON AI ENGINE ---
def calculate_entry_confidence(df, current_set):
    # Base Confidence
    score = 0
    
    # 1. Exhaustion Logic (Set 7 is a premium reversal signal)
    if current_set >= 7:
        score += 50
    
    # 2. Volatility Check (If market is too fast, reduce confidence)
    # Using simple ATR from pandas
    df['ATR'] = df['high'] - df['low']
    if df['ATR'].iloc[-1] < df['ATR'].rolling(10).mean().iloc[-1]:
        score += 30 # Stable market = Higher confidence
    
    # 3. Sentiment/Trend (Logic: If we are counter-trend, lower confidence)
    # (Optional: Add your moving average logic here)
    
    return min(score, 100) # Cap at 100%

# --- BRIDGE: Send this to MT5 ---
def send_ai_score_to_mt5(score):
    with open('ai_score.txt', 'w') as f:
        f.write(str(score))

def get_entry_proposal(current_mt5_state):
    """
    Evaluates the current live market state from test2.mq5
    """
    # Convert live data to the same feature format
    live_features = pd.DataFrame([current_mt5_state])
    
    # Get probability (0.0 to 1.0)
    probability = model.predict_proba(live_features)[0][1]
    
    if probability > 0.75:
        return f"STRONG ENTRY: {probability:.2%} Confidence"
    elif probability > 0.60:
        return f"MODERATE ENTRY: {probability:.2%} Confidence"
    else:
        return "NO TRADE: Low Probability"

# --- CONFIGURATION ---
class ConfigLoader:
    @staticmethod
    def load():
        script_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
        config_name = f"{script_name}_config.json"
        try:
            with open(config_name, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"CRITICAL ERROR: {config_name} not found.")
            sys.exit(1)

# --- SYSTEM CONTROL ---
class CommandCenter:
    def __init__(self, config):
        self.mt5_path = config["mt5_path"]
        self.trading_enabled = False
        self.state_start_time = datetime.now()
        self.analysis_mode = "SMA"

    def toggle_trading(self):
        self.trading_enabled = not self.trading_enabled
        self.state_start_time = datetime.now() 
        return self.trading_enabled

    def get_state_duration(self):
        delta = datetime.now() - self.state_start_time
        return str(delta).split(".")[0]

    def signal_mt5_shutdown(self):
        shutdown_file = os.path.join(self.mt5_path, "sys_shutdown.txt")
        try:
            with open(shutdown_file, "w") as f:
                f.write("SHUTDOWN_REQUESTED")
        except: pass

class Heartbeat:
    def __init__(self, config):
        # This path must point EXACTLY to your MT5 'Files' folder
        self.path = os.path.join(config["mt5_path"], "python_heartbeat.txt")
        print("Link with MT5 - test2 version 1.1")

    def pulse(self):
        try:
            # We use UTC timestamp to match MT5's TimeGMT()
            utc_ts = int(datetime.now(timezone.utc).timestamp())
            
            with open(self.path, "w") as f:
                f.write(str(utc_ts))
                f.flush()        # Push data out of Python buffer
                os.fsync(f.fileno()) # Force MacOS to write to the physical disk
        except Exception as e:
            print(f"Heartbeat Error: {e}")

# --- DATA & CONNECTION BRIDGE ---
class TradingBridge:
    def __init__(self, config):
        self.symbol = config["active_symbol"]
        self.mt5_path = config["mt5_path"]
        self.price_path = os.path.join(self.mt5_path, f"{self.symbol}_price.txt")
        self.current_tf = "M1" 
        # Initial path matching the MQL5 EnumToString output
        self.hist_path = os.path.join(self.mt5_path, f"{self.symbol}_PERIOD_{self.current_tf}_history.csv")
        self._last_mtime = 0
        self._start_time = time.time()

    def is_connected(self):
        try:
            if not os.path.exists(self.price_path):
                return (time.time() - self._start_time) < 5
            mtime = os.path.getmtime(self.price_path)
            return (time.time() - mtime) < 30
        except: return False

    def has_new_data(self):
        try:
            if not os.path.exists(self.price_path): return False
            mtime = os.path.getmtime(self.price_path)
            if mtime > self._last_mtime:
                self._last_mtime = mtime
                return True
            return False
        except: return False

    def get_price_and_tf(self):
        try:
            # Use binary read + decode to prevent Wine file locks
            with open(self.price_path, "rb") as f:
                content = f.read().replace(b'\x00', b'').decode('utf-8').strip().split("|")
                price = float(content[0])
                if len(content) > 1:
                    new_tf = content[1] # e.g., "PERIOD_M30"
                    if new_tf != self.current_tf:
                        self.current_tf = new_tf
                        # Updated to match MQL5: Symbol + TF + _history.csv
                        # If content[1] is "PERIOD_M30", this becomes XAUUSD_PERIOD_M30_history.csv
                        self.hist_path = os.path.join(self.mt5_path, f"{self.symbol}_{self.current_tf}_history.csv")
                return price, self.current_tf
        except: return None, self.current_tf

    def get_history_df(self):
        try:
            if not os.path.exists(self.hist_path) or os.path.getsize(self.hist_path) < 10:
                return None
            
            # --- SHADOW READ (Crucial for Wine/MT5) ---
            with open(self.hist_path, 'rb') as f:
                raw_bytes = f.read()
                content = raw_bytes.replace(b'\x00', b'').decode('utf-8', errors='ignore')
            
            from io import StringIO
            df = pd.read_csv(StringIO(content), sep='\t')
            
            df.columns = [c.strip().lower() for c in df.columns]
            
            if 'time' in df.columns:
                # Detect if it's Unix Timestamp (Seconds) or String
                first_val = str(df['time'].iloc[0])
                if first_val.replace('.', '').isdigit():
                    df['time'] = pd.to_datetime(pd.to_numeric(df['time']), unit='s')
                else:
                    df['time'] = pd.to_datetime(df['time'], format='mixed')
                df.set_index('time', inplace=True)
            
            for col in ['open', 'high', 'low', 'close']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
            return df.dropna(subset=['close']).tail(100) # Performance: only plot last 100
        except Exception as e:
            return None
        
    def get_sync_data(self):
        """Reads the sync file for Set Counts and Trendlines (Set 7 Logic)."""
        sync_file = os.path.join(self.mt5_path, f"{self.symbol}_sync.csv")
        data = {"set_count": 0, "trendlines": []}
        
        if not os.path.exists(sync_file):
            return data

        try:
            # Use binary read to bypass Wine locks
            with open(sync_file, 'rb') as f:
                content = f.read().replace(b'\x00', b'').decode('utf-8', errors='ignore')
            
            from io import StringIO
            df_sync = pd.read_csv(StringIO(content), header=None)
            
            for _, row in df_sync.iterrows():
                # Format: SET, count
                if row[0] == "SET":
                    data["set_count"] = int(row[1])
                # Format: TL, time1, price1, time2, price2
                elif row[0] == "TL" and len(row) >= 5:
                    try:
                        t1 = pd.to_datetime(int(row[1]), unit='s')
                        p1 = float(row[2])
                        t2 = pd.to_datetime(int(row[3]), unit='s')
                        p2 = float(row[4])
                        data["trendlines"].append([(t1, p1), (t2, p2)])
                    except: continue
        except Exception:
            pass # Keep moving if file is temporarily busy
            
        return data
    
# --- STRATEGY ---
class StrategyModule:
    def __init__(self, config):
        self.sma_period = config["logic_settings"]["sma_period"]

    def calculate_trend(self, price, df):
        if df is None or len(df) < self.sma_period: return "SYNCING..."
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        sma = df['close'].rolling(window=self.sma_period).mean().iloc[-1]
        if pd.isna(sma): return "WAITING..."
        return "BULLISH 📈" if price > sma else "BEARISH 📉"
    
    def prepare_ai_features(self, df, set_count):
        if df is None or len(df) < 5: return None
        
        last_candle = df.iloc[-1]
        body_size = abs(last_candle['close'] - last_candle['open'])
        total_range = last_candle['high'] - last_candle['low']
        
        # Calculate Wick Ratio: If body is > 80% of the candle, it's MOMENTUM (Dangerous for Reversals)
        wick_ratio = body_size / total_range if total_range > 0 else 0
        
        features = {
            "set_level": set_count,
            "volatility": df['close'].pct_change().rolling(10).std().iloc[-1],
            "wick_ratio": wick_ratio, # New Improvement Feature
            "hour": datetime.now().hour
        }
        return pd.DataFrame([features])

# --- VISUALIZER ---
class Visualizer:
    def __init__(self, bridge, target_symbol):
        self.bridge = bridge 
        self.active_symbol = target_symbol
        self.current_tl_type = 1
        self.timeframe = self.bridge.current_tf
        self._need_redraw = True # Optimization flag

        # Setup Figure with dark theme
        self.fig = plt.figure(figsize=(12, 8), facecolor='#0d1117')
        self.ax = self.fig.add_axes([0.1, 0.15, 0.85, 0.7])
        self.ax_status = self.fig.add_axes([0.1, 0.88, 0.8, 0.08])
        
        # Button construction (Abstracted for brevity)
        self._setup_buttons()
        
        # Indicators
        self.set_label = self.ax.text(0.02, 0.91, "SET: 0", transform=self.ax.transAxes, 
                                     color='#FFFF00', fontweight='bold', zorder=5)
    def _setup_buttons(self):
        # Existing SET button
        self.ax_set = self.fig.add_axes([0.15, 0.04, 0.15, 0.06])
        self.btn_set = Button(self.ax_set, 'SET +1', color='#1f2937', hovercolor='#374151')
        self.btn_set.label.set_color('white')
        self.btn_set.on_clicked(lambda e: self._send_cmd("SET_INC"))

        # New CLEAR button (Positioned next to it, but in RED)
        self.ax_clear = self.fig.add_axes([0.32, 0.04, 0.15, 0.06])
        self.btn_clear = Button(self.ax_clear, 'CLEAR CHART', color='#4a0000', hovercolor='#8b0000')
        self.btn_clear.label.set_color('white')
        self.btn_clear.label.set_weight('bold')
        
        # This triggers the MQL5 ObjectsDeleteAll logic we discussed
        self.btn_clear.on_clicked(lambda e: self._send_cmd("CLEANUP"))

    def trigger_set(self, event):
        print(">>> PYTHON CLICKED: SET") # Check if this prints in your terminal
        self._send_cmd("SET_INC")

    def _send_cmd(self, cmd_text):
        # Reach into the bridge to get the path
        mt5_path = self.bridge.mt5_path 
        cmd_path = os.path.join(mt5_path, f"{self.active_symbol}_cmd.csv")
        
        try:
            # FIXED: Changed 'action' to 'cmd_text'
            with open(cmd_path, "w", encoding='utf-8') as f:
                f.write(cmd_text)
            
            # Debug print so you know the button click registered
            print(f">>> Command Sent: {cmd_text}")
            
        except Exception as e:
            # It's better to print the error than 'pass' so you know if 
            # there is a permission issue on your MacBook Air.
            print(f"DEBUG Error sending command: {e}")
            
    def trigger_tl(self, event):
        # 1. Identify the mode to send
        active_mode = self.current_tl_type
        
        # 2. Update Dashboard Label (Reflection Fix)
        if hasattr(self, 'tl_mode_text'):
            self.tl_mode_text.set_text(f"TL MODE: {active_mode}")
        
        # 3. Send the command that MT5 understands
        self._send_cmd(f"DRAW_TL_{active_mode}")
        
        # 4. Cycle mode for next click
        self.current_tl_type = (self.current_tl_type % 4) + 1
        
        # 5. UI Feedback
        event.inaxes.set_facecolor('#00FF00') # Visual 'Touch' sensitivity
        self.fig.canvas.draw_idle()
        plt.pause(0.05)
        event.inaxes.set_facecolor('#21262d')
        self.fig.canvas.draw_idle()

    def trigger_clear(self, event):
        """Sends CLEAR command and resets dashboard view"""
        self._send_cmd("CLEAR")
        
        # Immediate UI feedback
        event.inaxes.set_facecolor('#FF3131') # Flash Red
        self.fig.canvas.draw_idle()
        plt.pause(0.05)
        event.inaxes.set_facecolor('#21262d')
        self.fig.canvas.draw_idle()

    def update_dashboard_ui(self, online, tf, price):
            """Update the top status text without clearing the whole chart"""
            self.ax_status.clear()
            self.ax_status.set_axis_off()
            
            status_color = '#00FF00' if online else '#FF3131'
            status_text = "● MT5 ONLINE" if online else "○ MT5 OFFLINE"
            display_price = f"{price:.2f}" if isinstance(price, (int, float)) else "---"
            
            # Draw the Dashboard Info Box
            info = f"{status_text}  |  TF: {tf}  |  {self.active_symbol}: {display_price}"
            
            self.ax_status.text(0.5, 0.5, info, transform=self.ax_status.transAxes,
                            ha='center', va='center', color='white', 
                            fontsize=11, fontweight='bold', 
                            bbox=dict(facecolor='#161b22', alpha=0.9, edgecolor=status_color))
    
    def update_dashboard_labels(self, set_count, trend_direction):
        """Updates the on-chart text indicators based on MT5 Sync data."""
        try:
            # Update the Exhaustion text
            self.set_label.set_text(f"SET: {set_count}")
            
            # Logic for terminal awareness
            if hasattr(self, 'last_printed_set') and self.last_printed_set != set_count:
                print(f">>> [AI ENGINE] MT5 Exhaustion updated to: {set_count}")
                self.last_printed_set = set_count

            # Visual indicator for "High Exhaustion"
            try:
                # Check if set_label exists before trying to color it
                if hasattr(self, 'set_label'):
                    if set_count >= 7:
                        self.set_label.set_color('#FF3131') # Red for alert
                        self.set_label.set_weight('bold')
                    else:
                        self.set_label.set_color('#00FF00') # Green for safe
                        self.set_label.set_weight('normal')
            except:
                pass

        except Exception as e:
            print(f"Dashboard Update Error: {e}")
 
    def send_mt5_cmd(self, action):
        cmd_file = os.path.join(self.mt5_path, f"{self.active_symbol}_cmd.csv")
        try:
            with open(cmd_file, "w") as f:
                f.write(f"CMD,{action}")
        except Exception as e:
            print(f"Error sending command: {e}")

    # Inside your Visualizer class, usually in the function passed to FuncAnimation

    def update_chart(self, df, price, is_connected, tf="M1", ai_status="Learning"):
        # 1. Protection against empty data
        if df is None or df.empty:
            self._update_overlay(price, is_connected, 0, tf, ai_status)
            self.fig.canvas.draw_idle()
            return

        # --- GET SYNC DATA FOR ALERT ---
        sync_data = self.bridge.get_sync_data()
        set_count = sync_data.get('set_count', 0)
        
        # --- SET 7 ALERT: BACKGROUND COLOR CHANGE ONLY ---
        # If set is 7, we use a deep red background, otherwise your original #0d1117
        bg_color = '#2e0000' if set_count >= 7 else '#0d1117'
        
        self.ax.clear()
        self.ax.set_facecolor(bg_color)
        self.fig.patch.set_facecolor(bg_color) # Also update the figure border
        
        # 2. Setup colors and plot (Your original logic)
        mc = mpf.make_marketcolors(up='#00FF00', down='#FF3131', inherit=True)
        s  = mpf.make_mpf_style(marketcolors=mc, facecolor=bg_color, gridcolor='#1f2937')
        
        # 3. Dynamic Plotting (Your original logic)
        plot_kwargs = dict(type='candle', ax=self.ax, style=s)
        
        if sync_data.get('trendlines'):
            plot_kwargs['alines'] = dict(alines=sync_data['trendlines'], colors='#00FFFF', linewidths=0.5)

        mpf.plot(df, **plot_kwargs)

        # 4. Update the Text Labels (Your original logic)
        self._update_overlay(price, is_connected, set_count, tf, ai_status)
        
        # --- VOICE ALERT (Optional, runs in background) ---
        if set_count >= 7:
            if not hasattr(self, '_last_voice') or (time.time() - self._last_voice > 60):
                os.system(f'say "Set {set_count} alert" &')
                self._last_voice = time.time()

        self.fig.canvas.draw_idle()

        # --- NEW LOGIC: AUTO-SCREENSHOT ON SET 7 ---
        if set_count >= 7:
            # Create folder if it doesn't exist
            if not os.path.exists('trade_logs'):
                os.makedirs('trade_logs')
            
            # Save if we haven't saved this specific minute yet
            current_min = datetime.now().strftime("%Y%m%d_%H%M")
            screenshot_path = f"trade_logs/Set7_{self.symbol}_{current_min}.png"
            
            if not os.path.exists(screenshot_path):
                self.fig.savefig(screenshot_path, facecolor=self.fig.get_facecolor())
                print(f">>> Logged Set 7 screenshot: {screenshot_path}")
    
    def _update_overlay(self, price, is_connected, set_count, tf, ai_status):
        for txt in self.ax.texts:
            txt.remove()
    
        # Clear previous text if you are using text objects, or just draw fresh
        # Use lime for AI active, orange for learning
        ai_color = "lime" if ai_status.lower() == "active" else "orange"
        
        # Determine Color for Set Count
        set_color = "yellow" if set_count < 7 else "#FF0000" # Red if 7
        
        # Example position for Set Count
        self.ax.text(0.5, 0.95, f"SET: {set_count}", color=set_color, 
                     transform=self.ax.transAxes, fontweight='bold', ha='center',
                     bbox=dict(facecolor='black', alpha=0.5))

        # Define Colors
        conn_color = "#00FF00" if is_connected else "#FF3131"
        status_color = "#00FF00" if ai_status == "Active" else "#FFA500" # Green vs Orange
        
        # 1. Top Left: AI Status & TF Display
        # This uses the 'tf' variable we just passed from the bridge
        self.ax.text(0.02, 0.95, f"AI: {ai_status} | {tf}", transform=self.ax.transAxes, 
                     color=status_color, fontsize=10, fontweight='bold', verticalalignment='top')

        # 2. Top Right: Connection & Set Count
        self.ax.text(0.98, 0.95, f"SET: {set_count} | {'CONNECTED' if is_connected else 'DISCONNECTED'}", 
                     transform=self.ax.transAxes, color=conn_color, fontsize=9, 
                     horizontalalignment='right', verticalalignment='top')

        # 3. Center Right: Large Price Display
        # In _update_overlay, find the Large Price Display section:
        display_text = f"{price:.2f}" if (price and price > 0) else "WAITING..."
        
        self.ax.text(0.98, 0.85, display_text, transform=self.ax.transAxes,
                     color='#FFFFFF', fontsize=20, fontweight='bold',
                     horizontalalignment='right', alpha=0.8)
        
def get_ai_confirmation(df):
    # Calculate ATR (Volatility)
    df['ATR'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
    
    current_candle_size = abs(df['high'].iloc[-1] - df['low'].iloc[-1])
    avg_volatility = df['ATR'].iloc[-1]
    
    # IMPROVEMENT: Only allow trades if the candle is "Significant" (1.5x larger than average)
    if current_candle_size > (avg_volatility * 1.5):
        return True # AI Confirms high-momentum reversal
    return False

def evaluate_entry_proposal(current_data):
    score = 0
    
    # 1. Check Set Exhaustion (The "7 Sets" Rule)
    if current_data['current_set'] >= 7:
        score += 2  # High probability of reversal
        
    # 2. Check Multi-Timeframe (MTF) Confirmation
    if current_data['h1_trend'] == current_data['m5_trend']:
        score += 3  # Trend alignment is king
        
    # 3. Check Distance from Breakeven (The "Snap-back")
    dist_to_be = current_data['price'] - current_data['be_line']
    if abs(dist_to_be) > threshold:
        score += 1 

    return "STRONG_BUY" if score > 5 else "WAIT"

# ... (Keep your imports exactly as they are) ...

# --- NEW: INITIALIZE AI MODEL ONCE AT STARTUP ---
# Load history from the directory defined in your config
# ... Keep all your imports as they are ...

# 1. REMOVE these lines from the top level (they are causing the crash):
# data = pd.read_csv('MT5_Set_History.csv') <--- DELETE THIS
# X = data[features]                     <--- DELETE THIS
# ... etc ...

# 2. ADD this function to handle AI setup using your config path:
def initialize_ai(mt5_path):
    history_file = os.path.join(mt5_path, 'MT5_Set_History.csv')
    if not os.path.exists(history_file):
        print(f"Warning: {history_file} not found. AI score will be disabled.")
        return None
    
    data = pd.read_csv(history_file)
    features = ['set_magnitude', 'bars_duration', 'hour_of_day', 'rsi_value', 'dist_from_be']
    
    # Ensure columns exist before training
    if all(col in data.columns for col in features):
        X = data[features]
        y = data['success_label']
        model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1)
        model.fit(X, y)
        return model
    return None

# ... (Your imports remain the same) ...

# 1. DEFINE THE AI TRAINER (Move logic into a function)
def train_ai_model(mt5_path):
    history_file = os.path.join(mt5_path, 'MT5_Set_History.csv')
    
    # --- AUTO-SEED LOGIC: Create history if missing so AI can start ---
    if not os.path.exists(history_file) or os.path.getsize(history_file) < 10:
        with open(history_file, 'w') as f:
            f.write("set_magnitude,bars_duration,hour_of_day,dist_from_be,success_label\n")
            f.write("7,10,12,0.5,1\n") # Fake Win
            f.write("3,5,14,0.1,0\n")  # Fake Loss
        print(">>> AI Engine: Seeded initial memory.")

    try:
        with open(history_file, 'rb') as f:
            content = f.read().replace(b'\x00', b'').decode('utf-8', errors='ignore')
        
        from io import StringIO
        data = pd.read_csv(StringIO(content))
        
        # Define the exact features your MT5 sends
        features = ['set_magnitude', 'bars_duration', 'hour_of_day', 'dist_from_be']
        
        # Convert and Train
        for col in features + ['success_label']:
            data[col] = pd.to_numeric(data[col], errors='coerce')
        
        data = data.dropna()

        if len(data) >= 2:
            X = data[features]
            y = data['success_label']
            model = XGBClassifier(n_estimators=50, max_depth=3, learning_rate=0.1)
            model.fit(X, y)
            print(">>> AI Engine: ACTIVE")
            return model
    except Exception as e:
        print(f">>> AI Training Error: {e}")
    return None

def main():
    config = ConfigLoader.load()
    
    # IMPROVED: Dynamic Debug Message
    symbol = config.get('active_symbol', 'XAUUSD')
    mt5_path = config.get('mt5_path', '')
    
    # This now reflects the actual folder being watched
    print(f"DEBUG: Monitoring MT5 Path: {mt5_path}")
    print(f"DEBUG: Active Symbol: {symbol}")
    
    # Initialize Bridge and Visualizer
    bridge = TradingBridge(config)
    viz = Visualizer(bridge, symbol)
    
    # 1. TRAIN AI (Using your modular function)
    ai_model = train_ai_model(mt5_path)

    heartbeat = Heartbeat(config)
    
    plt.show(block=False)

    try:
        while plt.fignum_exists(viz.fig.number):
            heartbeat.pulse()
            connected = bridge.is_connected()
            sync_data = bridge.get_sync_data()

            # --- FIX: GET PRICE AND TF SAFELY ---
            raw_price, tf = bridge.get_price_and_tf()
            
            # If bridge returns None, use a fallback so the dashboard doesn't crash
            price = raw_price if raw_price is not None else 0.0
            
            # --- 1. GET LIVE TF AND PRICE ---
            price, tf = bridge.get_price_and_tf()
            
            # --- 2. DETERMINE AI STATUS ---
            current_status = "Active" if ai_model is not None else "Learning"

            # --- 3. AI SCORING LOGIC (Safely contained) ---
            if ai_model is not None and bridge.has_new_data():
                try:
                    df = bridge.get_history_df()
                    if df is not None:
                        current_set = sync_data.get('set_count', 0)
                        
                        live_data = pd.DataFrame([{
                            'set_magnitude': float(current_set), 
                            'bars_duration': float(len(df)),
                            'hour_of_day': float(datetime.now().hour),
                            'dist_from_be': 0.0   
                        }])
                        
                        # Prob and direction logic
                        prob = ai_model.predict_proba(live_data)[0][1] * 100
                        direction = 1 if current_set > 0 else 0
                        
                        score_file = os.path.join(mt5_path, "ai_score.txt")
                        with open(score_file, 'w') as f:
                            f.write(f"{prob:.2f},{direction}")
                except:
                    current_status = "AI Error"

            # --- THE CLEAN CALL ---
            price, tf = bridge.get_price_and_tf()
            current_status = "Active" if ai_model is not None else "Learning"
            
            # Use explicit keyword arguments for safety
            viz.update_chart(
                df=bridge.get_history_df(), 
                price=price, 
                is_connected=connected, 
                tf=tf, 
                ai_status=current_status
            )
            
            plt.pause(0.1)

    except Exception as e:
        print(f"\n>>> SYSTEM ERROR: {e}")
    finally:
        plt.close('all')

if __name__ == "__main__":
    main()
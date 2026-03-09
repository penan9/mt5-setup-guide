from logging import config
import os
import time
import json
import sys
from datetime import datetime, timezone
import pandas as pd
import mplfinance as mpf
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
import warnings
warnings.filterwarnings("ignore", category=UserWarning)

# macOS Stability Backend
matplotlib.use('TkAgg') 

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
            # --- FIXED: MUST INITIALIZE THESE ---
            self.current_tf = "M1" 
            self.hist_path = os.path.join(self.mt5_path, f"{self.symbol}_{self.current_tf}_history.csv")
            self._last_mtime = 0
            self._start_time = time.time()

    def is_connected(self):
        """Watchdog: Checks if MT5 is updating the price file."""
        try:
            if not os.path.exists(self.price_path):
                return (time.time() - self._start_time) < 5 # 5s grace period
            
            mtime = os.path.getmtime(self.price_path)
            return (time.time() - mtime) < 30
        except:
            return False

    def has_new_data(self):
            """FIXED: Added missing method"""
            try:
                if not os.path.exists(self.price_path): return False
                mtime = os.path.getmtime(self.price_path)
                if mtime > self._last_mtime:
                    self._last_mtime = mtime
                    return True
                return False
            except: return False

    def get_sync_data(self):
            """Reads the sync file and returns a dictionary for the AI."""
            sync_file = os.path.join(self.mt5_path, f"{self.symbol}_sync.csv")
            data = {"set_count": 0, "trendlines": []}
            if os.path.exists(sync_file):
                try:
                    df_sync = pd.read_csv(sync_file, header=None)
                    for _, row in df_sync.iterrows():
                        if row[0] == "SET":
                            data["set_count"] = int(row[1])
                        elif row[0] == "TL" and len(row) >= 6:
                            data["trendlines"].append([
                                (pd.to_datetime(int(row[2]), unit='s'), float(row[3])),
                                (pd.to_datetime(int(row[4]), unit='s'), float(row[5]))
                            ])
                except: pass
            return data

    def get_price_and_tf(self):
        try:
            with open(self.price_path, "r") as f:
                content = f.read().strip().split("|")
                price = float(content[0])
                if len(content) > 1:
                    # Content is already 'M1', no need to replace "PERIOD_"
                    new_tf = content[1] 
                    
                    if new_tf != self.current_tf:
                        self.current_tf = new_tf
                        # Matches your screenshot: XAUUSD_M1_history.csv
                        self.hist_path = os.path.join(self.mt5_path, f"{self.symbol}_{self.current_tf}_history.csv")
                return price, self.current_tf
        except: return None, self.current_tf

    def get_history_df(self):
        try:
            if os.path.exists(self.hist_path):
                # 1. Read the file (MT5 uses Tabs)
                df = pd.read_csv(self.hist_path, sep='\t')
                
                # 2. Clean headers to lowercase
                df.columns = [c.strip().lower() for c in df.columns]
                
                # 3. CONVERT TIME TO DATETIME INDEX (The Fix)
                if 'time' in df.columns:
                    # Convert Unix seconds to real dates
                    df['time'] = pd.to_datetime(df['time'], unit='s')
                    # Set it as the index so mplfinance can see it
                    df.set_index('time', inplace=True)
                
                # 4. Ensure price columns are numbers
                cols_to_fix = ['open', 'high', 'low', 'close']
                for col in cols_to_fix:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                # Drop any rows that failed to convert
                df.dropna(subset=['close'], inplace=True)
                
                return df
            return None
        except Exception as e:
            print(f"Read Error: {e}")
            return None
        
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

# --- VISUALIZER ---
# --- VISUALIZER ---
class Visualizer:
    def __init__(self, bridge, target_symbol):
        # 1. Assign the bridge and symbol
        self.bridge = bridge 
        self.active_symbol = target_symbol
        
        # Pull necessary paths/config from the bridge or global config
        self.mt5_path = bridge.mt5_path
        self.timeframe = "M15" # Default starting TF
        self.last_printed_set = -1
        self.last_chart_update = 0

        # 2. Setup Figure and Axes
        # Use a dark theme for the "AI" look
        self.fig, self.ax = plt.subplots(figsize=(12, 8))
        self.fig.patch.set_facecolor('#0d1117')
        
        # Define Status Bar (Top)
        self.ax_status = self.fig.add_axes([0.1, 0.88, 0.8, 0.08])
        self.ax_status.set_axis_off()
        
        # Define Button Axes (Bottom)
        self.ax_set = self.fig.add_axes([0.15, 0.04, 0.2, 0.06])
        self.ax_tl  = self.fig.add_axes([0.40, 0.04, 0.2, 0.06])
        self.ax_clr = self.fig.add_axes([0.65, 0.04, 0.2, 0.06])
        
        # 3. Create Buttons
        self.btn_set = Button(self.ax_set, 'SET EXHAUSTION', color='#1f2937', hovercolor='#374151')
        self.btn_tl  = Button(self.ax_tl, 'DRAW TREND', color='#1f2937', hovercolor='#374151')
        self.btn_clr = Button(self.ax_clr, 'CLEAR ALL', color='#991b1b', hovercolor='#b91c1c')
        
        # 4. Attach Click Events
        self.btn_set.on_clicked(self.trigger_set)
        self.btn_tl.on_clicked(self.trigger_tl)
        self.btn_clr.on_clicked(self.trigger_clear)
        
        # Style buttons
        for b in [self.btn_set, self.btn_tl, self.btn_clr]:
            b.label.set_color('white')
            b.label.set_weight('bold')

        # Create the exhaustion label on the main chart
        self.set_label = self.ax.text(0.02, 0.91, "SET: 0", transform=self.ax.transAxes, 
                                     color='#FFFF00', fontweight='bold', fontsize=11)

        plt.show(block=False)
        plt.pause(0.5)

    def trigger_set(self, event):
        print(">>> PYTHON CLICKED: SET") # Check if this prints in your terminal
        self._send_cmd("SET_INC")

    def _send_cmd(self, action):
        cmd_path = os.path.join(self.mt5_path, f"{self.active_symbol}_cmd.csv")
        try:
            # Use utf-8 to ensure no extra spaces/nulls are added

            with open(cmd_path, "w", encoding='utf-8') as f:
                f.write(action)

            print(f">>> SIGNAL SENT: {action}")
        except Exception as e:
            print(f"Command Error: {e}")
            
    def trigger_tl(self, event):
        self._send_cmd("DRAW_TL")

    def trigger_clear(self, event):
        self._send_cmd("CLEAR")

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

    def update_chart(self, df_input, current_price, is_connected):
        # 1. Clear Axis & Setup Background (DO THIS ONCE)
        self.ax.clear()
        self.ax_status.clear()
        self.ax.set_facecolor('#0d1117')
        self.ax_status.set_axis_off()
        
        # 2. DATA VALIDATION
        if df_input is None or df_input.empty:
            self.ax.text(0.5, 0.5, "AWAITING MARKET DATA...", transform=self.ax.transAxes, 
                         ha='center', va='center', color='white')
            self.fig.canvas.draw()
            return 

        # 3. SYNC DATA FROM MT5 (Sets and Trendlines)
        sync_data = self.bridge.get_sync_data() 
        current_set = sync_data.get('set_count', 0)
        mt5_trendlines = sync_data.get('trendlines', [])
        display_price = f"{current_price:.2f}" if current_price is not None else "---"

        # 4. UPDATE TOP DASHBOARD STATUS BAR
        status_color = '#00FF00' if is_connected else '#FF3131'
        status_text = "● MT5 ONLINE" if is_connected else "○ MT5 OFFLINE"
        info = f"{status_text}  |  TF: {self.timeframe}  |  {self.active_symbol}: {display_price}"
        
        self.ax_status.text(0.5, 0.5, info, transform=self.ax_status.transAxes,
                           ha='center', va='center', color='white', 
                           fontsize=11, fontweight='bold', 
                           bbox=dict(facecolor='#161b22', alpha=0.9, edgecolor=status_color))

        # 5. PREPARE PLOT STYLE (Neon Green/Red)
        mc = mpf.make_marketcolors(up='#00FF00', down='#FF3131', edge='inherit', wick='inherit')
        bright_style = mpf.make_mpf_style(marketcolors=mc, base_mpf_style='charles', gridcolor='#1f2937')

        plot_kwargs = {
            'type': 'candle',
            'ax': self.ax,
            'style': bright_style,
            'update_width_config': dict(candle_linewidth=0.8)
        }
        
        if mt5_trendlines:
            plot_kwargs['alines'] = dict(alines=mt5_trendlines, colors='#00FFFF', linewidths=1.5, alpha=0.8)

        # 6. RENDER CHART AND OVERLAYS
        try:
            mpf.plot(df_input, **plot_kwargs)

            # TOP LEFT: Online Status (High)
            self.ax.text(0.02, 0.96, status_text, transform=self.ax.transAxes, 
                         color=status_color, fontweight='bold', fontsize=9)
            
            # TOP LEFT: Exhaustion Indicator (Lower - avoids overlap)
            # Added a bbox (background box) to ensure readability against candles
            self.ax.text(0.02, 0.88, f"EXHAUSTION: SET {current_set}", 
                         transform=self.ax.transAxes, color='#FFFF00', 
                         fontweight='bold', fontsize=11,
                         bbox=dict(facecolor='#0d1117', alpha=0.7, edgecolor='none'))
            
            # TOP RIGHT: Live Price
            if current_price:
                self.ax.set_title(f"LIVE: {display_price}", color='white', loc='right', fontsize=10)

        except Exception as e:
            print(f"\n[Plot Error] {e}")

        self.fig.canvas.draw_idle()

# --- MAIN ENGINE ---
def main():
    # 1. INITIALIZE CONFIG AND CORE MODULES
    config = ConfigLoader.load()
    mt5_path = config["mt5_path"]
    
    # Initialize the bridge using the correct class name from your code
    bridge = TradingBridge(config) 
    heartbeat = Heartbeat(config)
    strategy = StrategyModule(config)
    cmd = CommandCenter(config)
    
    print("\n>>> MASTER SYSTEM INITIALIZING...")
    print(f">>> TARGET SYMBOL: {config['active_symbol']}")
    print(f">>> MT5 PATH: {mt5_path}")

    # 2. WAIT FOR INITIAL DATA SYNC
    # Prevents the visualizer from starting before MT5 writes the first files
    timeout = 0
    while not os.path.exists(bridge.price_path) and timeout < 20:
        time.sleep(0.5)
        sys.stdout.write(f"\r>>> SYNCING WITH MT5 FILES ({timeout}/20)...")
        sys.stdout.flush()
        timeout += 1
    
    if not os.path.exists(bridge.price_path):
        print("\nCRITICAL: MT5 price file not found. Ensure EA 'test2' is running in MT5.")
        sys.exit(1)

    # 3. INITIALIZE VISUALIZER
    # We pass 'bridge' so the Visualizer can call bridge.get_sync_data()
    viz = Visualizer(bridge=bridge, target_symbol=config["active_symbol"])
    
    # Allow macOS to render the window frame
    plt.show(block=False)
    plt.pause(1.0) 

    df = None

    # 4. MAIN OPERATIONAL LOOP
    try:
        # Loop runs as long as the Matplotlib window is open
        while plt.fignum_exists(viz.fig.number):
            # A. Connection Pulse
            heartbeat.pulse()
            connected = bridge.is_connected()

            # B. Get Live Data
            price, current_tf = bridge.get_price_and_tf()
            current_tf = current_tf.replace("PERIOD_", "")

            # C. Handle Timeframe Switching
            if viz.timeframe != current_tf:
                print(f"\n>>> SWITCHING CHART TO: {current_tf}")
                viz.timeframe = current_tf
                df = None # Force history reload for new TF

            # D. Refresh Data Frame (Candles)
            if bridge.has_new_data() or df is None:
                new_df = bridge.get_history_df()
                if new_df is not None:
                    df = new_df

            # E. Render Chart and AI Sync
            if df is not None:
                live_price = price if connected else None
                
                # Update the dashboard (Exhaustion Sets, Trendlines, Candles)
                viz.update_chart(df, live_price, connected)
                
                # F. Calculate Strategy Trend
                trend = strategy.calculate_trend(live_price, df) if live_price else "OFFLINE"
                
                # G. ROBUST TERMINAL OUTPUT (The Fix for the 'f' error)
                if isinstance(live_price, (int, float)):
                    price_str = f"{live_price:<10.2f}"
                else:
                    price_str = "---       "

                sys.stdout.write(
                    f"\r[{current_tf}] PRICE: {price_str} | "
                    f"TREND: {trend:<12} | SYNC: {'OK' if connected else 'ERR'}"
                )
                sys.stdout.flush()

            # H. Maintain GUI Thread
            plt.pause(0.05) 

    except Exception as e:
        print(f"\n>>> SYSTEM ERROR: {e}")
        import traceback
        traceback.print_exc() 
    finally:
        print("\n>>> System Offline. Goodbye.")
        plt.close('all')
        sys.exit(0)

if __name__ == "__main__":
    main()
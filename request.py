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
                # FIXED: Added sep='\t' to handle the MT5 Tab format
                df = pd.read_csv(self.hist_path, sep='\t')
                
                # Cleanup headers
                df.columns = [c.strip().lower() for c in df.columns]
                
                if 'close' in df.columns:
                    df['close'] = pd.to_numeric(df['close'], errors='coerce')
                    return df
                else:
                    # This will now show the individual columns if it still fails
                    print(f"\n>>> DEBUG HEADERS: {list(df.columns)}")
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
class Visualizer:
    def __init__(self, bridge, target_symbol):
        # This creates the 'bridge' attribute that was missing
        self.bridge = bridge 
        self.active_symbol = target_symbol
        self.last_printed_set = -1

        # 1. Basic Setup
        self.mt5_path = config["mt5_path"]
        self.active_symbol = config["active_symbol"]
        self.timeframe = tf
        
        # 2. Define ALL Attributes before using them
        self.fig, self.ax = plt.subplots(figsize=(12, 8))
        self.fig.patch.set_facecolor('#0d1117')
        
        # Define the Status Bar axis FIRST
        self.ax_status = self.fig.add_axes([0.1, 0.88, 0.8, 0.08])
        self.ax_status.set_axis_off()
        
        # Define Button Axes
        self.ax_set = self.fig.add_axes([0.15, 0.04, 0.2, 0.06])
        self.ax_tl  = self.fig.add_axes([0.40, 0.04, 0.2, 0.06])
        self.ax_clr = self.fig.add_axes([0.65, 0.04, 0.2, 0.06])
        
        # 3. Create Buttons
        self.btn_set = Button(self.ax_set, 'SET EXHAUSTION', color='#1f2937', hovercolor='#374151')
        self.btn_tl  = Button(self.ax_tl, 'DRAW TREND', color='#1f2937', hovercolor='#374151')
        self.btn_clr = Button(self.ax_clr, 'CLEAR ALL', color='#991b1b', hovercolor='#b91c1c')
        
        # 4. Attach Events
        self.btn_set.on_clicked(self.trigger_set)
        self.btn_tl.on_clicked(self.trigger_tl)
        self.btn_clr.on_clicked(self.trigger_clear)
        
        # Optional: Add formatting to buttons
        for b in [self.btn_set, self.btn_tl, self.btn_clr]:
            b.label.set_color('white')
            b.label.set_weight('bold')

        # Connect them to the class methods
        self.btn_set.on_clicked(self.trigger_set)
        self.btn_tl.on_clicked(self.trigger_tl)
        self.btn_clr.on_clicked(self.trigger_clear)

        # 3. Finalize Window handle
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
        status_text = "● ONLINE" if online else "○ OFFLINE"
        
        # Draw the Dashboard Info
        info = f"{status_text}  |  SYMBOL: {self.active_symbol}  |  TF: {tf}  |  LIVE: {price:.2f}"
        self.ax_status.text(0.5, 0.5, info, transform=self.ax_status.transAxes,
                           ha='center', va='center', color='white', 
                           fontsize=12, fontweight='bold', bbox=dict(facecolor='#161b22', alpha=0.8))
    
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
            if set_count >= 7:
                self.set_label.set_color('#FF4444') # Bright Red
                self.set_label.set_weight('bold')
            else:
                self.set_label.set_color('#00FF00') # Neon Green
                self.set_label.set_weight('normal')

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
        # 1. Get latest data from the bridge
        sync_data = self.bridge.get_sync_data() 
        
        # 2. Extract the values we need
        current_set = sync_data.get('set_count', 0)
        current_trend = "BULLISH" if self.price_up else "BEARISH"

        # 3. CALL THE UPDATE HERE
        self.update_dashboard_labels(current_set, current_trend)
        
        # ... rest of your candle plotting logic ...

        # 1. Prepare DatetimeIndex
        if not isinstance(df_input.index, pd.DatetimeIndex):
            df_input.index = pd.to_datetime(df_input.index)

        self.ax.clear()
        
        if df_input is None or df_input.empty:
            self.ax.text(0.5, 0.5, "AWAITING MARKET DATA...", transform=self.ax.transAxes, 
                         ha='center', va='center', color='white')
            self.fig.canvas.draw()
            return

        # --- SYNC DATA FROM MT5 (Sets and Trendlines) ---
        sync_file = os.path.join(self.mt5_path, f"{self.active_symbol}_sync.csv")
        trendlines = []
        set_count_text = "SET: 0"
        display_price = f"{current_price:.2f}" if current_price is not None else "---"

        # --- UPDATE TOP STATUS BAR ---
        self.ax_status.clear()
        self.ax_status.set_axis_off()

        status_color = '#00FF00' if is_connected else '#FF3131'
        status_text = "● MT5 ONLINE" if is_connected else "○ MT5 OFFLINE"
        
        # New Dashboard Text with safety check
        info = f"{status_text}  |  TF: {self.timeframe}  |  {self.active_symbol}: {display_price}"
        
        self.ax_status.text(0.5, 0.5, info, transform=self.ax_status.transAxes,
                           ha='center', va='center', color='white', 
                           fontsize=11, fontweight='bold', 
                           bbox=dict(facecolor='#161b22', alpha=0.9, edgecolor=status_color))
        
        if os.path.exists(sync_file):
            try:
                sync_data = pd.read_csv(sync_file, header=None)
                for _, row in sync_data.iterrows():
                    if row[0] == "SET":
                        set_count_text = f"EXHAUSTION: SET {row[1]}"

                        # Inside your sync file processing loop
                    elif row[0] == "TL" and len(row) >= 6:
                        t1 = pd.to_datetime(int(row[2]), unit='s')
                        p1 = float(row[3])
                        t2 = pd.to_datetime(int(row[4]), unit='s')
                        p2 = float(row[5])                      
                        # NEW: AI awareness printout
                        print(f">>> AI RECEIVED MT5 TRENDLINE: Start({t1}, {p1}) End({t2}, {p2})")                     
                        trendlines.append([(t1, p1), (t2, p2)])

            except: pass 

        # --- CREATE BRIGHT NEON STYLE ---
        # Up: Lime Green (#00FF00), Down: Bright Neon Red (#FF3131)
        mc = mpf.make_marketcolors(
            up='#00FF00', 
            down='#FF3131', 
            edge='inherit', 
            wick='inherit', 
            volume='inherit'
        )
        
        # Creating a custom style that works specifically with your dark background
        bright_style = mpf.make_mpf_style(
            marketcolors=mc, 
            base_mpf_style='charles', 
            gridcolor='#1f2937' # Subtle dark grid
        )

        # --- DYNAMIC PLOTTING ARGUMENTS ---
        plot_kwargs = {
            'type': 'candle',
            'ax': self.ax,
            'style': bright_style, # Using the new bright style
            'update_width_config': dict(candle_linewidth=0.8) # Slightly thicker for visibility
        }
        
        if trendlines:
            # Using Cyan for trendlines to contrast with the Neon Red/Green
            plot_kwargs['alines'] = dict(alines=trendlines, colors='#00FFFF', linewidths=1.5, alpha=0.8)

        # --- RENDER ---
        try:
            mpf.plot(df_input, **plot_kwargs)

            # UI Overlays
            status_color = '#00FF00' if is_connected else '#FF3131'
            self.ax.text(0.02, 0.96, f"{'● ONLINE' if is_connected else '○ OFFLINE'}", 
                         transform=self.ax.transAxes, color=status_color, fontweight='bold', fontsize=10)
            
            # Bright Yellow for your "Set" indicator
            self.ax.text(0.02, 0.91, set_count_text, transform=self.ax.transAxes, 
                         color='#FFFF00', fontweight='bold', fontsize=11)
            
            if current_price:
                # White Gold text in the top right
                self.ax.set_title(f"LIVE: {display_price}", color='white', loc='right', fontsize=10)

        except Exception as e:
            print(f"\n[Plot Error] {e}")

        # Ensure background is consistently dark
        self.ax.set_facecolor('#0d1117')
        self.fig.canvas.draw()

# --- MAIN ENGINE ---
def main():

    # --- MAIN EXECUTION ---
    # 1. Initialize the Bridge first
    my_bridge = MT5Bridge(path=mt5_path) 

    # 2. Pass 'my_bridge' into the Visualizer
    # This is where the "connection" happens
    viz = Visualizer(bridge=my_bridge, target_symbol="BTCUSD") 

    # 3. Start the loop
    viz.run_loop()

    # 1. INITIALIZE CONFIG AND CORE MODULES
    config = ConfigLoader.load()
    cmd = CommandCenter(config)
    
    bridge = TradingBridge(config) 
    heartbeat = Heartbeat(config)
    
    # Logic Modules
    strategy = StrategyModule(config)
    
    print("\n>>> MASTER SYSTEM INITIALIZING...")
    print(f">>> TARGET SYMBOL: {config['active_symbol']}")

    # 2. WAIT FOR INITIAL DATA SYNC
    # Ensure MT5 has at least written the first price file
    while not os.path.exists(bridge.price_path):
        time.sleep(0.5)
        sys.stdout.write("\r>>> SYNCING WITH MT5 FILES...")
        sys.stdout.flush()
    
    # 3. INITIALIZE VISUALIZER
    price_init, tf_init = bridge.get_price_and_tf()
    # Now this matches the __init__ arguments exactly
    viz = Visualizer(config, tf_init, config["logic_settings"]["sma_period"], cmd)
    
    # Give the OS (especially macOS) a moment to register the window handle
    plt.show(block=False)
    plt.pause(1.0) 

    df = None

    # 4. MAIN OPERATIONAL LOOP
    try:
        # Check if the figure window is still open
        while plt.fignum_exists(viz.fig.number):
            # Maintain the connection pulse
            heartbeat.pulse()
            connected = bridge.is_connected()

            # GET LIVE DATA
            price, current_tf = bridge.get_price_and_tf()
            current_tf = current_tf.replace("PERIOD_", "")
            # -------------------------
            # HANDLE TIMEFRAME SWITCHING
            if viz.timeframe != current_tf:
                print(f"\n>>> SWITCHING CHART TO: {current_tf}")
                viz.timeframe = current_tf
                viz.last_chart_update = 0 
                df = None 

            # REFRESH DATA FRAME
            if bridge.has_new_data() or df is None:
                new_df = bridge.get_history_df()
                if new_df is not None:
                    df = new_df

            # RENDER CHART AND STATS
            if df is not None:
                live_price = price if connected else None
                
                # This calls your updated update_chart with Set/Trendline sync
                viz.update_chart(df, live_price, connected)
                
                # CALCULATE TREND & PRINT STATUS
                trend = strategy.calculate_trend(live_price, df) if live_price else "OFFLINE"
                
                sys.stdout.write(
                    f"\r[{current_tf}] PRICE: {live_price if live_price else '---':<10} | "
                    f"TREND: {trend:<12} | SYNC: {'OK' if connected else 'ERR'}"
                )
                sys.stdout.flush()

            # The pulse of the GUI. Essential for responsiveness.
            plt.pause(0.05) 

    except Exception as e:
        print(f"\n>>> SYSTEM ERROR: {e}")
        # Optional: import traceback; traceback.print_exc() 
    finally:
        print("\n>>> System Offline. Goodbye.")
        plt.close('all')
        sys.exit(0)

if __name__ == "__main__":
    main()
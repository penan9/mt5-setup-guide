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
        print("Link with MT5 - test2 version 1.0")

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
    def __init__(self, symbol, timeframe, sma_period, cmd_center):
        self.symbol, self.timeframe, self.sma_period = symbol, timeframe, sma_period
        self.cmd = cmd_center
        self.last_chart_update = 0
        
        # Use a specific figure number (e.g., 1) to make it easier to track
        self.fig = plt.figure(1, figsize=(12, 8))
        self.ax = self.fig.add_subplot(111)
        
        plt.subplots_adjust(bottom=0.25)
        plt.ion()

        # Force window title for easier identification
        self.fig.canvas.manager.set_window_title(f"GOLD MASTER ENGINE - {self.symbol}")

        # UI Buttons (Persistent)
        self.ax_trade = plt.axes([0.1, 0.05, 0.2, 0.075])
        self.ax_mode  = plt.axes([0.4, 0.05, 0.2, 0.075])
        self.ax_quit  = plt.axes([0.7, 0.05, 0.2, 0.075])

        self.btn_trade = Button(self.ax_trade, 'TOGGLE TRADE', color='#2c3e50', hovercolor='#2ecc71')
        self.btn_mode  = Button(self.ax_mode, 'CHANGE MODE', color='#2c3e50', hovercolor='#3498db')
        self.btn_quit  = Button(self.ax_quit, 'SHUTDOWN', color='#c0392b', hovercolor='#e74c3c')

        for btn in [self.btn_trade, self.btn_mode, self.btn_quit]:
            btn.label.set_color('#ecf0f1')
            btn.label.set_fontweight('bold')

        self.btn_trade.on_clicked(self._on_trade_click)
        self.btn_mode.on_clicked(self._on_mode_click)
        self.btn_quit.on_clicked(self._on_quit_click)

        self.status_text_obj = None

    def _on_trade_click(self, event): self.cmd.toggle_trading()
    def _on_mode_click(self, event): self.cmd.analysis_mode = "RSI" if self.cmd.analysis_mode == "SMA" else "SMA"
    def _on_quit_click(self, event): plt.close(self.fig)

    def update_chart(self, df_input, current_price, is_connected):
        now = time.time()
        
        # 1. RENDER CANDLESTICKS (Throttled for Performance)
        if now - self.last_chart_update > 1.0 and df_input is not None:
            self.ax.clear()
            df_plot = df_input.copy()
            
            if 'time' in df_plot.columns:
                df_plot['time'] = pd.to_datetime(df_plot['time'])
                df_plot.set_index('time', inplace=True)
            
            # Professional Dark Theme
            mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', inherit=True)
            s = mpf.make_mpf_style(base_mpl_style='dark_background', marketcolors=mc, gridstyle='--')
            
            # Strategy Overlay (SMA)
            sma = df_plot['close'].rolling(window=self.sma_period).mean()
            ap = mpf.make_addplot(sma, ax=self.ax, color='orange', width=1.2)
            
            # Execute Plot - Force ax assignment to prevent new window popup
            mpf.plot(df_plot, type='candle', ax=self.ax, addplot=ap, style=s)
            
            # Live Price Line
            if current_price: 
                self.ax.axhline(current_price, color='white', linestyle='--', alpha=0.5)
            
            self.ax.set_title(f"GOLD MASTER ENGINE | {self.symbol}", color='cyan', fontsize=12, pad=20)
            self.last_chart_update = now
            self.status_text_obj = None 

        # 2. INTEGRATED HUD LOGIC
        duration = self.cmd.get_state_duration()
        # Change these lines:
        sync_status = "ONLINE" if is_connected else "OFFLINE"
        sync_color = "lime" if is_connected else "red"
        
        hud_content = (
            f"--- SYSTEM STATUS ---\n"
            f"MT5 LINK : {sync_status}\n"
            f"STATE    : {'HUNTING' if self.cmd.trading_enabled else 'SCANNING'}\n"
            f"MODE     : {self.cmd.analysis_mode}\n"
            f"DURATION : {duration}\n"
            f"TIMEFRAME: {self.timeframe}"
        )

        # 3. RENDER CLEAN OVERLAY
        if self.status_text_obj: 
            self.status_text_obj.remove()
        
        self.status_text_obj = self.ax.text(0.02, 0.96, hud_content, transform=self.ax.transAxes, 
                                            color='white', fontsize=9, family='monospace',
                                            verticalalignment='top',
                                            bbox=dict(boxstyle='round,pad=0.5', 
                                                      facecolor='#000000', 
                                                      edgecolor=sync_color, 
                                                      alpha=0.7))

        # --- CRITICAL FIX FOR MAC: FORCE RENDER ---
        self.fig.canvas.draw_idle()   # Prepare the pixels
        self.fig.canvas.flush_events() # Push them to the screen
        plt.show(block=False)         # Ensure window stays visible

# --- MAIN ENGINE ---
def main():
    config = ConfigLoader.load()
    bridge = TradingBridge(config)
    heartbeat = Heartbeat(config)
    strategy = StrategyModule(config)
    cmd = CommandCenter(config)
    
    print("\n>>> MASTER SYSTEM INITIALIZING...")
    
    # 1. WAIT FOR SYNC
    while not os.path.exists(bridge.price_path):
        time.sleep(0.5)
        sys.stdout.write("\r>>> SYNCING WITH MT5...")
        sys.stdout.flush()

    # 2. START MATPLOTLIB PROPERLY
    plt.close('all') # Clear any ghost processes
    price, tf = bridge.get_price_and_tf()
    viz = Visualizer(config["active_symbol"], tf, config["logic_settings"]["sma_period"], cmd)
    
    plt.show(block=False)
    plt.pause(1.0) # Give Mac a full second to register the window

    df = None

    try:
        # Use a simple flag instead of fignum_exists for the loop start
        while plt.fignum_exists(viz.fig.number):
            heartbeat.pulse()
            connected = bridge.is_connected()

            # DATA PROCESSING
            price, current_tf = bridge.get_price_and_tf()
            
            if viz.timeframe != current_tf:
                print(f"\n>>> SWITCHING TO: {current_tf}")
                viz.timeframe = current_tf
                viz.last_chart_update = 0 
                df = None 

            if bridge.has_new_data() or df is None:
                new_df = bridge.get_history_df()
                if new_df is not None:
                    df = new_df

            if df is not None:
                live_price = price if connected else None
                viz.update_chart(df, live_price, connected)
                
                # LIVE PRINTING
                trend = strategy.calculate_trend(live_price, df) if live_price else "OFFLINE"
                sys.stdout.write(
                    f"\r[{current_tf}] PRICE: {live_price if live_price else '---':<10} | "
                    f"TREND: {trend:<12} | SYNC: {'OK' if connected else 'ERR'}"
                )
                sys.stdout.flush()

            # The pulse of the GUI. If this is too fast, the window "dies".
            plt.pause(0.05) 

    except Exception as e:
        print(f"\n>>> SYSTEM ERROR: {e}")
    finally:
        print("\n>>> System Offline. Goodbye.")
        plt.close('all')
        sys.exit(0)

if __name__ == "__main__":
    main()
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
        self.hist_path = os.path.join(self.mt5_path, f"{self.symbol}_history.csv")
        self.current_tf = "M1"
        self._last_mtime = 0

    def is_connected(self):
            """Watchdog: Checks if MT5 is actually writing new data."""
            try:
                if not os.path.exists(self.price_path): 
                    return False
                
                # Get the last time MT5 touched this file
                last_update = os.path.getmtime(self.price_path)
                current_time = time.time()
                
                # If the file hasn't been updated for more than 10 seconds, 
                # MT5 is likely OFF or frozen.
                if (current_time - last_update) > 10:
                    return False
                    
                return True
            except:
                return False

    def get_price_and_tf(self):
        try:
            with open(self.price_path, "r") as f:
                content = f.read().strip()
                if not content: return None, self.current_tf
                parts = content.split("|")
                price = float(parts[0])
                if len(parts) > 1: self.current_tf = parts[1]
                return price, self.current_tf
        except: return None, self.current_tf        

    def has_new_data(self):
        try:
            mtime = os.path.getmtime(self.price_path)
            if mtime > self._last_mtime:
                self._last_mtime = mtime
                return True
        except: return False
        return False

    def get_history_df(self):
        try: return pd.read_csv(self.hist_path)
        except: return None

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
        
        self.fig, self.ax = plt.subplots(figsize=(12, 8))
        plt.subplots_adjust(bottom=0.25)
        plt.ion()

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
        
        if now - self.last_chart_update > 1.0 and df_input is not None:
            self.ax.clear()
            df_plot = df_input.copy()
            if 'time' in df_plot.columns:
                df_plot['time'] = pd.to_datetime(df_plot['time'])
                df_plot.set_index('time', inplace=True)
            
            mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', inherit=True)
            s = mpf.make_mpf_style(base_mpl_style='dark_background', marketcolors=mc, gridstyle='--')
            
            sma = df_plot['close'].rolling(window=self.sma_period).mean()
            ap = mpf.make_addplot(sma, ax=self.ax, color='orange', width=1.2)
            mpf.plot(df_plot, type='candle', ax=self.ax, addplot=ap, style=s)
            
            if current_price: self.ax.axhline(current_price, color='white', linestyle='--', alpha=0.5)
            self.ax.set_title(f"{self.symbol} [{self.timeframe}] - CHEE WOOI'S ENGINE", color='cyan')
            self.last_chart_update = now
            self.status_text_obj = None 

        duration = self.cmd.get_state_duration()
        if not is_connected:
            status_text = "⚠️ CONNECTION LOST - CHECK MT5"
            color = "#ff0000"
        else:
            # --- CHEE WOOI'S CUSTOM STATUS LABELS ---
            state_name = "HUNTING" if self.cmd.trading_enabled else "SCANNING"
            status_text = f"SYSTEM {state_name}: {duration}"
            color = "lime" if self.cmd.trading_enabled else "#00bfff" # Deep Sky Blue for Scanning

        if self.status_text_obj: self.status_text_obj.remove()
        self.status_text_obj = self.ax.text(0.02, 0.95, status_text, transform=self.ax.transAxes, 
                                            color=color, fontweight='bold', fontsize=12,
                                            bbox=dict(facecolor='black', alpha=0.7, edgecolor=color))
        self.fig.canvas.draw_idle()

# --- MAIN ENGINE ---
def main():
    config = ConfigLoader.load()
    bridge = TradingBridge(config)
    heartbeat = Heartbeat(config)
    strategy = StrategyModule(config)
    cmd = CommandCenter(config)
    
    viz = Visualizer(config["active_symbol"], "M1", config["logic_settings"]["sma_period"], cmd)
    
    print("\n>>> MASTER SYSTEM INITIALIZING...")
    plt.show(block=False)
    
    df = None
    
    try:
        while plt.fignum_exists(viz.fig.number):
            # 1. Send heartbeat pulse to MT5
            heartbeat.pulse()

            # 2. SENSOR: Is MT5 still talking to us?
            connected = bridge.is_connected()

            # 3. Process Data
            if bridge.has_new_data() or df is None or not connected:
                price, tf = bridge.get_price_and_tf()
                new_df = bridge.get_history_df()
                
                if new_df is not None:
                    df = new_df

                if df is not None:
                    viz.timeframe = tf
                    # If disconnected, we force price to None to stop 'ghost' repainting
                    live_price = price if connected else None
                    
                    # 4. Update UI Window (Turns Red if connected is False)
                    viz.update_chart(df, live_price, connected)
                    
                    # 5. Update Terminal Output
                    trend = strategy.calculate_trend(live_price, df) if live_price else "OFFLINE"
                    state_label = "HUNTING" if cmd.trading_enabled else "SCANNING"
                    sync_status = "ONLINE ✅" if connected else "OFFLINE ❌"
                    
                    sys.stdout.write(
                        f"\r[{tf}] PRICE: {live_price if live_price else '---':<10} | "
                        f"TREND: {trend:<12} | "
                        f"STATE: {state_label:<9} | "
                        f"SYNC: {sync_status}"
                    )
                    sys.stdout.flush()

            plt.pause(0.05) 

    except Exception as e:
        print(f"\n>>> ERROR: {e}")
    finally:
        cmd.signal_mt5_shutdown()
        print("\n>>> System Offline. Goodbye Chee Wooi.")
        sys.exit(0)

if __name__ == "__main__":
    main()
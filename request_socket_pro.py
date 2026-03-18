
"""
request_socket_pro.py
Full upgrade version with:
- MT5 ↔ Python bidirectional socket
- streaming candles
- command return channel
- no file I/O
"""

import socket
import threading
import json
import pandas as pd
import time

class MT5Bridge:

    def __init__(self, host="127.0.0.1", port=9090):
        self.host = host
        self.port = port
        self.conn = None

        self.price = None
        self.tf = None
        self.history = []
        self.set_count = None

        self.connected = False

        self.lock = threading.Lock()

    def start(self):

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((self.host, self.port))
        server.listen(1)

        print("Waiting for MT5 connection...")

        self.conn, addr = server.accept()

        print("MT5 connected:", addr)

        self.connected = True

        threading.Thread(target=self.receive_loop, daemon=True).start()

    def receive_loop(self):

        while True:

            try:

                data = self.conn.recv(65536)

                if not data:
                    break

                msg = json.loads(data.decode())

                self.handle_message(msg)

            except Exception as e:
                print("Receive error:", e)

    def handle_message(self, msg):

        t = msg.get("type")

        with self.lock:

            if t == "price":
                self.price = msg["price"]
                self.tf = msg["tf"]

            elif t == "set":
                self.set_count = msg["value"]

            elif t == "candle":
                self.history.append(msg["data"])

                if len(self.history) > 500:
                    self.history.pop(0)

    def send_command(self, cmd, value=None):

        if not self.connected:
            return

        payload = {"cmd": cmd}

        if value is not None:
            payload["value"] = value

        try:
            self.conn.send((json.dumps(payload)+"\n").encode())
        except:
            pass

    def get_history_df(self):

        if not self.history:
            return None

        df = pd.DataFrame(self.history)

        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("time", inplace=True)

        return df


# -----------------------
# Example AI engine hook
# -----------------------

class StrategyEngine:

    def __init__(self, bridge):

        self.bridge = bridge

    def process(self):

        while True:

            if not self.bridge.connected:
                time.sleep(1)
                continue

            price = self.bridge.price
            df = self.bridge.get_history_df()

            if price is None or df is None:
                time.sleep(0.5)
                continue

            signal = self.simple_ai(df)

            if signal == "BUY":
                self.bridge.send_command("BUY")

            if signal == "SELL":
                self.bridge.send_command("SELL")

            time.sleep(1)

    def simple_ai(self, df):

        if len(df) < 20:
            return None

        ma_fast = df["close"].rolling(5).mean().iloc[-1]
        ma_slow = df["close"].rolling(20).mean().iloc[-1]

        if ma_fast > ma_slow:
            return "BUY"

        if ma_fast < ma_slow:
            return "SELL"

        return None


if __name__ == "__main__":

    bridge = MT5Bridge()

    threading.Thread(target=bridge.start, daemon=True).start()

    engine = StrategyEngine(bridge)

    engine.process()

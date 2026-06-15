#!/usr/bin/env python3
"""
HUT Engineering Menu Toggle
============================
Activates/deactivates the Engineering (EOL) menu on GWM HUT
via CAN bus using Level 01 SecurityAccess + WriteDID F1C2.

Based on UDS protocol research and the SA L01 algorithm published at:
  https://github.com/DymOK93/GWM-CAN-Tools (MIT License)

Sequence:
  ON:  Extended Session → SA L01 unlock → WriteDID F1C2 = [01]
  OFF: Extended Session → SA L01 unlock → WriteDID F1C2 = [02]

Persistence: setting survives HUT reboot.

Usage:
  python3 hut_eng_menu.py --on       Enable engineering menu
  python3 hut_eng_menu.py --off      Disable engineering menu
  python3 hut_eng_menu.py --status   Read current state of F1C2

Requirements:
  - Raspberry Pi with MCP2515 on can0, 500kbps
  - Ignition must be ON
"""

import can
import time
import sys

HUT_TX = 0x773
HUT_RX = 0x7B3
POLY_L01 = 0x48205554
LFSR_ROUNDS = 35


def lfsr(seed: int, poly: int) -> int:
    k = seed & 0xFFFFFFFF
    if k != 0:
        for _ in range(LFSR_ROUNDS):
            msb = k & 0x80000000
            k = ((k << 1) & 0xFFFFFFFF)
            if msb:
                k ^= poly
    return k


class HutCan:
    def __init__(self):
        self.bus = can.Bus(channel="can0", interface="socketcan", bitrate=500000)

    def shutdown(self):
        self.bus.shutdown()

    def send(self, data):
        d = list(data)[:8] + [0xCC] * (8 - len(list(data)[:8]))
        self.bus.send(can.Message(
            arbitration_id=HUT_TX, data=d[:8], is_extended_id=False
        ))

    def send_isotp(self, payload):
        plen = len(payload)
        if plen <= 7:
            frame = [plen] + list(payload[:7])
            self.send(frame)
        else:
            ff = [0x10, plen] + list(payload[:6])
            self.send(ff)
            time.sleep(0.005)
            offset, seq = 6, 1
            while offset < plen:
                chunk = list(payload[offset:offset + 7])
                cf = [(0x20 | (seq & 0xF))] + chunk
                self.send(cf)
                offset += 7
                seq += 1
                time.sleep(0.005)

    def recv(self, timeout_val=5.0):
        t0 = time.time()
        pending = 0
        while time.time() - t0 < timeout_val and pending < 30:
            m = self.bus.recv(timeout=min(2.0, timeout_val - (time.time() - t0)))
            if not m or m.arbitration_id != HUT_RX:
                continue
            r = list(m.data)
            pci = (r[0] >> 4) & 0xF
            if pci == 0:
                sf_dl = r[0] & 0xF
                p = r[1:1 + sf_dl]
                if len(p) >= 3 and p[0] == 0x7F and p[2] == 0x78:
                    pending += 1
                    t0 = time.time()
                    continue
                return p
            elif pci == 1:
                tl = ((r[0] & 0xF) << 8) | r[1]
                res = r[2:8]
                self.send([0x30, 0x00, 0x00])
                while len(res) < tl:
                    cm = self.bus.recv(timeout=max(1.0, timeout_val - (time.time() - t0)))
                    if cm and cm.arbitration_id == HUT_RX and (cm.data[0] >> 4) & 0xF == 2:
                        res += list(cm.data)[1:min(8, 1 + tl - len(res))]
                    elif time.time() - t0 > timeout_val:
                        break
                return res[:tl]
        return None

    def drain(self):
        while self.bus.recv(timeout=0.3):
            pass

    def tester_present(self):
        self.send([0x02, 0x3E, 0x00])

    def enter_session(self, session_type):
        self.drain()
        self.send([0x02, 0x10, session_type])
        r = self.recv()
        return r is not None and len(r) >= 2 and r[0] == 0x50

    def request_seed_l01(self):
        self.send([0x02, 0x27, 0x01])
        r = self.recv()
        if r and r[0] == 0x67 and len(r) >= 6:
            seed = (r[2] << 24) | (r[3] << 16) | (r[4] << 8) | r[5]
            return seed
        return None

    def send_key_l01(self, key_val):
        kb = [
            (key_val >> 24) & 0xFF,
            (key_val >> 16) & 0xFF,
            (key_val >> 8) & 0xFF,
            key_val & 0xFF,
        ]
        self.send([0x06, 0x27, 0x02] + kb)
        r = self.recv()
        return r is not None and r[0] == 0x67

    def unlock_l01(self):
        if not self.enter_session(0x03):
            print("  Failed to enter Extended session")
            return False
        seed = self.request_seed_l01()
        if seed is None:
            print("  Failed to get SA L01 seed")
            return False
        print(f"  Seed: 0x{seed:08X}")
        key_val = lfsr(seed, POLY_L01)
        for _ in range(4):
            self.tester_present()
            time.sleep(2.0)
            self.bus.recv(timeout=0.5)
        if not self.send_key_l01(key_val):
            print(f"  SA L01 key rejected (key=0x{key_val:08X})")
            return False
        print(f"  SA L01 unlocked (key=0x{key_val:08X})")
        return True

    def write_did_f1c2(self, value):
        """Write DID F1C2. value=1 for ENG ON, value=2 for ENG OFF."""
        self.send([0x04, 0x2E, 0xF1, 0xC2, value])
        r = self.recv(15.0)
        if r and len(r) >= 3 and r[0] == 0x6E:
            return True
        if r and r[0] == 0x7F and len(r) > 2 and r[2] == 0x78:
            print("  Pending...")
            r2 = self.recv(10.0)
            return r2 is not None and r2[0] == 0x6E
        return False

    def read_did_f1c2(self):
        """Read current value of DID F1C2."""
        self.send_isotp([0x22, 0xF1, 0xC2])
        r = self.recv(5.0)
        if r and r[0] == 0x62 and len(r) >= 4:
            return r[3]
        return None


def eng_menu_on(hut):
    print("Enabling engineering menu (F1C2=[01])...")
    if not hut.unlock_l01():
        print("FAILED: Could not unlock SA L01")
        return False
    if hut.write_did_f1c2(0x01):
        print("SUCCESS: Engineering menu ENABLED")
        print("  Setting persists across HUT reboots.")
        return True
    else:
        print("FAILED: WriteDID F1C2=[01] rejected")
        return False


def eng_menu_off(hut):
    print("Disabling engineering menu (F1C2=[02])...")
    if not hut.unlock_l01():
        print("FAILED: Could not unlock SA L01")
        return False
    if hut.write_did_f1c2(0x02):
        print("SUCCESS: Engineering menu DISABLED")
        print("  Restart HUT to clear EOL indicator.")
        return True
    else:
        print("FAILED: WriteDID F1C2=[02] rejected")
        return False


def eng_menu_status(hut):
    print("Reading engineering menu status...")
    hut.enter_session(0x03)
    val = hut.read_did_f1c2()
    if val is None:
        # Try with SA unlocked
        if hut.unlock_l01():
            val = hut.read_did_f1c2()
    if val is not None:
        state = "ENABLED (ON)" if val == 0x01 else "DISABLED (OFF)" if val == 0x02 else f"UNKNOWN (0x{val:02X})"
        print(f"F1C2 = 0x{val:02X} → Engineering menu {state}")
        return val
    else:
        print("Could not read F1C2")
        return None


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    hut = HutCan()
    try:
        if "--on" in args:
            eng_menu_on(hut)
        elif "--off" in args:
            eng_menu_off(hut)
        elif "--status" in args:
            eng_menu_status(hut)
        else:
            print(__doc__)
    finally:
        hut.shutdown()


if __name__ == "__main__":
    main()

# GWM HUT Engineering Menu Toggle

Enables/disables the Engineering (EOL) menu on GWM Head Unit (HUT)
via CAN bus using SecurityAccess Level 01 + WriteDID F1C2.

Tested on Haval H9 Gen2 2024 (Desay SV HUT). The same SA L01 algorithm
is used across GWM vehicles with Harman HUT (Jolion, Tank) per
[DymOK93/GWM-CAN-Tools](https://github.com/DymOK93/GWM-CAN-Tools).

## Sequence

| Step | Command | Data | Description |
|------|---------|------|-------------|
| 1 | `10 03` | Extended Session | Enter extended diagnostic session |
| 2 | `27 01` → seed → `27 02 [4B key]` | SA L01 unlock | Seed-Key via LFSR35 |
| 3a | `2E F1 C2 01` | ENG MENU ON | Write 0x01 to enable |
| 3b | `2E F1 C2 02` | ENG MENU OFF | Write 0x02 to disable |

## Key Values

- `F1C2 = 0x01` → Engineering menu ENABLED (persists across reboots)
- `F1C2 = 0x02` → Engineering menu DISABLED (requires HUT restart)

## SA L01 Algorithm

```
poly = 0x48205554
key = LFSR35(seed, poly)  # 35 rounds, Galois LFSR, MSB-first
Key sent as SingleFrame: [06 27 02] + key[4 bytes]
```

Based on [DymOK93/GWM-CAN-Tools](https://github.com/DymOK93/GWM-CAN-Tools/blob/master/uds.py) (MIT License).

## Timing (observed)

- ~8s TesterPresent after Default Session before switching to Extended
- ~8s between seed request and key send (TesterPresent every 2s)
- ResponsePending (0x78) on WriteDID is normal; actual response follows in ~0.6s

## Verified Operations

| Operation | Result |
|-----------|--------|
| ENG ON (`F1C2=01`) | ✅ Confirmed, persists after reboot |
| ENG OFF (`F1C2=02`) | ✅ Confirmed, requires reboot |

## Usage

```bash
python3 hut_eng_menu.py --on       # Enable engineering menu
python3 hut_eng_menu.py --off      # Disable engineering menu
python3 hut_eng_menu.py --status   # Read current state of F1C2
```

### Requirements

- Raspberry Pi with MCP2515 on can0, 500kbps
- Ignition must be ON

## Files

| File | Purpose |
|------|---------|
| `hut_eng_menu.py` | Main script: --on / --off / --status |

## Disclaimer

- Intended solely for diagnostics of your own vehicle.
- SecurityAccess Level 01 is a standard UDS diagnostic service (ISO 14229-1),
  not an anti-theft or immobilizer bypass.
- Use at your own risk. Author is not responsible for any damage.

## License

MIT License. Seed-Key algorithm from [DymOK93/GWM-CAN-Tools](https://github.com/DymOK93/GWM-CAN-Tools) (MIT License).

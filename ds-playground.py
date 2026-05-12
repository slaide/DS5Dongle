#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pydualsense>=0.7"]
# ///
"""
DualSense playground over USB. Flags compose: set lightbar + a trigger + read state in one invocation.

Examples
  ./ds-playground.py --lightbar 255 0 128 --duration 5
  ./ds-playground.py --rumble 80 200 --duration 2
  ./ds-playground.py --trigger-right rigid 180 --duration 5
  ./ds-playground.py --trigger-right pulse-ab 4 5 200 --duration 5    # gun-trigger feel
  ./ds-playground.py --trigger-right pulse-ab 2 7 220 --duration 5    # wider, heavier "bow draw"
  ./ds-playground.py --mic-led on --player-leds 3 --duration 3
  ./ds-playground.py --read                 # stream input state until ctrl-c
  ./ds-playground.py --list-trigger-modes   # show what your pydualsense supports

Linux notes
  hidraw access usually needs a udev rule. For a one-off test:
    sudo chmod 666 /dev/hidraw*
  hid-playstation creates an evdev device but does not lock hidraw, so direct
  HID output reports still go through. Steam holding the pad exclusively can
  block access — quit Steam or disable Steam Input for the controller.
"""
import argparse
import sys
import time

from pydualsense import pydualsense, TriggerModes


TRIGGER_PRESETS = {
    # name -> (TriggerModes attr, list of setForce indices for the trailing args)
    "off":      ("Off",      []),
    "rigid":    ("Rigid",    [1]),
    "pulse":    ("Pulse",    [1]),
    "pulse-a":  ("Pulse_A",  [0, 1, 2]),
    "pulse-b":  ("Pulse_B",  [0, 1, 2]),
    "pulse-ab": ("Pulse_AB", [0, 1, 2]),
    "rigid-a":  ("Rigid_A",  [0, 1, 2]),
    "rigid-b":  ("Rigid_B",  [0, 1, 2]),
    "rigid-ab": ("Rigid_AB", [0, 1, 2]),
}


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument(
        "--lightbar", nargs=3, type=int, metavar=("R", "G", "B"),
        help="lightbar RGB, each 0..255 (0 0 0 = off).",
    )
    p.add_argument(
        "--player-leds", type=int, choices=range(6), metavar="N",
        help="player-number LEDs under the lightbar.\n"
             "  0 = all off\n"
             "  1..4 = controller number lit (PlayStation-style)\n"
             "  5 = all five lit",
    )
    p.add_argument(
        "--mic-led", choices=["on", "off"],
        help="microphone mute LED (the small orange LED above the mic).",
    )
    p.add_argument(
        "--rumble", nargs=2, type=int, metavar=("LEFT", "RIGHT"),
        help="classic ERM rumble. Two eccentric-mass motors, each 0..255 amplitude:\n"
             "  LEFT  = heavy/low-frequency motor in the left grip  (deep, bassy)\n"
             "  RIGHT = light/high-frequency motor in the right grip (buzzy, snappy)\n"
             "Examples:\n"
             "  80 200  → mild bass + strong buzz (think 'engine revving')\n"
             "  255 0   → pure bass thump\n"
             "  0 255   → pure high-frequency rattle\n"
             "Motors stay on for --duration, then reset to 0 on exit.",
    )
    p.add_argument(
        "--trigger-left", nargs="+", metavar="ARG",
        help="adaptive trigger effect for L2. Form: MODE [params...]\n"
             "see --trigger-right for the full mode/param reference.",
    )
    p.add_argument(
        "--trigger-right", nargs="+", metavar="ARG",
        help="adaptive trigger effect for R2. Form: MODE [params...].\n"
             "Parameter meaning is mode-specific. Positions are 0..9 along the\n"
             "trigger's travel (0 = released, 9 = fully pressed). Strengths\n"
             "are 0..255 amplitude bytes.\n"
             "\n"
             "  off                              no effect — trigger feels normal\n"
             "  rigid STRENGTH                   constant resistance through the whole pull.\n"
             "                                     STRENGTH 0..255. ~80 = noticeable,\n"
             "                                     ~180 = stiff, 255 = max.\n"
             "  pulse STRENGTH                   single pulse-resistance, fixed window.\n"
             "                                     try STRENGTH 150..255.\n"
             "  pulse-ab START END STRENGTH      gun-trigger / weapon feel — free pull until\n"
             "                                     position START, then heavy resistance until\n"
             "                                     position END, then breaks through and is\n"
             "                                     free again. START,END in 0..9 with END>START.\n"
             "                                     Narrow window (e.g. 4 5) = crisp gun click;\n"
             "                                     wide window (e.g. 2 7) = bow-draw feel.\n"
             "  rigid-ab  START END STRENGTH     same shape as pulse-ab but constant-resistance\n"
             "                                     instead of pulsed.\n"
             "  pulse-a   START END STRENGTH     pulse effect biased to one section; experiment.\n"
             "  pulse-b   START END STRENGTH     same family as pulse-a, different bias bits.\n"
             "  rigid-a / rigid-b                rigid variants of the above; experiment.\n"
             "\n"
             "See --list-trigger-modes for the underlying TriggerModes the script will use.",
    )
    p.add_argument(
        "--duration", type=float, default=2.0,
        help="seconds to hold the configured state before resetting (default 2).",
    )
    p.add_argument(
        "--read", action="store_true",
        help="stream input state at ~20 Hz until ctrl-c; overrides --duration.",
    )
    p.add_argument(
        "--list-trigger-modes", action="store_true",
        help="print TriggerModes enum members supported by your pydualsense build, then exit.",
    )
    return p.parse_args()


def apply_trigger(trigger, spec):
    name = spec[0].lower()
    if name not in TRIGGER_PRESETS:
        raise SystemExit(f"unknown trigger preset '{name}'. options: {', '.join(TRIGGER_PRESETS)}")
    attr, force_idxs = TRIGGER_PRESETS[name]
    if not hasattr(TriggerModes, attr):
        raise SystemExit(f"TriggerModes.{attr} not present in this pydualsense — try --list-trigger-modes")
    trigger.setMode(getattr(TriggerModes, attr))
    forces = [int(x) for x in spec[1:]]
    if len(forces) != len(force_idxs):
        raise SystemExit(f"'{name}' expects {len(force_idxs)} force value(s), got {len(forces)}")
    for idx, val in zip(force_idxs, forces):
        trigger.setForce(idx, max(0, min(255, val)))


def set_player_leds(ds, n):
    from pydualsense import PlayerID
    # enum names have varied across pydualsense versions; map defensively
    candidates = {
        0: ("OFF", "PLAYER_0"),
        1: ("PLAYER_1",),
        2: ("PLAYER_2",),
        3: ("PLAYER_3",),
        4: ("PLAYER_4",),
        5: ("ALL", "PLAYER_5"),
    }
    for attr in candidates[n]:
        if hasattr(PlayerID, attr):
            ds.light.setPlayerID(getattr(PlayerID, attr))
            return
    raise SystemExit(f"could not map --player-leds {n} to any PlayerID member; have: "
                     f"{[a for a in dir(PlayerID) if not a.startswith('_')]}")


def print_state(ds):
    s = ds.state
    b = getattr(ds, "battery", None)
    bat = f"{b.Level}% {b.State.name}" if b is not None else "?"
    tp0 = s.trackPadTouch0
    print(
        f"LS=({s.LX:+04d},{s.LY:+04d}) RS=({s.RX:+04d},{s.RY:+04d}) "
        f"L2={s.L2:3d} R2={s.R2:3d} | "
        f"X{int(s.cross)} O{int(s.circle)} Sq{int(s.square)} Tr{int(s.triangle)} "
        f"L1{int(s.L1)} R1{int(s.R1)} L3{int(s.L3)} R3{int(s.R3)} "
        f"Op{int(s.options)} Sh{int(s.share)} PS{int(s.ps)} "
        f"D({int(s.DpadUp)}{int(s.DpadRight)}{int(s.DpadDown)}{int(s.DpadLeft)}) | "
        f"gyro=({s.gyro.Pitch:+6d},{s.gyro.Yaw:+6d},{s.gyro.Roll:+6d}) "
        f"acc=({s.accelerometer.X:+6d},{s.accelerometer.Y:+6d},{s.accelerometer.Z:+6d}) | "
        f"tp=({getattr(tp0, 'X', '?')},{getattr(tp0, 'Y', '?')}) | "
        f"bat={bat}",
        flush=True,
    )


def main():
    args = parse_args()

    if args.list_trigger_modes:
        print("preset name -> TriggerModes member used by this script:")
        for k, (attr, idxs) in TRIGGER_PRESETS.items():
            present = hasattr(TriggerModes, attr)
            val = getattr(TriggerModes, attr, None)
            mark = "✓" if present else "✗"
            print(f"  {mark} {k:9s} -> TriggerModes.{attr:9s} = {int(val) if present else '-':>4}  forces:{idxs}")
        return

    ds = pydualsense()
    try:
        ds.init()
    except Exception as e:
        print(f"failed to open DualSense: {e}", file=sys.stderr)
        print("hint: USB-connected? udev permissions on /dev/hidraw*? Steam not holding it?", file=sys.stderr)
        sys.exit(1)

    try:
        if args.lightbar:
            ds.light.setColorI(*args.lightbar)
        if args.player_leds is not None:
            set_player_leds(ds, args.player_leds)
        if args.mic_led:
            ds.audio.setMicrophoneLED(args.mic_led == "on")
        if args.rumble:
            ds.setLeftMotor(args.rumble[0])
            ds.setRightMotor(args.rumble[1])
        if args.trigger_left:
            apply_trigger(ds.triggerL, args.trigger_left)
        if args.trigger_right:
            apply_trigger(ds.triggerR, args.trigger_right)

        if args.read:
            print("streaming state, ctrl-c to exit", file=sys.stderr)
            while True:
                print_state(ds)
                time.sleep(0.05)
        else:
            time.sleep(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            ds.setLeftMotor(0)
            ds.setRightMotor(0)
            ds.triggerL.setMode(TriggerModes.Off)
            ds.triggerR.setMode(TriggerModes.Off)
            ds.light.setColorI(0, 0, 0)
            try:
                ds.audio.setMicrophoneLED(False)
            except Exception:
                pass
            time.sleep(0.1)  # let the last output report flush before closing
        finally:
            ds.close()


if __name__ == "__main__":
    main()

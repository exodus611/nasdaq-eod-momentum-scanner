#!/usr/bin/env python3
"""DEPRECATED: the SAFE scanner logic (prob_safe/prob_big_drop + hard filters) is
merged into the new src/scan.py, which now outputs two tiers:

  * pre_move  — structural 'before the move' mask (uptrend, near 52w high, quiet day,
                no spike this week) ranked by the model probability;
  * momentum  — everything else ranked by probability.

The old version of this file fabricated dashboard statistics (hardcoded hit/gap values)
and could produce an empty scan — both fixed in scan.py.

Running this file simply runs the new scanner.
"""
import runpy
import os

print("[scan_safe] deprecated — running unified scanner src/scan.py")
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan.py"), run_name="__main__")

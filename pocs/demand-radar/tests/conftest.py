"""Make the demand-radar scripts importable as modules for unit tests.
They live one level up and aren't a package; add that dir to sys.path."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

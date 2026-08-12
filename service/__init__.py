"""The daily trial server shell (spec S1 in docs/specs/).

The package wires providers, reads and writes the trial store, and
serves the intake page. No scoring logic, no formula, and no cutoff
lives here (S1 R9) - the computation comes from core/ and pipeline/.
"""

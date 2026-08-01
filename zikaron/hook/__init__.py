"""The hook client: push injection and policy delivery, on a hard interpreter-startup budget.

Stdlib only, and not even all of stdlib: this package must not import `logging`, whose import
cost alone is comparable to the whole budget the service architecture exists to protect.
"""

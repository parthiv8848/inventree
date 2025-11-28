import threading

_local = threading.local()

def disable_invoice_sync():
    _local.skip_invoice = True

def enable_invoice_sync():
    _local.skip_invoice = False

def is_invoice_sync_disabled():
    return getattr(_local, "skip_invoice", False)

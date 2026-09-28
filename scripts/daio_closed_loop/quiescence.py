"""Read-only POSIX termination verification for a controller-owned process group.

The controller must create the process with start_new_session=True and retain
the actual Process handle, await it, and invoke this verifier. A PID alone or
an expired lease is insufficient. This module does not launch or kill anything.
"""
import os

from .handoff_contract import QuiescenceReceipt, identifier


def verify_process_group_exit(attempt_id, process, receipt_id):
    identifier(attempt_id)
    identifier(receipt_id)
    state = 'UNKNOWN'
    if os.name == 'posix' and isinstance(process.pid, int) and process.returncode is not None:
        try:
            # The leader has been reaped, but descendants may still exist.
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            state = 'TERMINATED'
        except PermissionError:
            pass
    return QuiescenceReceipt(attempt_id, state, receipt_id, 'PROCESS_GROUP_EXITED')

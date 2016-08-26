import socket
import sys
import os
from subprocess import call

os.chdir(os.environ['SPOTIFETCH_MODULE_DIR'])

lock_socket = None


def is_lock_free():
    global lock_socket
    lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        lock_id = "steinitzu.spotifetch-celery-worker"
        lock_socket.bind('\0' + lock_id)
        print 'Locked at: {}'.format(lock_id)
        return True
    except socket.error:
        print 'Socket is locked'
        # socket already locked, task must already be running
        return False

if not is_lock_free():
    sys.exit()

call(['celery', '-A', 'spotifetch.celery', 'worker'])

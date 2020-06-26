
import os
import logging
import time
import multiprocessing
import difflib
import threading
import hashlib
import shutil
import sys
import filecmp

from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler, FileModifiedEvent, \
    FileCreatedEvent, FileDeletedEvent, DirModifiedEvent, DirCreatedEvent, \
    DirDeletedEvent

from scandir import scandir

_files_home = 'files_home'
_trigger_event = '_trigger_event'
shared_state = {}

dir_cache = {}
vgrid_state_tracker = {}

blacklist = [
    "(^|\/)\."
]


def make_fake_event(path, state, is_directory=False):
    """Create a fake state change event for path. Looks up path to see if the
    change is a directory or file.
    """

    file_map = {'modified': FileModifiedEvent,
                'created': FileCreatedEvent,
                'deleted': FileDeletedEvent}
    dir_map = {'modified': DirModifiedEvent,
               'created': DirCreatedEvent, 'deleted': DirDeletedEvent}
    if is_directory or os.path.isdir(path):
        fake = dir_map[state](path)
    else:
        fake = file_map[state](path)

    # mark it a trigger event

    setattr(fake, _trigger_event, True)
    return fake


def get_file_sha(path):
    buffer_size = 65536

    sha = hashlib.sha1()
    with open(path, 'rb') as file:
        while True:
            data = file.read(buffer_size)
            if not data:
                break
            sha.update(data)
    return sha.hexdigest()


class FileTrackingEventHandler(PatternMatchingEventHandler):

    def __init__(
        self,
        patterns=None,
        ignore_patterns=None,
        ignore_directories=False,
        case_sensitive=False,
    ):
        PatternMatchingEventHandler.__init__(
            self,
            patterns,
            ignore_patterns,
            ignore_directories,
            case_sensitive
        )

    def track_state(self, event):
        logging.info("State tracking file: '%s'" % event.src_path)

        if event.is_directory:
            logging.info("Path '%s' is a directory, ignore this")
            return

        src_path = event.src_path
        if _files_home not in src_path:
            logging.info("Event is not in monitored directory, exiting state tracking")
            return

        base_path = src_path[src_path.index(_files_home) + len(_files_home) + 1:]
        logging.info("Got base path: '%s'" % base_path)

        path_dirs = base_path.split(os.path.sep)

        if len(path_dirs) < 2:
            logging.info("File is not within a VGrid, no tacking")
            return
        else:
            vgrid_name = path_dirs[0]
            file_name = path_dirs[-1]

            logging.info("Got VGrid name: '%s'" % vgrid_name)
            logging.info("Got file name: '%s'" % file_name)

        internal_path = base_path[base_path.index(vgrid_name) + len(vgrid_name) + 1:]

        logging.info("Got internal VGrid path: '%s'" % internal_path)

        current_sha = get_file_sha(src_path)

        logging.info("File '%s' has sha '%s'" % (file_name, current_sha))

        if vgrid_name not in vgrid_state_tracker:
            vgrid_state_tracker[vgrid_name] = {}

        if internal_path not in vgrid_state_tracker[vgrid_name]:
            logging.info("File '%s' encountered for the first time" % internal_path)

            revision = {
                'type': event.event_type,
                'time': event.time_stamp,
                'checksum': current_sha
            }
            vgrid_state_tracker[vgrid_name][internal_path] = {
                'checksum': current_sha,
                'revisions': [revision]
            }

        else:
            if vgrid_state_tracker[vgrid_name][internal_path]['checksum'] != current_sha:
                logging.info("File '%s' has been changed" % internal_path)
                vgrid_state_tracker[vgrid_name][internal_path]['checksum'] = current_sha

                revision = {
                    'type': event.event_type,
                    'time': event.time_stamp,
                    'checksum': current_sha
                }
                vgrid_state_tracker[vgrid_name][internal_path]['revisions'].append(revision)

            else:
                logging.info("File '%s' has not been changed" % internal_path)

    def run_handler(self, event):
        pid = multiprocessing.current_process().pid
        state = event.event_type
        src_path = event.src_path

        is_directory = event.is_directory

        logging.debug('(%s) got %s event for src_path: %s, directory: %s' % \
                    (pid, state, src_path, is_directory))
        # logger.debug('(%s) filter %s against %s' % (pid,
        #             all_rules.keys(), src_path))

        self.track_state(event)

    def handle_event(self, event):
        pid = multiprocessing.current_process().pid
        event.time_stamp = time.time()
        self.run_handler(event)

    def on_moved(self, event):
        for (change, path) in [('created', event.dest_path),
                               ('deleted', event.src_path)]:
            fake = make_fake_event(path, change, event.is_directory)
            self.handle_event(fake)

    def on_created(self, event):
        self.handle_event(event)

    def on_modified(self, event):
        self.handle_event(event)

    def on_deleted(self, event):
        self.handle_event(event)


if __name__ == '__main__':
    logging.basicConfig(
        filename='events.log',
        level=logging.DEBUG,
        format='%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logging.info('Starting new Log')

    path = os.path.join('.', _files_home)
    event_handler = FileTrackingEventHandler()
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()

    logging.info('Starting main loop')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info('KeyboardInterrupt, stopping observer')
        observer.stop()
    observer.join()

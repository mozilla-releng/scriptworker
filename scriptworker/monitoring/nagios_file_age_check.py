#!/usr/bin/env python

"""
Checks for the existence and age of specific files, and that they are not
too old.

Allow 'old' to be defined as warning and critical arguments. 

You can either:
- Specify one file to check
- Give the path to a file, that contains a newline-separated list
  of the files to check.

This script will produce a multi-line nagios report in either case.

"""
import os
import sys
import time
import argparse

# Nagios plugin exit codes
STATUS_CODE = {
    'OK': 0,
    'WARNING': 1,
    'CRITICAL': 2,
    'UNKNOWN': 3,
}

DEFAULT_WARNING = 45
DEFAULT_CRITICAL = 60


def file_age_check(filename, warning, critical, optional):
    """file_age_check

    Checks the age and existence of a given filename

    Arguments:
      - filename: a string, containing a full path
      - warning: integer, time in seconds over which to issue a warning.
      - critical: integer, time in seconds over which to issue critical.

    Returns:
      Tuple:
        - nagios status code from global STATUS_CODE
        - message string to be given to nagios
    """

    if not os.path.isfile(filename):
        if optional:
            return STATUS_CODE['OK'], "{0} doesn't exist and that's ok".format(filename)
        else:
            return STATUS_CODE['CRITICAL'], "{0} does not exist".format(filename)

    try:
        st = os.stat(filename)
    except OSError as excp:
        return STATUS_CODE['UNKNOWN'], "{0}: {1}".format(filename, excp)
    current_time = time.time()
    age = current_time - st.st_mtime

    if age >= critical:
        msg = "{0} is too old {1}/{2} seconds".format(
            filename, int(age), critical)
        return STATUS_CODE['CRITICAL'], msg
    elif age >= warning:
        msg = "{0} is getting too old {1}/{2} seconds".format(
            filename, int(age), warning)
        return STATUS_CODE['CRITICAL'], msg
    else:
        msg = "{0} is ok, {1}/{2} seconds old".format(
            filename, int(age), max_age)
        return STATUS_CODE['OK'], msg


def get_args():

    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument('-w', '--warning', type=int, default=DEFAULT_WARNING,
                      help='warn if files are older than this many minutes')
    argp.add_argument('-c', '--critical', type=int, default=DEFAULT_CRITICAL,
                      help='critical if files are older than this many minutes')

    argp.add_argument('-o', '--optional', action='store_true',
                      help="If set, do not report error if the file is missing")

    arggroup = argp.add_mutually_exclusive_group(required=True)

    arggroup.add_argument('-p', '--path', type=str,
                          help="The full path name to check")
    arggroup.add_argument('-f', '--from-file',
                          type=argparse.FileType('r'),
                          default=sys.stdin,
                          help="A file of paths to check, one per line, or - for stdin (default)")

    args = argp.parse_args()

    # convert to seconds for epoch time comparison
    args.warning = args.warning * 60
    args.critical = args.critical * 60

    return args


def run_file_age_checks():
    """run_file_age_checks
    Organise the file age checks for nagios

    Output:
    Prints to stdout
    Exits with appropriate return code"""

    args = get_args()

    statuses = list()
    messages = list()

    if args.path:
        check_files = [args.path]
    else:
        check_files = [f.strip() for f in args.from_file]

    for filename in check_files:
        status, message = file_age_check(
            filename, args.warning, args.critical, args.optional)
        statuses.append(status)
        messages.append(message)

    exit_code = max(statuses)

    reverse_status_codes = {v: k for k, v in STATUS_CODE.items()}
    service_output = "FILE_AGE {0}".format(reverse_status_codes[exit_code])

    service_output_options = {
        STATUS_CODE['OK']: "All files ok",
        STATUS_CODE['WARNING']: "Some files may be too old, see long output",
        STATUS_CODE['CRITICAL']: "Some files errored, see long output",
        STATUS_CODE['UNKNOWN']: "Unknown error",
    }

    service_output += " - {0}".format(service_output_options[exit_code])

    print("{0}\n{1}\n".format(service_output, "\n".join(sorted(messages))))
    sys.exit(exit_code)

if __name__ == '__main__':
    run_file_age_checks()

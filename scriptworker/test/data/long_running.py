#!/usr/bin/env python
# This script is here to test killing process groups from python.
#
# If this script is called with one argument, that argument is the
# tempdir, and we launch 2 additional instances of this script with three
# args each.
#
# With 3 args, we use those args as files to write gibberish to, so we're
# writing to 6 files total.
#
# On killing the main script, the files should stop changing.
import asyncio
import os
import subprocess
import sys
import time

BASH_SCRIPT = os.path.join(os.path.dirname(__file__), "write_file.sh")


def launch_second_instances():
    temp_dir = sys.argv[1]
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    job1 = subprocess.Popen(
        [sys.executable, __file__,
         os.path.join(temp_dir, "one"),
         os.path.join(temp_dir, "two"),
         os.path.join(temp_dir, "three")],
    )
    loop = asyncio.get_event_loop()
    job2 = asyncio.create_subprocess_exec(
        sys.executable,
        __file__,
        os.path.join(temp_dir, "four"),
        os.path.join(temp_dir, "five"),
        os.path.join(temp_dir, "six"),
    )
    loop.run_until_complete(job2)
    job1.wait()


async def write_file1(path):
    with open(path, "w") as fh:
        while True:
            print(time.time(), file=fh)
            await asyncio.sleep(.001)


def write_files():
    loop = asyncio.get_event_loop()
    tasks = [
        write_file1(sys.argv[1]),
    ]
    subprocess.Popen(['bash', BASH_SCRIPT, sys.argv[2]])
    subprocess.Popen("bash {} {}".format(BASH_SCRIPT, sys.argv[3]), shell=True)
    loop.run_until_complete(asyncio.wait(tasks))


def main():
    num_args = len(sys.argv)
    if num_args == 2:
        launch_second_instances()
    else:
        assert num_args == 4
        write_files()


if __name__ == '__main__':
    main()

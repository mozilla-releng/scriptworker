import json
import os
from setuptools import setup
from setuptools.command.test import test as TestCommand
import sys

reqs = [
    "aiohttp==0.22.0a0",
    "arrow==0.8.0",
    "defusedxml==0.4.1",
    "frozendict==0.6",
    "jsonschema==2.5.1",
    "taskcluster==0.3.4",
    "virtualenv==15.0.2",
]

tests_require = [
    "tox",
    "virtualenv",
]

PATH = os.path.join(os.path.dirname(__file__), "version.json")
with open(PATH) as filehandle:
    VERSION = json.load(filehandle)['version_string']


class Tox(TestCommand):
    """http://bit.ly/1T0dwvG
    """
    user_options = [('tox-args=', 'a', "Arguments to pass to tox")]

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.tox_args = None

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        # import here, cause outside the eggs aren't loaded
        import tox
        import shlex
        args = self.tox_args
        if args:
            args = shlex.split(self.tox_args)
        errno = tox.cmdline(args=args)
        sys.exit(errno)


setup(
    name="scriptworker",
    version=VERSION,
    description="TaskCluster Script Worker",
    author="Mozilla Release Engineering",
    author_email="release+python@mozilla.com",
    url="https://github.com/escapewindow/scriptworker",
    packages=["scriptworker"],
    package_data={"": ["version.json"]},
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "scriptworker = scriptworker.worker:main",
        ],
    },
    zip_safe=True,
    license="MPL 2.0",
    install_requires=reqs,
    tests_require=tests_require,
    cmdclass={'test': Tox},
    classifiers=(
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.5',
    ),
)

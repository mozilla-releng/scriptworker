from __future__ import print_function

import json
import os
import sys

from setuptools import setup
from setuptools.command.test import test as TestCommand

project_dir = os.path.abspath(os.path.dirname(__file__))

if {"register", "upload"}.intersection(set(sys.argv)):
    print(
        "                        ***** WARNING *****\n"
        "`python setup.py register` and `python setup.py upload` are unsafe!\n"
        "See http://scriptworker.readthedocs.io/en/latest/releases.html#pypi\n"
        "\n"
        "Exiting...",
        file=sys.stderr,
    )
    sys.exit(1)

tests_require = [
    "asyncio_extras",
    "flake8",
    "flake8_docstrings",
    "mock",
    "pytest",
    # doesn't support python 3.8
    "pytest-asyncio<1.0",
    "pytest-cov",
    "pytest-mock",
    "pytest-random-order",
    "tox",
    "virtualenv",
]

PATH = os.path.join(os.path.dirname(__file__), "version.json")
with open(PATH) as filehandle:
    VERSION = json.load(filehandle)["version_string"]

with open(os.path.join(os.path.abspath(os.path.dirname(__file__)), "requirements.txt")) as f:
    install_requires = f.readlines()

with open(os.path.join(project_dir, "README.rst")) as fh:
    long_description = fh.read()


class Tox(TestCommand):
    """http://bit.ly/1T0dwvG"""

    user_options = [("tox-args=", "a", "Arguments to pass to tox")]

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.tox_args = None

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        # import here, cause outside the eggs aren't loaded
        import shlex

        import tox

        args = self.tox_args
        if args:
            args = shlex.split(self.tox_args)
        errno = tox.cmdline(args=args)
        sys.exit(errno)


setup(
    name="scriptworker",
    version=VERSION,
    description="TaskCluster Script Worker",
    long_description=long_description,
    author="Mozilla Release Engineering",
    author_email="release+python@mozilla.com",
    url="https://github.com/mozilla-releng/scriptworker",
    packages=["scriptworker", "scriptworker.cot"],
    package_data={"": ["version.json"]},
    package_dir={"": "src"},
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "scriptworker = scriptworker.worker:main",
            "verify_cot = scriptworker.cot.verify:verify_cot_cmdln",
            "create_test_workdir = scriptworker.cot.verify:create_test_workdir",
            "verify_ed25519_signature = scriptworker.ed25519:verify_ed25519_signature_cmdln",
        ]
    },
    zip_safe=False,
    license="MPL 2.0",
    install_requires=install_requires,
    tests_require=tests_require,
    python_requires=">=3.7",
    cmdclass={"test": Tox},
    classifiers=(
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ),
)

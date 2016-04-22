from __future__ import absolute_import, division, print_function
from setuptools import setup

reqs = [
    "aiohttp",
    "defusedxml",
    "frozendict",
    "taskcluster",
]


setup(
    name="scriptworker",
    version="0.1",
    description="TaskCluster Script Worker",
    author="Mozilla Release Engineering",
    author_email="release+python@mozilla.com",
    url="https://github.com/escapewindow/scriptworker",
    packages=["scriptworker"],
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "scriptworker = scriptworker.worker:main",
        ],
    },
    zip_safe=True,
    license="MPL2",
    install_requires=reqs,
)

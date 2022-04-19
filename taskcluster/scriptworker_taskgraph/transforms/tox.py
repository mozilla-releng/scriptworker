# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Tox-specific transforms
"""

from copy import deepcopy

from taskgraph.transforms.base import TransformSequence

transforms = TransformSequence()


def _replace_string(obj, subs):
    if isinstance(obj, dict):
        return {k: v.format(**subs) for k, v in obj.items()}
    elif isinstance(obj, list):
        for c in range(0, len(obj)):
            obj[c] = obj[c].format(**subs)
    else:
        obj = obj.format(**subs)
    return obj


def _resolve_replace_string(item, field, subs):
    # largely from resolve_keyed_by
    container, subfield = item, field
    while "." in subfield:
        f, subfield = subfield.split(".", 1)
        if f not in container:
            return item
        container = container[f]
        if not isinstance(container, dict):
            return item

    if subfield not in container:
        return item

    container[subfield] = _replace_string(container[subfield], subs)
    return item


@transforms.add
def replace_strings(config, jobs):
    fields = [
        "description",
        "run.command",
        "worker.command",
        "worker.docker-image",
    ]
    for job in jobs:
        python_version = job.pop("python-version")
        targets = job.pop("targets")
        task = deepcopy(job)
        subs = {
            "name": job["name"],
            "python-version": python_version,
            "targets": targets,
        }
        for field in fields:
            _resolve_replace_string(task, field, subs)
        yield task


@transforms.add
def update_env(config, jobs):
    for job in jobs:
        env = job.pop("env", {})
        job["worker"].setdefault("env", {}).update(env)
        yield job


@transforms.add
def add_dependencies(config, jobs):
    """Explicitly add the docker-image task as a dependency.

    This needs to be done before the `cached_tasks` transform, so we can't
    wait until the `build_docker_worker_payload` transform.

    From `build_docker_worker_payload`.

    """
    for job in jobs:
        image = job["worker"]["docker-image"]
        if isinstance(image, dict):
            if "in-tree" in image:
                docker_image_task = "build-docker-image-" + image["in-tree"]
                job.setdefault("dependencies", {})["docker-image"] = docker_image_task
        yield job

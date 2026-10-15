#!/usr/bin/env python3
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""Multi-SWE-bench (Java) batch runner for mini-swe-agent.

A thin wrapper over ``minisweagent.run.benchmarks.swebench``: identical batch
loop, progress display, ``preds.json`` writing, resume-on-rerun and
``--redo-existing`` semantics.  Exactly two things differ, and both are about
the container:

1. **Image comes from the row.**  Multi-SWE-bench images are named
   ``mswebench/{org}_m_{repo}:pr-{number}`` (lower-cased), which
   ``helper_code/data_prepare/generate_msb_instances.py`` already writes into
   ``image_name``.  The stock runner only reads ``image_name`` when there is no
   ``dockerhub_tag``; that happens to be true here, but relying on a fallback is
   fragile, so this runner reads ``image_name`` directly and fails loudly when
   it is missing.

2. **cwd is per instance.**  Multi-SWE-bench images clone the repository to
   ``/home/{repo}`` and set ``WORKDIR /home/``.  Verified against every Java
   repo definition in ``multi_swe_bench/harness/repos/java/`` — all nine of the
   repos in our dataset use ``cd /home/{pr.repo}``.  The stock runner takes cwd
   from the benchmark config, and ``swebench_pro_hints.yaml`` hardcodes
   ``/app``, which does not exist in these images: the agent would start in an
   empty directory and see no code.  ``doc2feat.py`` overrides cwd per instance
   for the same reason; this mirrors it.

Wrapping instead of forking keeps upstream fixes to the shared batch loop — the
per-thread ``deepcopy`` of ``env_config`` (without it, instance A can start in
instance B's image once ``--workers > 1``) and the ``swerex_daytona`` branch —
without duplicating ~250 lines that would then drift.

Usage (there is no Docker on this host, so ``daytona.yaml`` goes last):

    mini-extra multi-swe-bench \\
        -c multi_swe_bench_hints.yaml \\
        -c openrouter_swebench_ds.yaml \\
        -c daytona.yaml \\
        --subset results/miniswe_java/sel40_nocode_java_declaration.jsonl \\
        --workers 20 \\
        --output ./output/msb_nocode_declaration
"""

from __future__ import annotations

import copy

from jinja2 import StrictUndefined, Template

from minisweagent.environments import get_environment
from minisweagent.run.benchmarks import swebench as _swebench


def get_msb_image_name(instance: dict) -> str:
    """Image URI for a Multi-SWE-bench instance, straight off the row."""
    image_name = instance.get("image_name") or ""
    if not image_name:
        raise ValueError(
            f"Instance {instance.get('instance_id', '<unknown>')!r} has no 'image_name'. "
            "Multi-SWE-bench rows must carry it; regenerate the subset with "
            "helper_code/data_prepare/generate_msb_instances.py."
        )
    return image_name


def get_msb_cwd(instance: dict) -> str:
    """Working directory inside the container: /home/<repo name>.

    ``repo`` is ``org/name`` (e.g. ``elastic/logstash``) and the image clones it
    to ``/home/logstash``.
    """
    repo = instance.get("repo") or ""
    name = repo.split("/")[-1]
    if not name:
        raise ValueError(
            f"Instance {instance.get('instance_id', '<unknown>')!r} has no 'repo', "
            "so the in-container repository path cannot be derived."
        )
    return f"/home/{name}"


def get_msb_environment(config: dict, instance: dict):
    """Build the environment for one Multi-SWE-bench instance.

    Mirrors ``swebench.get_sb_environment`` (including its deepcopy, so worker
    threads cannot scribble on each other's image) and then overrides cwd.
    """
    env_config = copy.deepcopy(config.get("environment", {}))
    env_config["environment_class"] = env_config.get("environment_class", "docker")

    image_name = get_msb_image_name(instance)
    if env_config["environment_class"] in ("docker", "swerex_modal", "swerex_daytona"):
        env_config["image"] = image_name
    elif env_config["environment_class"] in ("singularity", "contree"):
        env_config["image"] = "docker://" + image_name

    # Must come after the config copy: the benchmark config's cwd (/app for
    # SWE-bench Pro, /testbed for SWE-bench) is wrong for these images.
    env_config["cwd"] = get_msb_cwd(instance)

    env = get_environment(env_config)
    if startup_command := config.get("run", {}).get("env_startup_command"):
        startup_command = Template(startup_command, undefined=StrictUndefined).render(**instance)
        out = env.execute(startup_command)
        if out["returncode"] != 0:
            raise RuntimeError(f"Error executing startup command: {out}")
    return env


# process_instance() resolves get_sb_environment as a module global at call
# time, so rebinding it here redirects the whole batch loop.
_swebench.get_sb_environment = get_msb_environment

app = _swebench.app

if __name__ == "__main__":
    app()

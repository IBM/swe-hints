#!/usr/bin/env python3

"""Run mini-SWE-agent on Doc2Feat-bench instances in batch mode.

Doc2Feat-bench evaluates documentation-driven feature addition:
given a documentation diff, implement the described feature in source code.

Dataset: https://huggingface.co/datasets/Doc2Feat-bench/Doc2Feat-bench_Verified
Docker images: nocodebench/nocode-bench-instances:ncbench_{instance_id}
               (pull with: python environment/pull_instance_images.py from the doc2feat repo)
Evaluation: https://github.com/Doc2Feat-bench/Doc2Feat-bench
"""

import concurrent.futures
import json
import re
import threading
import time
import traceback
from pathlib import Path

import typer
from rich.live import Live

from minisweagent.config import builtin_config_dir, get_config_from_spec
from minisweagent.environments import get_environment
from minisweagent.models import get_model
from minisweagent.run.benchmarks.utils.batch_progress import RunBatchProgressManager
from minisweagent.run.benchmarks.utils.common import ProgressTrackingAgent
from minisweagent.utils.log import add_file_handler, logger
from minisweagent.utils.serialize import UNSET, recursive_merge

_HELP_TEXT = """Run mini-SWE-agent on Doc2Feat-bench instances.

[not dim]
Doc2Feat-bench evaluates [bold]documentation-driven feature addition[/bold]:
given a documentation diff, implement the described feature in the source code.

Dataset: [bold green]Doc2Feat-bench/Doc2Feat-bench_Verified[/bold green] (114 instances)

[bold]Before running[/bold], pull the instance-level Docker images from DockerHub:

  [bold green]python pull_instance_images.py --bench_tasks Doc2Feat-bench/Doc2Feat-bench_Verified[/bold green]

(script is in the [italic]environment/[/italic] folder of https://github.com/Doc2Feat-bench/Doc2Feat-bench)

Evaluate predictions with the doc2feat eval.py script:

  [bold green]python evaluation/eval.py --predictions_path preds.jsonl --bench_tasks Doc2Feat-bench/Doc2Feat-bench_Verified[/bold green]
[/not dim]
"""

_CONFIG_SPEC_HELP_TEXT = """Path to config files, filenames, or key-value pairs.

[bold red]IMPORTANT:[/bold red] [red]If you set this option, the default config file will not be used.[/red]
So you need to explicitly set it e.g., with [bold green]-c doc2feat.yaml <other options>[/bold green]

Multiple configs will be recursively merged.

Examples:

[bold green]-c doc2feat.yaml -c model.model_kwargs.temperature=0.5[/bold green]

[bold green]-c doc2feat.yaml -c model.model_name=anthropic/claude-haiku-3-5[/bold green]
"""

DATASET_MAPPING = {
    "verified": "Doc2Feat-bench/Doc2Feat-bench_Verified",
    "full": "Doc2Feat-bench/Doc2Feat-bench_Full",
}

DEFAULT_CONFIG_FILE = builtin_config_dir / "benchmarks" / "doc2feat.yaml"

app = typer.Typer(rich_markup_mode="rich", add_completion=False)
_OUTPUT_FILE_LOCK = threading.Lock()


def get_doc2feat_docker_image_name(instance: dict) -> str:
    """Get the instance-level Docker image name for a Doc2Feat-bench instance.

    Images are hosted at docker.io/nocodebench/nocode-bench-instances and must
    be pulled + locally tagged as ncbench_{instance_id}:latest before running.
    See: https://github.com/Doc2Feat-bench/Doc2Feat-bench/blob/main/environment/pull_instance_images.py
    """
    instance_id = instance["instance_id"]
    return f"ncbench_{instance_id}:latest"


def get_doc2feat_cwd(instance: dict) -> str:
    """Get the working directory inside the container for a Doc2Feat-bench instance.

    Doc2Feat images place the repo at /root/{repo_name} (e.g. /root/requests).
    """
    repo = instance["repo"]  # e.g. "psf/requests"
    repo_name = repo.split("/")[-1]  # e.g. "requests"
    return f"/root/{repo_name}"


def get_doc2feat_environment(config: dict, instance: dict):
    """Build an environment for a Doc2Feat-bench instance."""
    import copy

    env_config = copy.deepcopy(config.get("environment", {}))
    env_config["environment_class"] = env_config.get("environment_class", "docker")
    env_config["image"] = get_doc2feat_docker_image_name(instance)
    # Override cwd with the repo-specific working directory
    env_config["cwd"] = get_doc2feat_cwd(instance)
    return get_environment(env_config)


def format_hints(instance: dict) -> str:
    """Return the hints string for a Doc2Feat-bench instance.

    The ``hints`` field in the instance dict is the single control point.
    It must be explicitly set in the JSONL produced by
    generate_doc2feat_instances.py.  If the field is absent or empty,
    no hints section is shown — live-computed augmentations are never used.
    """
    return instance.get("hints") or ""


def update_preds_file(output_path: Path, instance_id: str, model_name: str, result: str):
    """Update the JSONL predictions file with results from a single instance.

    Doc2Feat eval.py accepts both .json and .jsonl formats. We write JSONL
    (one JSON object per line) for streaming-safe multi-worker writes.
    """
    with _OUTPUT_FILE_LOCK:
        # Read existing entries
        existing: dict[str, dict] = {}
        if output_path.exists():
            for line in output_path.read_text().splitlines():
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        existing[rec["instance_id"]] = rec
                    except json.JSONDecodeError:
                        pass
        existing[instance_id] = {
            "model_name_or_path": model_name,
            "instance_id": instance_id,
            "model_patch": result or "",
        }
        output_path.write_text("\n".join(json.dumps(r) for r in existing.values()) + "\n")


def remove_from_preds_file(output_path: Path, instance_id: str):
    """Remove an instance from the predictions file."""
    if not output_path.exists():
        return
    with _OUTPUT_FILE_LOCK:
        lines = []
        for line in output_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("instance_id") != instance_id:
                    lines.append(line)
            except json.JSONDecodeError:
                lines.append(line)
        output_path.write_text("\n".join(lines) + "\n" if lines else "")


def process_instance(
    instance: dict,
    output_dir: Path,
    config: dict,
    progress_manager: RunBatchProgressManager,
) -> None:
    """Process a single Doc2Feat-bench instance."""
    instance_id = instance["instance_id"]
    instance_dir = output_dir / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)

    remove_from_preds_file(output_dir / "preds.jsonl", instance_id)
    (instance_dir / f"{instance_id}.traj.json").unlink(missing_ok=True)

    model = get_model(config=config.get("model", {}))
    task = instance["problem_statement"]
    hints = format_hints(instance)

    progress_manager.on_instance_start(instance_id)
    progress_manager.update_instance_status(instance_id, "Pulling/starting environment")

    agent = None
    exit_status = None
    result = None
    extra_info = {}

    try:
        env = get_doc2feat_environment(config, instance)
        agent = ProgressTrackingAgent(
            model,
            env,
            progress_manager=progress_manager,
            instance_id=instance_id,
            **config.get("agent", {}),
        )
        info = agent.run(task, hints=hints)
        exit_status = info.get("exit_status")
        result = info.get("submission")
    except Exception as e:
        logger.error(f"Error processing instance {instance_id}: {e}", exc_info=True)
        exit_status, result = type(e).__name__, ""
        extra_info = {"traceback": traceback.format_exc(), "exception_str": str(e)}
    finally:
        if agent is not None:
            traj_path = instance_dir / f"{instance_id}.traj.json"
            agent.save(
                traj_path,
                {
                    "info": {
                        "exit_status": exit_status,
                        "submission": result,
                        **extra_info,
                    },
                    "instance_id": instance_id,
                },
            )
            logger.info(f"Saved trajectory to '{traj_path}'")
        update_preds_file(output_dir / "preds.jsonl", instance_id, model.config.model_name, result)
        progress_manager.on_instance_end(instance_id, exit_status)


def filter_instances(
    instances: list[dict], *, filter_spec: str, slice_spec: str = "", shuffle: bool = False
) -> list[dict]:
    """Filter and slice a list of instances."""
    import random

    if shuffle:
        instances = sorted(instances.copy(), key=lambda x: x["instance_id"])
        random.seed(42)
        random.shuffle(instances)
    before_filter = len(instances)
    if filter_spec:
        instances = [i for i in instances if re.match(filter_spec, i["instance_id"])]
        if (after_filter := len(instances)) != before_filter:
            logger.info(f"Instance filter: {before_filter} -> {after_filter} instances")
    if slice_spec:
        values = [int(x) if x else None for x in slice_spec.split(":")]
        instances = instances[slice(*values)]
        if (after_slice := len(instances)) != before_filter:
            logger.info(f"Instance slice: {before_filter} -> {after_slice} instances")
    return instances


# fmt: off
@app.command(help=_HELP_TEXT)
def main(
    subset: str = typer.Option("verified", "--subset", help="Doc2Feat-bench subset: 'verified', 'full', or a HuggingFace dataset path", rich_help_panel="Data selection"),
    split: str = typer.Option("test", "--split", help="Dataset split", rich_help_panel="Data selection"),
    slice_spec: str = typer.Option("", "--slice", help="Slice specification (e.g., '0:5' for first 5 instances)", rich_help_panel="Data selection"),
    filter_spec: str = typer.Option("", "--filter", help="Filter instance IDs by regex", rich_help_panel="Data selection"),
    shuffle: bool = typer.Option(False, "--shuffle", help="Shuffle instances", rich_help_panel="Data selection"),
    output: str = typer.Option("", "-o", "--output", help="Output directory", rich_help_panel="Basic"),
    workers: int = typer.Option(1, "-w", "--workers", help="Number of worker threads for parallel processing", rich_help_panel="Basic"),
    model: str | None = typer.Option(None, "-m", "--model", help="Model to use", rich_help_panel="Basic"),
    model_class: str | None = typer.Option(None, "--model-class", help="Model class to use", rich_help_panel="Advanced"),
    redo_existing: bool = typer.Option(False, "--redo-existing", help="Redo existing instances", rich_help_panel="Data selection"),
    config_spec: list[str] = typer.Option([str(DEFAULT_CONFIG_FILE)], "-c", "--config", help=_CONFIG_SPEC_HELP_TEXT, rich_help_panel="Basic"),
    environment_class: str | None = typer.Option(None, "--environment-class", help="Environment type (e.g., docker, singularity)", rich_help_panel="Advanced"),
) -> None:
    # fmt: on
    output_path = Path(output) if output else Path(f"doc2feat_results_{int(time.time())}")
    output_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Results will be saved to {output_path}")
    add_file_handler(output_path / "minisweagent.log")

    from datasets import load_dataset

    dataset_path = DATASET_MAPPING.get(subset, subset)
    logger.info(f"Loading dataset {dataset_path}, split {split}...")
    if dataset_path.endswith(".jsonl") or dataset_path.endswith(".json"):
        instances = list(load_dataset("json", data_files=dataset_path, split="train"))
    else:
        instances = list(load_dataset(dataset_path, split=split))

    instances = filter_instances(instances, filter_spec=filter_spec, slice_spec=slice_spec, shuffle=shuffle)

    preds_file = output_path / "preds.jsonl"
    if not redo_existing and preds_file.exists():
        existing_ids: set[str] = set()
        for line in preds_file.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    existing_ids.add(json.loads(line)["instance_id"])
                except (json.JSONDecodeError, KeyError):
                    pass
        if existing_ids:
            logger.info(f"Skipping {len(existing_ids)} existing instances")
            instances = [i for i in instances if i["instance_id"] not in existing_ids]

    logger.info(f"Running on {len(instances)} instances...")

    logger.info(f"Building agent config from specs: {config_spec}")
    configs = [get_config_from_spec(spec) for spec in config_spec]
    configs.append({
        "environment": {"environment_class": environment_class or UNSET},
        "model": {"model_name": model or UNSET, "model_class": model_class or UNSET},
    })
    config = recursive_merge(*configs)

    progress_manager = RunBatchProgressManager(len(instances), output_path / f"exit_statuses_{time.time()}.yaml")

    def process_futures(futures: dict[concurrent.futures.Future, str]):
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except concurrent.futures.CancelledError:
                pass
            except Exception as e:
                instance_id = futures[future]
                logger.error(f"Error in future for instance {instance_id}: {e}", exc_info=True)
                progress_manager.on_uncaught_exception(instance_id, e)

    with Live(progress_manager.render_group, refresh_per_second=4):
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(process_instance, instance, output_path, config, progress_manager): instance[
                    "instance_id"
                ]
                for instance in instances
            }
            try:
                process_futures(futures)
            except KeyboardInterrupt:
                logger.info("Cancelling all pending jobs. Press ^C again to exit immediately.")
                for future in futures:
                    if not future.running() and not future.done():
                        future.cancel()
                process_futures(futures)


if __name__ == "__main__":
    app()

"""Daytona sandboxes for mini-SWE-agent (`environment_class: swerex_daytona`).

Selectable like any other backend, e.g. `-c ... --environment-class swerex_daytona`, or via
an `environment:` block in a config file (see config/extra/daytona.yaml).

swe-rex ships a DaytonaDeployment, but it is not usable for SWE-bench Pro as-is. Five gaps
are closed here; each patch below explains its own failure mode in detail.

1. No resource control - swe-rex passes only `image`, so every sandbox gets Daytona's
   default size. SWE-bench Pro needs real resources (the official harness asks Modal for
   cpu=(1,4) / memory=(5,30) GB).
2. The dead pypi-timemachine index - 635 of 731 instance images bake
   `pip config set global.index-url http://127.0.0.1:9876/` from a proxy that only ran at
   build time, which breaks every in-sandbox pip install.
3. Leaked sandboxes - mini tears environments down via __del__, so a crash orphans a sandbox
   that bills until its timeout. auto_stop_interval/auto_delete_interval are the backstop.
4. swe-rex's start() blocks forever - it passes `runAsync=True` where the model field is
   `run_async`, so the camelCase kwarg is silently dropped and the server runs in the
   foreground. See _patch_start.
5. A bootstrap that assumes a modern Python - see _patch_bootstrap_command.

Requires: pip install daytona-sdk, and DAYTONA_API_KEY in the environment.
"""

import asyncio
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from daytona_sdk import CreateSandboxFromImageParams as _RealCreateSandboxParams
from daytona_sdk.common.image import Image as DaytonaImage
from daytona_sdk.common.sandbox import Resources
from pydantic import BaseModel
from swerex.deployment import daytona as _rex_daytona
from swerex.deployment.daytona import DaytonaDeployment
from swerex.runtime.abstract import Command as RexCommand

from minisweagent.exceptions import Submitted
from minisweagent.utils.serialize import recursive_merge

#: Override for the images' dead pypi-timemachine index (see module docstring).
PIP_INDEX_URL = os.environ.get("SWEBP_PIP_INDEX_URL", "https://pypi.org/simple")

#: Chatter from the runtime-startup poll. Off by default - a 502 from the Daytona proxy
#: is the *expected* state while the in-sandbox bootstrap is still binding the port, so
#: at any real worker count it just floods the progress display. Set SWEBP_DEBUG=1 to
#: bring it back when a deployment genuinely hangs.
DEBUG = os.environ.get("SWEBP_DEBUG", "").lower() not in ("", "0", "false", "no")

_PATCH_MARKER = "_swebp_daytona_patched"


def _debug(message: str) -> None:
    """Print only under SWEBP_DEBUG (see DEBUG)."""
    if DEBUG:
        print(message, flush=True)


class SwerexDaytonaEnvironmentConfig(BaseModel):
    image: str
    cwd: str = "/"
    """Working directory in which to execute commands."""
    timeout: int = 30
    """Timeout for executing a single command."""
    env: dict[str, str] = {}
    """Environment variables applied to each executed command."""
    api_key: str = ""
    """Daytona API key. Falls back to $DAYTONA_API_KEY."""
    target: str = "us"
    """Daytona target region."""
    port: int = 8000
    """Port the swe-rex server listens on inside the sandbox."""
    container_timeout: float = 3600.0
    """Max lifetime of the swe-rex server process. swe-rex defaults this to 900s, which is
    shorter than a real SWE-bench Pro instance (a measured qutebrowser run took ~10 min of
    model calls alone), so it is raised here."""
    runtime_timeout: float = 900.0
    """How long to wait for the runtime to come up. swe-rex defaults to 60s, which is not
    enough when the bootstrap has to apt-get pipx and pipx run swe-rex on a cold sandbox."""
    cpu: int = 2
    """CPU cores. 2 matches the configuration proven on the qutebrowser smoke run."""
    memory: int = 8
    """Memory in GiB. Keep >= 5: that is the floor the official eval harness requests."""
    disk: int = 10
    """Disk in GiB. Daytona caps this at 10 GiB per sandbox on standard accounts - asking
    for more fails the create call outright ("Disk request 20GB exceeds maximum allowed per
    sandbox (10GB)"). 10 is comfortable: the python-partition images measure 0.5-1.1 GB
    compressed, roughly 1.3-2.7 GB unpacked, leaving ample room for the repo, pip installs
    and test artifacts. Daytona bills storage only above the first 5 GiB."""
    auto_stop_interval: int = 30
    """Minutes of inactivity before Daytona stops the sandbox. 0 disables. Backstop against
    leaked sandboxes billing forever."""
    auto_delete_interval: int = 60
    """Minutes after stopping before Daytona deletes the sandbox. 0 deletes immediately."""
    create_timeout: float = 1800.0
    """Seconds to allow for sandbox creation, including any snapshot build.

    The SDK defaults `create(timeout=60)` but then calls wait_for_sandbox_start(timeout=0),
    which waits forever - so a slow or wedged snapshot build hangs the run with no error
    and no output at all. Bounded here so failures surface."""
    show_build_logs: bool = True
    """Stream Daytona's snapshot build logs.

    daytona_sdk only streams them when an on_snapshot_create_logs callback is supplied
    (see _sync/daytona.py: `if response.state == PENDING_BUILD and on_snapshot_create_logs`).
    swe-rex supplies none, so a multi-minute build looks identical to a hang."""
    public: bool = True
    """Make the sandbox's preview URL publicly reachable.

    swe-rex connects to the sandbox through Daytona's preview link. For private sandboxes
    that link requires an x-daytona-preview-token header, which swe-rex's RemoteRuntime
    never sends (it only sends X-API-Key) - the is_alive poll then 401s until the runtime
    timeout with no error surfaced. The swe-rex server still requires its own per-run auth
    token, so opening the preview URL does not expose an unauthenticated shell."""
    prebuild_image: bool = False
    """Build a snapshot with swe-rex baked in, instead of pulling the image as-is.

    OFF by default. daytona_sdk submits a str image as a one-line `FROM <image>` build_info
    (_sync/daytona.py: `if isinstance(params.image, str)`), i.e. a pull-and-register, while an
    Image object ships a real multi-step Dockerfile that Daytona must actually build. With 266
    distinct instance images, paying a real build per image is far worse than a fast runtime
    bootstrap - so prefer the patched bootstrap below and leave this off.

    swe-rex's Daytona bootstrap is
        swerex-remote ... || (apt-get update -y && apt-get install pipx -y && ...
                              && pipx run swe-rex ...)
    On Modal the pipx half is baked in at image build time and cached, so sandboxes start
    in ~40s. Daytona's swe-rex backend has no build step, so that entire chain runs inside
    every sandbox from a bare python:3.11-slim base - minutes each, silently (the command
    is dispatched with runAsync=True, so nothing is surfaced until the runtime poll
    finally times out). Across 532 runs that overhead is paid 532 times.

    With this enabled the image is declared via Daytona's Image builder so swerex-remote
    already exists on PATH and the fallback chain never runs. Set false to revert to
    swe-rex's stock behaviour."""


class SwerexDaytonaEnvironment:
    """Executes commands in a Daytona sandbox via swe-rex. Mirrors SwerexModalEnvironment."""

    def __init__(self, **kwargs):
        apply()
        self.config = SwerexDaytonaEnvironmentConfig(**kwargs)
        api_key = self.config.api_key or os.environ.get("DAYTONA_API_KEY", "")
        if not api_key:
            msg = "No Daytona API key: set DAYTONA_API_KEY or environment.api_key in the config."
            raise RuntimeError(msg)

        # Resources / env_vars / auto-reap are not settable through swe-rex's config, so
        # they are stashed here and picked up by the CreateSandboxFromImageParams wrapper.
        _CREATE_KWARGS["timeout"] = self.config.create_timeout
        _CREATE_KWARGS["show_build_logs"] = self.config.show_build_logs
        _SANDBOX_PARAMS.pop("image", None)
        if self.config.prebuild_image:
            _SANDBOX_PARAMS["image"] = _prebuilt_image(self.config.image)
        _SANDBOX_PARAMS.update(
            public=self.config.public,
            resources=Resources(cpu=self.config.cpu, memory=self.config.memory, disk=self.config.disk),
            env_vars={"PIP_INDEX_URL": PIP_INDEX_URL, **self.config.env},
            auto_stop_interval=self.config.auto_stop_interval,
            auto_delete_interval=self.config.auto_delete_interval,
        )

        self.deployment = DaytonaDeployment(
            # Must stay a str: DaytonaDeploymentConfig.image is typed str and rejects an
            # Image object. The built image is handed to CreateSandboxFromImageParams
            # instead, whose image field is `str | Image`.
            image=self.config.image,
            api_key=api_key,
            target=self.config.target,
            port=self.config.port,
            container_timeout=self.config.container_timeout,
            runtime_timeout=self.config.runtime_timeout,
        )
        asyncio.run(self.deployment.start())

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        command = action.get("command", "") if isinstance(action, dict) else action
        try:
            result = asyncio.run(
                self.deployment.runtime.execute(
                    RexCommand(
                        command=command,
                        shell=True,
                        check=False,
                        cwd=cwd or self.config.cwd,
                        timeout=timeout or self.config.timeout,
                        merge_output_streams=True,
                        env=self.config.env or None,
                    )
                )
            )
            output = {"output": result.stdout, "returncode": result.exit_code, "exception_info": ""}
        except Exception as e:
            output = {
                "output": str(e) if str(e) else "",
                "returncode": -1,
                "exception_info": f"An error occurred while executing the command: {e}",
                "extra": {"exception_type": type(e).__name__, "exception": str(e)},
            }
        self._check_finished(output)
        return output

    def _check_finished(self, output: dict):
        """Raises Submitted if the output indicates task completion."""
        lines = output.get("output", "").lstrip().splitlines(keepends=True)
        if lines and lines[0].strip() == "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" and output["returncode"] == 0:
            submission = "".join(lines[1:])
            raise Submitted(
                {
                    "role": "exit",
                    "content": submission,
                    "extra": {"exit_status": "Submitted", "submission": submission},
                }
            )

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return recursive_merge(self.config.model_dump(), kwargs)

    def serialize(self) -> dict:
        return {
            "info": {
                "config": {
                    "environment": self.config.model_dump(mode="json"),
                    "environment_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                }
            }
        }

    def stop(self):
        try:
            asyncio.run(asyncio.wait_for(self.deployment.stop(), timeout=30))
        except Exception:
            pass

    # mini tears environments down via __del__ (see the orphaned-sandbox note above).
    cleanup = stop
    __del__ = stop


def _patch_bootstrap_command() -> None:
    """Replace swe-rex's apt+pipx sandbox bootstrap with a venv+pip one.

    Stock swe-rex runs, inside every sandbox:
        swerex-remote ... || (apt-get update -y && apt-get install pipx -y
                              && pipx ensurepath && pipx run swe-rex ...)
    `apt-get update` alone downloads the whole package index, and `apt-get install pipx` pulls
    a dependency tree - minutes per sandbox, paid 532 times, and invisible because swe-rex
    dispatches the command with runAsync=True.

    Most of these images are FROM python:3.11-slim, so python3, venv and pip are already
    present: a venv plus `pip install swe-rex` reaches the same place without touching apt. The
    venv also keeps swe-rex out of the repo's own environment, which is the thing under test.

    --index-url is passed explicitly because the images bake a dead pypi-timemachine index into
    pip's global config.

    "Most" is the catch, and it is why there is a uv tier. Every real swe-rex release declares
    Requires-Python >=3.10, and 88 of the 266 python-partition images ship an older python3
    (3.9 or 3.8). On those, `pip install swe-rex` does NOT fail - it silently resolves to
    swe-rex 0.0.0, a 990-byte "Coming soon" placeholder with no modules and no console script.
    pip exits 0, the && chain advances, and the tier dies on
    `/tmp/swerex-venv/bin/swerex-remote: No such file or directory`. Hence the explicit
    >=1.0 floor below: it turns that silent stub into an honest resolution error, so the
    chain falls through in seconds instead of pretending to have succeeded.

    What happens next used to depend entirely on the distro, which is why python:3.9-slim
    instances passed while ubuntu:20.04 ones hung:

      * On Debian bookworm (the python:X-slim images) `apt-get install pipx` yields a modern
        pipx bound to Debian's own python3.11, so `pipx run swe-rex` gets a real swe-rex on a
        new enough interpreter. Slow - apt update plus a pipx venv on every sandbox - but it
        works, which is why nobody noticed the stub.
      * On ubuntu:20.04 (28 instances: ansible 22, qutebrowser 6) focal ships pipx 0.12.3.1,
        which crashes under python3.9 with `TypeError: __init__() got an unexpected keyword
        argument encoding`. Nothing binds the port, the Daytona proxy answers 502 forever, and
        the deployment burns the full runtime_timeout before raising TimeoutError - ~15 idle
        sandbox-minutes per instance, and it can never succeed.

    The uv tier removes the dependency on the image's python entirely: it fetches a standalone
    CPython 3.11 and builds the swe-rex venv against that. Two details are load-bearing:

      * uv is obtained by whichever of three routes works, each ending at one fixed path.
        Never via `python3 -m uv`: that does install, but on Debian/Ubuntu the console script
        lands in /usr/local/bin while uv's own find_uv_bin() searches only /usr/bin,
        <dist-packages>/bin and ~/.local/bin, so it dies with UvNotFound. The preferred route
        is a throwaway venv (binary at <venv>/bin/uv), then `pip install --user` (~/.local/bin),
        then the curl installer - because one ubuntu:22.04 ansible image installs python3.10
        without python3.10-venv, so `python3 -m venv` fails there and took the whole tier with
        it until this fallback existed.
      * It needs egress to PyPI and to the python-build-standalone release assets on GitHub.

    This also retires the apt+pipx path for the ~53 python:3.8/3.9 official images that were
    only ever passing through it, which is minutes of apt traffic per sandbox.
    """
    if getattr(DaytonaDeployment._get_command, _PATCH_MARKER, False):
        return

    def _get_command(self, *, token: str) -> str:
        args = f"--port {self._config.port} --auth-token {token}"
        venv = "/tmp/swerex-venv"
        fast = (
            f"python3 -m venv {venv}"
            f" && {venv}/bin/pip install --quiet --disable-pip-version-check"
            # The >=1.0 floor is what stops pip from "succeeding" with the 0.0.0 stub.
            f' --index-url {PIP_INDEX_URL} "swe-rex>=1.0"'
            f" && {venv}/bin/swerex-remote {args}"
        )
        uv_box = "/tmp/swerex-uvbox"
        uv_venv = "/tmp/swerex-uv-venv"
        uv_bin = "/tmp/swerex-uv"
        # Three ways to land a uv binary at one known path, because no single one covers every
        # image: the venv route needs python3-venv (missing on one ubuntu:22.04 ansible image),
        # --user needs a pip that does not enforce PEP 668, and curl is absent from the slim
        # python images. Each branch ends by copying uv to uv_bin so the rest is uniform.
        get_uv = (
            f"( python3 -m venv {uv_box}"
            f" && {uv_box}/bin/pip install --quiet --disable-pip-version-check"
            f" --index-url {PIP_INDEX_URL} uv && cp {uv_box}/bin/uv {uv_bin} )"
            f" || ( python3 -m pip install --quiet --disable-pip-version-check --user"
            f" --index-url {PIP_INDEX_URL} uv && cp $HOME/.local/bin/uv {uv_bin} )"
            f" || ( curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/tmp sh"
            f" && cp /tmp/uv {uv_bin} )"
        )
        uv = (
            f"( {get_uv} )"
            f" && {uv_bin} venv --quiet --python 3.11 {uv_venv}"
            f" && {uv_bin} pip install --quiet --python {uv_venv}/bin/python"
            f' --index-url {PIP_INDEX_URL} "swe-rex>=1.0"'
            f" && {uv_venv}/bin/swerex-remote {args}"
        )
        stock = " && ".join(
            ["apt-get update -y", "apt-get install pipx -y", "pipx ensurepath", f"pipx run swe-rex {args}"]
        )
        # Note: no single quotes anywhere inside - the whole thing is wrapped in bash -c '...'.
        inner = f"swerex-remote {args} || ( {fast} ) || ( {uv} ) || ( {stock} )"
        return f"timeout {self._config.container_timeout}s bash -c '{inner}'"

    setattr(_get_command, _PATCH_MARKER, True)
    DaytonaDeployment._get_command = _get_command


def _prebuilt_image(image_uri: str) -> "DaytonaImage":
    """The instance image with swe-rex already installed (see prebuild_image)."""
    return (
        DaytonaImage.base(image_uri)
        # SWE-bench Pro images declare ENTRYPOINT ["/bin/bash"] with no CMD. That exact
        # combination killed the Modal sandboxes, so clear it here as well rather than
        # rely on Daytona happening to ignore it.
        .entrypoint([])
        # Overrides the images' dead pypi-timemachine index at build time too, not just
        # at runtime - pip config in the image would otherwise break these installs.
        .env({"PIP_INDEX_URL": PIP_INDEX_URL})
        .run_commands(
            # pipx keeps swe-rex in its own venv, so the repo's environment - the thing
            # actually under test - is never touched.
            f"python3 -m pip install --no-cache-dir --index-url {PIP_INDEX_URL} pipx",
            f"PIP_INDEX_URL={PIP_INDEX_URL} python3 -m pipx install swe-rex",
            # The bootstrap runs under a non-login `bash -c`, which does not pick up what
            # `pipx ensurepath` writes to the shell profile, so link into a default PATH dir.
            "ln -sf /root/.local/bin/swerex-remote /usr/local/bin/swerex-remote",
            "swerex-remote --help > /dev/null",  # fail the build, not the run, if broken
        )
    )


#: Filled in per-instance by SwerexDaytonaEnvironment.__init__.
_SANDBOX_PARAMS: dict[str, Any] = {}
_CREATE_KWARGS: dict[str, Any] = {}


def _patch_start() -> None:
    """Replace DaytonaDeployment.start: swe-rex's version blocks forever by accident.

    Root cause: swe-rex builds `SessionExecuteRequest(command=..., runAsync=True)`, but this
    daytona_sdk's model field is `run_async` - the camelCase kwarg is SILENTLY DROPPED
    (verified: constructing with runAsync=True yields run_async=None). The execution is
    therefore synchronous, and execute_session_command blocks until the bash command exits.
    The command runs the swe-rex server in the foreground, which by design never exits, so
    start() hangs at "Starting SWE Rex server..." for up to container_timeout while the
    server sits healthy inside the sandbox. Every earlier fix (preview-link host, auth
    header, poll clamp) was downstream of this line and never got reached.

    Second bug fixed here: with async actually working the response carries exit_code=None,
    which upstream's `if response.exit_code != 0` would misread as failure.
    """
    if getattr(DaytonaDeployment.start, _PATCH_MARKER, False):
        return

    from daytona_sdk import SessionExecuteRequest

    async def start(self):
        self._init_daytona()
        self.logger.info("Creating Daytona sandbox...")
        params = _rex_daytona.CreateSandboxFromImageParams(image=self._config.image)
        self._sandbox = self._daytona.create(params)
        self._sandbox_id = self._sandbox.id
        self.logger.info(f"Created Daytona sandbox with ID: {self._sandbox_id}")
        self._auth_token = self._get_token()
        command = self._get_command(token=self._auth_token)
        session_id = f"swerex-server-{uuid.uuid4().hex[:8]}"
        self._sandbox.process.create_session(session_id)
        req = SessionExecuteRequest(command=command, run_async=True)  # field name, not alias
        response = self._sandbox.process.execute_session_command(session_id, req)
        if response.exit_code not in (None, 0):  # None = launched asynchronously
            self.logger.error(f"Failed to start SWE Rex server: {response.output}")
            await self.stop()
            raise RuntimeError(f"Failed to start SWE Rex server: {response.output}")
        link = self._sandbox.get_preview_link(self._config.port)
        self._runtime = _rex_daytona.RemoteRuntime(
            host=link, port=None, auth_token=self._auth_token, logger=self.logger
        )
        t0 = time.time()
        await self._wait_until_alive(timeout=self._config.runtime_timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    setattr(start, _PATCH_MARKER, True)
    DaytonaDeployment.start = start


def _patch_remote_runtime() -> None:
    """Make swe-rex's RemoteRuntime able to talk to a Daytona preview link.

    DaytonaDeployment.start does:
        sweRexHost = self._sandbox.get_preview_link(self._config.port)
        RemoteRuntime(host=sweRexHost, ...)
    but get_preview_link returns a PortPreviewUrl OBJECT (fields: url, token), not a str.
    RemoteRuntime builds f"{host}/is_alive" from it, which is not a URL, so the alive-poll
    can never succeed: the server comes up inside the sandbox (verified via session logs)
    while the client spins until runtime_timeout. Additionally, private-sandbox preview
    links require the x-daytona-preview-token header, which RemoteRuntime does not send.

    The shim extracts .url for the host and attaches the preview token header when present.
    """
    from swerex.runtime.remote import RemoteRuntime

    if getattr(_rex_daytona.RemoteRuntime, _PATCH_MARKER, False):
        return

    class DaytonaRemoteRuntime(RemoteRuntime):
        def __init__(self, *, host, **kwargs):
            self._preview_token = getattr(host, "token", None)
            resolved = getattr(host, "url", host)
            _debug(f"[swebp] runtime host: {resolved}")
            super().__init__(host=resolved, **kwargs)

        @property
        def _headers(self) -> dict:
            headers = dict(RemoteRuntime._headers.fget(self))
            if self._preview_token:
                headers["x-daytona-preview-token"] = self._preview_token
            return headers

        async def is_alive(self, *, timeout=None):
            # DaytonaDeployment passes function_timeout=container_timeout (3600s) as the
            # per-request budget. The first poll fires before the in-sandbox bootstrap
            # (venv + pip install, ~40s) has bound the port, and Daytona's proxy HOLDS the
            # connection until the upstream appears - so that single GET can sit inside its
            # hour-long budget indefinitely and the deployment looks hung forever. Clamp
            # each attempt; the wait loop retries, and succeeds as soon as the server is up.
            try:
                r = await super().is_alive(timeout=min(timeout or 10.0, 10.0))
            except Exception as e:
                _debug(f"[swebp poll] EXC {type(e).__name__}: {str(e)[:200]}")
                raise
            if not r.is_alive:
                _debug(f"[swebp poll] not alive yet: {str(r.message)[:200]}")
            return r

    setattr(DaytonaRemoteRuntime, _PATCH_MARKER, True)
    _rex_daytona.RemoteRuntime = DaytonaRemoteRuntime


def _call_off_loop(func, *args, **kwargs):
    """Run a blocking daytona_sdk call in a thread that has no running event loop.

    See gap 5 in the module docstring: the sync SDK calls asyncio.run() internally to
    stream build logs, which is illegal from the loop that asyncio.run(start()) is
    driving. A worker thread has no loop of its own, so the nested call is fine there;
    we block on the result, which is what the sync API promised anyway.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return func(*args, **kwargs)  # no loop in this thread - nothing to work around
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(func, *args, **kwargs).result()


def _patch_daytona_create() -> None:
    """Give Daytona.create a real timeout, surface build logs, and keep it off our loop."""
    from daytona_sdk import Daytona

    if getattr(Daytona.create, _PATCH_MARKER, False):
        return
    original = Daytona.create

    def create(self, params=None, *args, **kwargs):
        kwargs.setdefault("timeout", _CREATE_KWARGS.get("timeout", 1800.0))
        if _CREATE_KWARGS.get("show_build_logs", True) and "on_snapshot_create_logs" not in kwargs:
            kwargs["on_snapshot_create_logs"] = lambda chunk: print(f"[daytona build] {chunk}", flush=True)
        return _call_off_loop(original, self, params, *args, **kwargs)

    setattr(create, _PATCH_MARKER, True)
    Daytona.create = create


def _create_sandbox_params(**kwargs):
    """swe-rex's CreateSandboxFromImageParams(image=...), plus resources/env/auto-reap."""
    extra = dict(_SANDBOX_PARAMS)
    prebuilt = extra.pop("image", None)
    for key, value in extra.items():
        kwargs.setdefault(key, value)
    if prebuilt is not None:
        # Override rather than setdefault: swe-rex always passes image= explicitly.
        kwargs["image"] = prebuilt
    return _RealCreateSandboxParams(**kwargs)



def apply() -> None:
    """Idempotently install the Daytona backend into mini and swe-rex."""
    _patch_daytona_create()
    _patch_bootstrap_command()
    _patch_remote_runtime()
    _patch_start()

    if not getattr(_rex_daytona.CreateSandboxFromImageParams, _PATCH_MARKER, False):
        setattr(_create_sandbox_params, _PATCH_MARKER, True)
        _rex_daytona.CreateSandboxFromImageParams = _create_sandbox_params


apply()

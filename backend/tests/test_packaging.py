"""Packaging / reproducibility invariants (ACR-42, A10-4).

These tests read repo files rather than exercising `app.*`. They exist because the repo had drifted
into naming **four** Node versions and **three** Python versions across README, docs, CI, and the
two `.nvmrc` files, and because the two least deterministic dependencies — `google-genai` and
`anthropic` — were the only unpinned lines in `requirements.txt`.

That was not theoretical: two developer virtualenvs built from the same `requirements.txt` were
found running `anthropic` 0.119.0 and 0.109.2. Same spec file, different code.

Each test below asserts one parity invariant so the drift cannot come back silently. No database and
no fixtures, so they run in milliseconds as part of the normal suite.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

REQUIREMENTS = BACKEND_DIR / "requirements.txt"
LOCKFILE = BACKEND_DIR / "requirements.lock"
PYPROJECT = BACKEND_DIR / "pyproject.toml"
BACKEND_DOCKERFILE = BACKEND_DIR / "Dockerfile"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
ROOT_NVMRC = REPO_ROOT / ".nvmrc"
FRONTEND_NVMRC = REPO_ROOT / "frontend" / ".nvmrc"
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
FRONTEND_DOCKERFILE = REPO_ROOT / "frontend" / "Dockerfile"

ENV_TEMPLATES = [
    BACKEND_DIR / ".env.example",
    REPO_ROOT / "frontend" / ".env.local.example",
    REPO_ROOT / ".env.example",
]

# The backend container image is built with `backend/` as its context, so the repo-root files these
# parity tests compare against (.nvmrc, frontend/package.json, .github/workflows/ci.yml, README.md,
# docs/architecture.md) simply are not there. Skip rather than fail in that environment: the tests
# still run on a developer checkout and in CI, which is where the drift they guard against happens.
REPO_ROOT_AVAILABLE = (REPO_ROOT / "frontend").is_dir() and (REPO_ROOT / ".github").is_dir()

requires_repo_root = pytest.mark.skipif(
    not REPO_ROOT_AVAILABLE,
    reason="repo-root files are absent (running inside the backend image, whose context is backend/)",
)


# --------------------------------------------------------------------------- helpers


def _major(version_text: str) -> int:
    """First integer in a version-ish string: '24', 'v24.1', '>=24' -> 24."""
    match = re.search(r"\d+", version_text)
    assert match, f"no version number found in {version_text!r}"
    return int(match.group())


def _requirement_lines(path: Path) -> list[str]:
    """Non-empty, non-comment lines with any trailing ``# comment`` stripped."""
    lines = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _distribution_name(requirement: str) -> str:
    """'uvicorn[standard]==0.32.1' -> 'uvicorn'; normalized to PEP 503 form."""
    name = re.split(r"[\[=<>!~;]", requirement, maxsplit=1)[0].strip()
    return re.sub(r"[-_.]+", "-", name).lower()


def _package_json() -> dict:
    return json.loads(PACKAGE_JSON.read_text())


def _ci_python_version() -> str:
    """The `python-version:` the CI workflow pins.

    Read with a regex rather than a YAML parser on purpose: PyYAML is not a declared dependency of
    this project, it is only present transitively, and a packaging test must not be the thing that
    quietly adds one.
    """
    versions = set(
        re.findall(r"""python-version:\s*["']?([\d.]+)["']?""", CI_WORKFLOW.read_text())
    )
    assert versions, "no python-version found in the CI workflow"
    assert len(versions) == 1, f"CI pins more than one Python version: {sorted(versions)}"
    return versions.pop()


def _requires_python_floor() -> str:
    """The '3.13' out of a `requires-python = '>=3.13'` declaration."""
    declared = tomllib.loads(PYPROJECT.read_text())["project"]["requires-python"]
    match = re.search(r"(\d+\.\d+)", declared)
    assert match, f"could not parse a major.minor out of requires-python={declared!r}"
    return match.group(1)


# --------------------------------------------------------------------------- Node


@requires_repo_root
def test_node_version_is_consistent_across_the_repo():
    """Root .nvmrc, frontend/.nvmrc and engines.node must name one Node major.

    Regression guard for the pre-ACR-42 state: root said 22, frontend said 24, engines said >=24.
    """
    root = _major(ROOT_NVMRC.read_text())
    frontend = _major(FRONTEND_NVMRC.read_text())
    engines = _major(_package_json()["engines"]["node"])

    assert root == frontend == engines, (
        f"Node version drift: root .nvmrc={root}, frontend/.nvmrc={frontend}, "
        f"package.json engines.node={engines}"
    )


@requires_repo_root
def test_types_node_major_matches_the_node_runtime():
    """@types/node must track the Node major actually used, or types lie about the runtime."""
    types_node = _major(_package_json()["devDependencies"]["@types/node"])
    runtime = _major(FRONTEND_NVMRC.read_text())

    assert types_node == runtime, (
        f"@types/node major {types_node} does not match the Node runtime {runtime}"
    )


# --------------------------------------------------------------------------- Python


@requires_repo_root
def test_requires_python_matches_ci_python_version():
    """The declared Python and the Python CI actually runs must be the same major.minor."""
    assert _requires_python_floor() == _ci_python_version(), (
        f"requires-python floor {_requires_python_floor()} != "
        f"CI python-version {_ci_python_version()}"
    )


@requires_repo_root
def test_readme_and_architecture_docs_name_the_declared_python():
    """Docs must not advertise a Python the project does not declare."""
    declared = _requires_python_floor()

    for doc in (REPO_ROOT / "README.md", REPO_ROOT / "docs" / "architecture.md"):
        text = doc.read_text()
        versions = set(re.findall(r"\b3\.(?:9|10|11|12|13|14)\b", text))
        assert versions <= {declared}, (
            f"{doc.name} names Python {sorted(versions - {declared})} "
            f"but the project declares {declared}"
        )


# --------------------------------------------------------------------------- container base images
#
# The Dockerfiles hardcode their base-image tags, which makes them a source of truth for the very
# versions this file exists to keep aligned. Without these two tests, bumping `.nvmrc` would leave
# `node:24-alpine` behind in three places and every other test here would still pass — the exact
# drift the module docstring describes, reintroduced by the containers themselves.


def _dockerfile_base_tag(dockerfile: Path, image: str) -> str:
    """The tag off a `FROM <image>:<tag>` line, e.g. 'python' -> '3.13-slim'."""
    tags = re.findall(
        rf"^FROM\s+{re.escape(image)}:(\S+)", dockerfile.read_text(), flags=re.MULTILINE
    )
    assert tags, f"no `FROM {image}:...` line found in {dockerfile}"
    assert len(set(tags)) == 1, (
        f"{dockerfile.name} builds on more than one {image} tag: {sorted(set(tags))}"
    )
    return tags[0]


def test_backend_dockerfile_python_matches_requires_python():
    """The image Python and the declared Python must agree.

    `python:3.13-slim` vs `requires-python = ">=3.13"` — if these drift, the containers run a
    different interpreter than CI and the docs claim.
    """
    tag = _dockerfile_base_tag(BACKEND_DOCKERFILE, "python")
    declared = _requires_python_floor()

    assert tag.startswith(declared), (
        f"backend/Dockerfile builds on python:{tag} but the project declares Python {declared}"
    )


@requires_repo_root
def test_frontend_dockerfile_node_matches_nvmrc():
    """Every `FROM node:` stage must match the Node major in .nvmrc."""
    tag = _dockerfile_base_tag(FRONTEND_DOCKERFILE, "node")
    declared = _major(FRONTEND_NVMRC.read_text())

    assert _major(tag) == declared, (
        f"frontend/Dockerfile builds on node:{tag} but .nvmrc declares Node {declared}"
    )


# --------------------------------------------------------------------------- dependency pinning


@pytest.mark.parametrize("requirement", _requirement_lines(REQUIREMENTS))
def test_every_backend_requirement_is_exactly_pinned(requirement):
    """`==` only. A range makes two installs of the same commit produce different code.

    Parameterized so a failure names the offending package instead of the whole file.
    """
    assert "==" in requirement, (
        f"{requirement!r} is not exactly pinned — use '==' so the build is reproducible"
    )
    assert not re.search(r"[<>~]|!=", requirement), (
        f"{requirement!r} mixes a range operator into the pin"
    )


def test_lockfile_exists_and_covers_every_direct_requirement():
    """Every directly-declared distribution must appear in the transitive lock."""
    assert LOCKFILE.exists(), (
        f"{LOCKFILE.name} is missing — regenerate it with "
        f"`./.venv/bin/python -m pip freeze > requirements.lock`"
    )

    locked = {_distribution_name(line) for line in _requirement_lines(LOCKFILE)}
    direct = {_distribution_name(line) for line in _requirement_lines(REQUIREMENTS)}

    missing = sorted(direct - locked)
    assert not missing, f"declared in requirements.txt but absent from the lockfile: {missing}"


def test_lockfile_is_exactly_pinned():
    """A lockfile with a range in it is not a lockfile."""
    unpinned = [line for line in _requirement_lines(LOCKFILE) if "==" not in line]
    assert not unpinned, f"lockfile entries without an exact pin: {unpinned}"


def test_lockfile_agrees_with_requirements_on_shared_packages():
    """Where both files name a package, they must name the same version."""

    def versions(path: Path) -> dict[str, str]:
        out = {}
        for line in _requirement_lines(path):
            if "==" in line:
                name, _, version = line.partition("==")
                out[_distribution_name(name)] = version.strip()
        return out

    direct, locked = versions(REQUIREMENTS), versions(LOCKFILE)
    conflicts = {
        name: (direct[name], locked[name])
        for name in direct.keys() & locked.keys()
        if direct[name] != locked[name]
    }
    assert not conflicts, f"requirements.txt and requirements.lock disagree: {conflicts}"


# --------------------------------------------------------------------------- env templates


@pytest.mark.parametrize(
    "template", ENV_TEMPLATES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_env_template_has_no_duplicate_keys(template):
    """Regression test for ACR-42: backend/.env.example declared CORS_ORIGINS twice.

    The last assignment won, so behaviour was accidentally correct — but this is the file a
    clean-run user copies, and a silently-shadowed key is exactly the friction A10 is about.
    """
    if not template.exists():
        pytest.skip(f"{template} does not exist")

    seen: dict[str, int] = {}
    duplicates: dict[str, list[int]] = {}
    for number, raw in enumerate(template.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key in seen:
            duplicates.setdefault(key, [seen[key]]).append(number)
        else:
            seen[key] = number

    assert not duplicates, f"{template.name} declares the same key twice: {duplicates}"

"""Static guards for requirements that code and configuration enforce silently.

SEC-04 (parsing never evaluates content), SEC-13 (parameterised SQL only), SEC-23 (secrets only
from the environment), SEC-30 (locked dependencies), SEC-31 (pinned base images, non-root runtime)
and SEC-32 (no ad-hoc downloads in builds). Each of these was true when written and would break
quietly; these tests make breaking them loud.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import Final

import pytest

REPO: Final = Path(__file__).resolve().parents[3]
RUNTIME: Final = REPO / "backend" / "src" / "relay"

FORBIDDEN_CALLS: Final = frozenset({"eval", "exec", "compile", "__import__"})
FORBIDDEN_MODULES: Final = frozenset({"pickle", "marshal", "shelve", "subprocess", "yaml"})


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


RUNTIME_FILES: Final = _python_files(RUNTIME)


def test_the_runtime_package_is_not_empty() -> None:
    assert len(RUNTIME_FILES) > 50  # the scans below are not vacuous


@pytest.mark.parametrize("path", RUNTIME_FILES, ids=lambda p: str(p.relative_to(RUNTIME)))
def test_runtime_code_never_evaluates_content_or_shells_out(path: Path) -> None:
    """SEC-04: parsing is `csv` and explicit transforms; nothing evaluates what it reads."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in FORBIDDEN_CALLS, f"{path}:{node.lineno} calls {node.func.id}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in FORBIDDEN_MODULES, f"{path}:{node.lineno} imports {alias.name}"
        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            assert root not in FORBIDDEN_MODULES, f"{path}:{node.lineno} imports from {node.module}"


@pytest.mark.parametrize("path", RUNTIME_FILES, ids=lambda p: str(p.relative_to(RUNTIME)))
def test_raw_sql_is_never_built_from_strings(path: Path) -> None:
    """SEC-13: every `text(...)` takes a literal; values are bound, never interpolated."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "text" or not node.args:
            continue
        argument = node.args[0]
        literal = isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        joined = isinstance(argument, ast.JoinedStr)
        concatenated = isinstance(argument, ast.BinOp)
        where = f"{path}:{node.lineno}"
        assert not joined, f"{where} builds SQL with an f-string"
        assert not concatenated, f"{where} builds SQL by concatenation"
        assert literal, f"{where} builds SQL from a non-literal expression"


def test_committed_environment_example_holds_no_values() -> None:
    """SEC-23: `.env.example` documents names; real values live only in the environment."""
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    assignments = [
        line.split("=", 1)
        for line in example.splitlines()
        if "=" in line and not line.startswith("#")
    ]
    for name, value in assignments:
        if name.strip() == "RELAY_DB_PASSWORD":
            assert "local_dev_only" in value  # the API refuses to start with it outside local
            continue
        assert not re.search(r"(sk-|key-|token|secret)", value, re.IGNORECASE), name
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored
    assert ".env.*" in ignored
    assert "!.env.example" in ignored


def test_dependencies_are_locked() -> None:
    """SEC-30: both lockfiles are committed and the backend declares a pinned Python."""
    assert (REPO / "backend" / "uv.lock").is_file()
    assert (REPO / "web" / "package-lock.json").is_file()
    project = tomllib.loads((REPO / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["requires-python"].startswith(">=3.12")


@pytest.mark.parametrize("name", ["backend/Dockerfile", "web/Dockerfile"])
def test_images_are_pinned_by_digest_and_run_as_a_non_root_user(name: str) -> None:
    """SEC-31 and SEC-32."""
    text = (REPO / name).read_text(encoding="utf-8")
    froms = [line for line in text.splitlines() if line.startswith("FROM ")]
    assert froms
    for line in froms:
        image = line.split()[1]
        if image == "base":  # a stage of this same file, already pinned above
            continue
        assert "@sha256:" in image, f"{name}: {image} is not pinned by digest"
    assert re.search(r"^USER (?!root)", text, re.MULTILINE), f"{name} runs as root"
    assert not re.search(r"\b(curl|wget)\b", text), f"{name} downloads during the build"
    assert "| sh" not in text
    assert "|sh" not in text


def test_every_pulled_compose_image_is_pinned() -> None:
    """SEC-31: images this project builds are local; everything pulled is pinned by digest."""
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    images = [
        line.split("image:", 1)[1].strip()
        for line in compose.splitlines()
        if line.strip().startswith("image:")
    ]
    pulled = [image for image in images if not image.endswith(":local")]
    assert pulled
    for image in pulled:
        assert "@sha256:" in image, image

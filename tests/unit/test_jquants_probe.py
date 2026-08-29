"""The probe asks one question and stores nothing.

It exists because one unpublished field decides whether a zero-cost timing path
exists, and no amount of reading the plan page settles it. What it must not
become is an adapter: no source is approved for any use yet, and a probe that
quietly started keeping disclosures would walk straight through the gate the
review put up.

Checked against the syntax tree rather than the text. Three times today a scope
test grepped its own subject's prose and failed on the docstring explaining what
the code does not do — `urlopen(` contains `open(`, and a comment promising the
key is never printed contains `print`. A test that constrains the writing is not
testing the behaviour.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tools/jquants_probe.py"


def tree() -> ast.Module:
    return ast.parse(PROBE.read_text(encoding="utf-8"))


def called_names():
    """Every function called, as a dotted name where one can be recovered."""
    names = set()
    for node in ast.walk(tree()):
        if not isinstance(node, ast.Call):
            continue
        target, parts = node.func, []
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        if parts:
            names.add(".".join(reversed(parts)))
    return names


def literals():
    """Every string constant, which is where a URL or a field name would hide."""
    return {
        node.value
        for node in ast.walk(tree())
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def code_literals():
    """String constants that are not docstrings.

    A docstring is a constant too, and the whole point of the module docstring
    is to say what the probe does not do.
    """
    docstrings = set()
    for node in ast.walk(tree()):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    return literals() - docstrings


def test_the_probe_writes_nothing():
    """Not "writes nothing important" — nothing. A probe that persisted a
    disclosure would be capturing evidence from a source approved for no use.
    """
    called = called_names()
    for forbidden in ("open", "json.dump", "os.mkdir", "os.makedirs",
                      "shutil.copy", "pathlib.Path"):
        assert forbidden not in called, (forbidden, sorted(called))
    # Reading the network is not writing: urlopen is allowed by name, and the
    # substring check that once stood here rejected it.
    assert "urllib.request.urlopen" in called
    for name in called:
        assert not name.endswith(".write"), name
        assert not name.endswith(".write_text"), name


def test_the_key_is_read_from_the_environment_and_never_printed():
    assert "os.environ.get" in called_names()
    assert "JQUANTS_API_KEY" in code_literals()
    for node in ast.walk(tree()):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "print":
            continue
        for name in (n.id for n in ast.walk(node) if isinstance(n, ast.Name)):
            assert name != "key", ast.unparse(node)


def test_the_probe_asks_only_the_question_the_review_left_open():
    """One endpoint. A probe that swept several would be an adapter with a
    different name."""
    endpoints = {value for value in code_literals() if value.startswith("/")}
    assert endpoints == {"/fins/statements"}, endpoints


def test_it_reports_a_disclosure_time_but_never_disclosure_content():
    """A timestamp is metadata. The body is what the terms restrict, and the
    probe has no reason to show one."""
    values = code_literals()
    assert "DisclosedTime" in values and "DiscTime" in values
    for financial in ("NetSales", "OperatingProfit", "Profit", "Equity", "content"):
        assert financial not in values, financial


def test_the_probe_is_not_wired_into_the_package():
    """It lives in tools/ and is not importable as part of the library, so
    nothing that runs on its own can reach it."""
    assert PROBE.parent.name == "tools"
    assert not (ROOT / "tools/__init__.py").exists()
    for module in (ROOT / "src/earnings_research").rglob("*.py"):
        assert "jquants_probe" not in module.read_text(encoding="utf-8"), module

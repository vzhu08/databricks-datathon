"""Every module the hosted app loads must parse on the Python that Databricks Apps runs, which is older
than 3.12. Before 3.12 an f-string expression may not contain a backslash, a comment, or the quote that
opened the string; newer Pythons accept all three, so a local run cannot see the difference by itself."""
import io
import shutil
import subprocess
import sys
import tokenize
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SOURCES = sorted(path for path in APP.rglob("*.py") if "__pycache__" not in path.parts)
COMPILE = ("import sys\n"
           "bad = []\n"
           "for name in sys.argv[1:]:\n"
           "    try:\n"
           "        compile(open(name, encoding='utf-8').read(), name, 'exec')\n"
           "    except SyntaxError as error:\n"
           "        bad.append(f'{name}:{error.lineno}: {error.msg}')\n"
           "print('\\n'.join(bad))\n"
           "sys.exit(1 if bad else 0)\n")


def quote(token):
    """The quote characters that open a string or f-string token, without its prefix letters."""
    text = token.string.lstrip("rRbBuUfF")
    return text[:3] if text[:3] in ('"""', "'''") else text[:1]


def problems(source):
    """Lines where an f-string expression holds a backslash, a comment or its own opening quote.

    Uses the 3.12+ tokenizer, which splits f-strings into parts. On an older Python there is nothing to
    look for: the interpreter running the tests would already have refused the file.
    """
    start = getattr(tokenize, "FSTRING_START", None)
    if start is None:
        return []
    found, opened = [], []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == start:
            if opened and opened[-1] in quote(token):
                found.append((token.start[0], "nested f-string reuses the enclosing quote"))
            opened.append(quote(token))
        elif token.type == tokenize.FSTRING_END:
            opened.pop()
        elif opened and token.type != tokenize.FSTRING_MIDDLE:  # inside a {...} expression
            if token.type == tokenize.COMMENT:
                found.append((token.start[0], "comment inside an f-string expression"))
            elif "\\" in token.string:
                found.append((token.start[0], "backslash inside an f-string expression"))
            elif token.type == tokenize.STRING and opened[-1] in quote(token):
                found.append((token.start[0], "string inside an f-string expression reuses its quote"))
    return found


class GrammarTests(unittest.TestCase):
    def test_no_f_string_in_the_app_needs_python_312(self):
        self.assertGreater(len(SOURCES), 20)
        bad = [f"{path.relative_to(APP.parent)}:{line}: {what}"
               for path in SOURCES for line, what in problems(path.read_text(encoding="utf-8"))]
        self.assertEqual([], bad)

    @unittest.skipIf(sys.version_info < (3, 12), "needs the tokenizer that splits f-strings")
    def test_the_check_recognises_each_construct(self):
        bad = ('x = f"<tr{\' class=\\"a\\"\' if y else \'\'}>"\n',  # the line that stopped the hosted app
               'x = f"{d["k"]}"\n', "x = f'{d['k']}'\n", 'x = f"{f"{y}"}"\n', 'x = f"{"\\n".join(y)}"\n')
        for source in bad:
            with self.subTest(source=source):
                self.assertTrue(problems(source))
        good = ('x = f"<td class=\\"a\\">{d[\'k\']:,}</td>"\n', "x = f'<a href=\"{y}\">{z!r}</a>'\n",
                'x = f"""{d["k"]}"""\n', 'x = "\\n".join(f"{y}" for y in z)\n')
        for source in good:
            with self.subTest(source=source):
                self.assertEqual([], problems(source))

    def test_every_app_module_compiles_on_python_311_when_it_is_installed(self):
        old = shutil.which("python3.11") or shutil.which("python3.10")
        if sys.version_info < (3, 12):
            old = sys.executable
        if not old:
            self.skipTest("no Python older than 3.12 on this machine; the static check above still ran")
        done = subprocess.run([old, "-c", COMPILE, *map(str, SOURCES)], capture_output=True, text=True, timeout=120)
        self.assertEqual("", done.stdout.strip())
        self.assertEqual(0, done.returncode, done.stderr[-1000:])


if __name__ == "__main__":
    unittest.main()

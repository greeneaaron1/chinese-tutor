from __future__ import annotations

import python_multipart # This line is added to indicate that python-multipart is a dependency and should be installed

import contextlib
import html
import shlex
from io import StringIO

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse

from . import cli

app = FastAPI()


def _run_cli(args_text: str) -> tuple[str, int]:
    argv = shlex.split(args_text) if args_text else []
    buffer = StringIO()
    exit_code = 0
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        try:
            cli.main(argv)
        except SystemExit as exc:
            code = exc.code
            if isinstance(code, int):
                exit_code = code
            elif code is None:
                exit_code = 0
            else:
                exit_code = 1
        except Exception as exc:  # noqa: BLE001
            buffer.write(f"Error: {exc}\n")
            exit_code = 1
    return buffer.getvalue(), exit_code


def _render_page(args_value: str, output: str) -> str:
    escaped_args = html.escape(args_value or "")
    escaped_output = html.escape(output or "")
    return f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>chinese-tutor</title>
  </head>
  <body>
    <h1>chinese-tutor CLI (web)</h1>
    <form method="post">
      <label for="args">CLI arguments:</label>
      <input type="text" id="args" name="args" value="{escaped_args}" size="50" placeholder="e.g. list --limit 5" />
      <button type="submit">Run</button>
    </form>
    <h2>Output</h2>
    <pre>{escaped_output}</pre>
  </body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(_render_page(args_value="", output=""))


@app.post("/", response_class=HTMLResponse)
async def run_command(args: str = Form("")) -> HTMLResponse:
    output, exit_code = _run_cli(args)
    if exit_code:
        output = f"{output}\n(exit code {exit_code})"
    return HTMLResponse(_render_page(args_value=args, output=output))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("chinese_tutor.web:app", host="127.0.0.1", port=3000)

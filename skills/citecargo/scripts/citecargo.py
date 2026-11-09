"""Run the bundled CiteCargo CLI. Arguments stay data, never shell commands."""
import os
import sys

if not sys.flags.isolated or not sys.flags.utf8_mode:
    os.execv(sys.executable,[sys.executable,'-I','-X','utf8',os.path.abspath(__file__),*sys.argv[1:]])
from pathlib import Path
sys.dont_write_bytecode=True
import importlib.util
spec=importlib.util.spec_from_file_location('_citecargo_bootstrap',Path(__file__).with_name('bootstrap.py'))
bootstrap=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
try:
    command=bootstrap.get_cli_command()
    os.execve(command[0],[*command,*sys.argv[1:]],bootstrap._environment())
except bootstrap.BootstrapError as error:
    import json
    print(json.dumps(error.as_dict(),ensure_ascii=False))
    raise SystemExit(2)

#!/usr/bin/env python3

import sys
import yaml
import json
from subprocess import check_output, CalledProcessError

if __name__ == '__main__':
    sqcmd_path = [sys.executable, '/home/ddutt/work/suzieq/suzieq/cli/suzieq-cli']

    with open('samples/1.yml', 'r') as f:
        tests = yaml.load(f.read(), Loader=yaml.FullLoader)

    for t in tests['tests']:
        exec_cmd = sqcmd_path + t['command'].split()
        try:
            output = check_output(exec_cmd)
        except CalledProcessError as e:
            output = e.output

        jout = json.loads(output.decode('utf-8').strip())

        assert(jout == json.loads(t['output'].strip()))

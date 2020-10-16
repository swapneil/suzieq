from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Request
import logging
import uuid
import uvicorn
import argparse
import sys
import yaml
import inspect

from suzieq.sqobjects import *
from suzieq.utils import validate_sq_config


app = FastAPI()

# TODO: logging to this file isn't working
logging.FileHandler('/tmp/rest-server.log')
logger = logging.getLogger(__name__)


# for now we won't support top for REST API
#  this is because a lot of top logic is currently in commands
#  and I'm not sure what needs to get abstracted out
@app.get('/api/v1/{command}/top')
async def no_top(command: str):
    u = uuid.uuid1()
    msg = f"top not supported for {command}: id={u}"
    logger.warning(msg)
    raise HTTPException(status_code=404, detail=msg)


"""
each of these read functions behaves the same, it gets the arguments
puts them into dicts and passes them to sqobjects

assume that all API functions are named read_*
"""


@app.get("/api/v1/address/{verb}")
async def read_address(verb: str,
                       hostname: str = None,
                       start_time: str = "", end_time: str = "",
                       view: str = "latest", namespace: str = None,
                       columns: str = None, address: str = None,
                       ipvers: str = None,
                       vrf: str = None,
                       ):
    function_name = inspect.currentframe().f_code.co_name
    return read_shared(function_name, verb, locals())


@app.get("/api/v1/arpnd/{verb}")
async def read_arpnd(verb: str,
                     hostname: str = None,
                     start_time: str = "", end_time: str = "",
                     view: str = "latest", namespace: str = None,
                     columns: str = None, ipAddress: str = None,
                     macaddr: str = None,
                     oif: str = None
                     ):
    function_name = inspect.currentframe().f_code.co_name
    return read_shared(function_name, verb, locals())


def read_shared(function_name, verb, local_variables):
    """all the shared code for each of thse read functions"""

    command = function_name[5:]
    command_args, verb_args = create_filters(function_name, local_variables)

    verb = cleanup_verb(verb)

    ret, svc_inst = run_command_verb(command, verb, command_args, verb_args)
    check_args(function_name, svc_inst)
    return ret


def check_args(function_name, svc_inst):
    """make sure that all the args defined in sqobject is defined in this function"""

    arguments = inspect.getfullargspec(globals()[function_name]).args
    arguments = [i for i in arguments if i not in ['verb', 'start_time', 'end_time', 'view']]

    valid_args = set(svc_inst._valid_get_args)
    if svc_inst._valid_assert_args:
        valid_args = valid_args.union(svc_inst._valid_assert_args)

    for arg in valid_args:
        assert arg in arguments, f"{arg} missing from {function_name} arguments"

    for arg in arguments:
        assert arg in valid_args, f"extra argument {arg} in {function_name}"


def create_filters(function_name, locals):
    command_args = {}
    verb_args = {}
    remove_args = ['verb']
    possible_args = ['hostname', 'namespace', 'start_time', 'end_time', 'view', 'columns']
    split_args = ['namespace', 'columns', 'address']
    both_verb_and_command = ['namespace', 'hostname', 'columns']

    arguments = inspect.getfullargspec(globals()[function_name]).args

    for arg in arguments:
        if arg in remove_args:
            continue
        if arg in possible_args:
            if locals[arg] is not None:
                command_args[arg] = locals[arg]
                if arg in split_args:
                    command_args[arg] = command_args[arg].split()
                if arg in both_verb_and_command:
                    verb_args[arg] = command_args[arg]
        else:
            if locals[arg] is not None:
                verb_args[arg] = locals[arg]
                if arg in split_args:
                    verb_args[arg] = verb_args[arg].split()

    return command_args, verb_args


def cleanup_verb(verb):
    if verb == 'show':
        verb = 'get'
    if verb == 'assert':
        verb = 'aver'
    return verb


def create_command_args(hostname='', start_time='', end_time='', view='latest',
                        namespace='', columns='default'):
    command_args = {'hostname': hostname,
                    'start_time': start_time,
                    'end_time': end_time,
                    'view': view,
                    'namespace': namespace,
                    'columns': columns}
    return command_args


def get_svc(command):
    command_name = command

    # we almost have a consistent naming scheme, but not quite.
    # sometime there are s at the end and sometimes not
    try:
        module = globals()[command]
    except KeyError:
        command = f"{command}s"
        module = globals()[command]

    try:
        svc = getattr(module, f"{command.title()}Obj")
    except AttributeError:
        if command == 'interfaces':
            # interfaces doesn't follow the same pattern as everything else
            svc = getattr(module, 'IfObj')
        else:
            svc = getattr(module, f"{command_name.title()}Obj")
    return svc


def run_command_verb(command, verb, command_args, verb_args):
    """ 
    Runs the command and verb with the command_args and verb_args as dictionaries

    HTTP Return Codes
        404 -- Missing command or argument (including missing valid path)
        405 -- Missing or incorrect query parameters
        422 -- FastAPI validation errors
        500 -- Exceptions
    """
    svc = get_svc(command)
    try:
        svc_inst = svc(**command_args, config_file=app.cfg_file)
        df = getattr(svc_inst, verb)(**verb_args)

    except AttributeError as err:
        return_error(404, f"{verb} not supported for {command} or missing arguement: {err}")

    except NotImplementedError as err:
        return_error(404, f"{verb} not supported for {command}: {err}")

    except TypeError as err:
        return_error(405, f"bad keyword/filter for {command} {verb}: {err}")

    except ValueError as err:
        return_error(405, f"bad keyword/filter for {command} {verb}: {err}")

    except Exception as err:
        return_error(500, f"exceptional exception {verb} for {command} of type {type(err)}: {err}")

    if df.columns.to_list() == ['error']:
        return_error(405, f"bad keyword/filter for {command} {verb}: {df['error'][0]}")

    return df.to_json(orient="records"), svc_inst


def return_error(code: int, msg: str):
    u = uuid.uuid1()
    msg = f"{msg} id={u}"
    logger.warning(msg)
    raise HTTPException(status_code=code, detail=msg)


@app.get("/api/v1/{command}")
def missing_verb(command):
    u = uuid.uuid1()
    msg = f"{command} command missing a verb. for example '/api/v1/{command}/show' id={u}"
    logger.warning(msg)
    raise HTTPException(status_code=404, detail=msg)


@app.get("/")
def bad_path():
    u = uuid.uuid1()
    msg = f"bad path. you want to use something like '/api/v1/device/show' id={u}"
    logger.warning(msg)
    raise HTTPException(status_code=404, detail=msg)


def check_config_file(cfgfile):
    if cfgfile:
        with open(cfgfile, "r") as f:
            cfg = yaml.safe_load(f.read())

        validate_sq_config(cfg, sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--config",
        type=str, help="alternate config file"
    )
    userargs = parser.parse_args()
    check_config_file(userargs.config)
    app.cfg_file = userargs.config

    uvicorn.run(app, host="0.0.0.0", port=8000,
                log_level='info', )

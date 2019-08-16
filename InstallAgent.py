#!/usr/bin/env python3
###############
#  Script to:
#  1) create a launchctl plist file for local environment for desired program.
#  2) copy it to ~/Library/LaunchAgents
#  3) launch the agent
#
###############
### Python3 Library documentation   #   https://docs.python.org/3/library
import time             #   https://docs.python.org/3/library/time.html
import datetime         #   https://docs.python.org/3/library/datetime.html
from datetime import date           #   https://docs.python.org/3/library/datetime.html#date-objects
from datetime import timedelta      #   https://docs.python.org/3/library/datetime.html#timedelta-objects
from datetime import datetime as dt #   https://docs.python.org/3/library/datetime.html#datetime-objects
from datetime import time as dtime  #   https://docs.python.org/3/library/datetime.html#time-objects
import os               #   https://docs.python.org/3/library/os.html
import sys              #   https://docs.python.org/3/library/sys.html
import argparse         #   https://docs.python.org/3/library/argparse.html
import configparser     #   https://docs.python.org/3/library/configparser.html
import logging          #   https://docs.python.org/3/library/logging.html
import logging.config   #   https://docs.python.org/3/library/logging.config.html
import logging.handlers #   https://docs.python.org/3/library/logging.handlers.html
import json             #   https://docs.python.org/3/library/json.html
import shlex            #   https://docs.python.org/3/library/shlex.html
import re               #   https://docs.python.org/3/library/re.html
import shutil           #   https://docs.python.org/3/library/shutil.html
from getpass import getuser #   https://docs.python.org/3/library/getpass.html
import plistlib as PL   #   https://docs.python.org/3/library/plistlib.html
from pathlib import Path    #   https://docs.python.org/3/library/pathlib.html#module-pathlib
import base64           #   https://docs.python.org/3/library/base64.html

ProgName, ext = os.path.splitext(os.path.basename(sys.argv[0]))
ProgPath = os.path.dirname(os.path.realpath(sys.argv[0]))

#####  Setup logging; first try for file specific, and if it doesn't exist, use a folder setup file.
logConfFileName = os.path.join(ProgPath, ProgName + '_loggingconf.json')
if not os.path.isfile(logConfFileName):
    logConfFileName = os.path.join(ProgPath, 'Loggingconf.json')
if os.path.isfile(logConfFileName):
    try:
        with open(logConfFileName, 'r') as logging_configuration_file:
            config_dict = json.load(logging_configuration_file)
        if 'log_file_path' in config_dict:
            logPath = os.path.expandvars(config_dict['log_file_path'])
            os.makedirs(logPath, exist_ok=True)
        else:
            logPath=""
        for p in config_dict['handlers'].keys():
            if 'filename' in config_dict['handlers'][p]:
                fn = os.path.join(logPath, config_dict['handlers'][p]['filename'].replace('<replaceMe>', ProgName))
                config_dict['handlers'][p]['filename'] = fn
                # print('Setting handler %s filename to: %s'%(p, fn))

        # # program specific logging configurations:
        config_dict["handlers"]["debugconsole"]["level"] = 'NOTSET'
        # # config_dict["handlers"]["debug_file_handler"]["class"] = 'logging.FileHandler'
        # config_dict["handlers"]["debug_file_handler"]["mode"] = '\'w\''

        logging.config.dictConfig(config_dict)
    except Exception as e:
        print("loading logger config from file failed.")
        print(e)
        pass
else:
    print("Logging configuration file not found.")

logger = logging.getLogger(__name__)
logger.info('logger name is: "%s"', logger.name)

#######################   GLOBALS   ########################

myDomain = 'net.demayfamily'
HomePath = os.path.expandvars('$HOME')
PlistFileDir = os.path.join(HomePath, 'Library', 'LaunchAgents')
PrevTimeStamp = int(time.time()*1000000)    # current microsec since epoch

#######################   FUNCTIONS   ########################

#############  getTargetExecutable
def getTargetExecutable(targetProgFile):

    #########  getPythonExecutable
    def getPythonExecutable():
        return os.path.realpath(sys.executable)

    #########  getBashExecutable
    def getBashExecutable():
        try:
            path = shutil.which('bash')
        except:
            logger.warning('Attempt to get path to bash failed.')
            return None
        path = os.path.realpath(path)
        logger.debug('Path to bash executable is: "%s"'%path)
        return path

    knownExecutables = {
        '.py': getPythonExecutable
        , '.sh': getBashExecutable
        , '': getBashExecutable         #  Assume no extension => bash
        }

    _, targetProgExt = os.path.splitext(os.path.basename(targetProgFile))
    if targetProgExt == "":         # targetProgExt is empty, try first line of file to get kind
        with open(targetProgFile) as fp:
            l = fp.readline().rstrip()  # first line of file with trailing white space removed.
            m = re.search(r'^#!.*?(\w+$)', l)    # if line starts with "#!" get last word on line.
            if m is not None:
                targetProgExt = m[1]
                if 'python' in targetProgExt:
                    targetProgExt = '.py'
                elif 'sh' in targetProgExt:
                    targetProgExt = '.sh'
                else:
                    targetProgExt = 'unknown'
            ## leave targetProgExt as empty => bash
            # else:
            #     targetProgExt = 'unknown'
    if targetProgExt not in knownExecutables:
        logger.warning("I don't know how to find an executable for extension: '%s'"%targetProgExt)
        raise UserWarning("I don't know how to find an executable for extension: '%s'"%targetProgExt)
    return knownExecutables[targetProgExt]()

#############  removeCurrentAgent
def removeCurrentAgent(targetProgName):
    '''
    Unloads ALL loaded agents with our domain and the target file name.
    Deletes associated .plist files from ${HOME}/Library/LaunchAgents.

    targetProgName is the name of the executable without the path or extension.
    '''
    logger.debug('----- Remove ALL agents with domain "%s" and name "%s".'%(myDomain, targetProgName))
    pfd=Path(PlistFileDir)
    plistFiles= list(pfd.glob(myDomain + '*' + targetProgName + '.plist'))
    for plistFileName in plistFiles:
        logger.info('Stopping, removing Agent: "%s"'%plistFileName)
        logger.debug('Launchctl stop service.')
        retCode = os.system('launchctl stop %s'%plistFileName)
        logger.debug('Launchctl "stop" exited with status: %s, now unload service.'%retCode)
        retCode = os.system('launchctl unload %s'%plistFileName)
        logger.debug('Launchctl "unload" exited with status: %s, now delete plist file.'%retCode)
        try:
            os.remove(plistFileName)
            logger.debug('Removed file "%s"'%plistFileName)
        except:
            logger.debug('Attempted removal of "%s" did not succeed.'%plistFileName)
            pass

#############  main
def main():
    global PrevTimeStamp

    plistDict =  {  'Label': '{myDomain}.{progName}',
                    'Umask': '0002',
                    'ProgramArguments': ['{executablePath}', '{progFile}'],
                    'RunAtLoad': True,
                    'KeepAlive': True,
                    'WorkingDirectory': '{progPath}',
                    'StandardErrorPath': '{HomePath}/Logs/{progName}/error.log',
                    'StandardOutPath': '{HomePath}/Logs/{progName}/output.log',
                    'EnvironmentVariables': {}
                }
    labelTemplate = '{myDomain}.{UID}.{targetProgName}'

    parser = argparse.ArgumentParser(description = 'Install user level agent and start it.',
        epilog='''The target program is expected to run indefinitely (default) or as defined by additional launchctl args.''')
    parser.add_argument("target", help="Target program and command line arguments for the target.")
    parser.add_argument("--IAR", "--IARemove", dest="remove", action="store_true", help="Stops agent, unloads agent, deletes agent's plist file.  Other flags ignored.")
    parser.add_argument("--IAk", "--IAkeepAlive", dest="keepAlive", action="store_true", help="Sets KeepAlive flag in plist to true.")
    parser.add_argument("--IAl", "--IAnotRunAtLoad", dest="runAtLoad", action="store_false", default=True, help="Sets RunAtLoad flag in plist to FALSE.")
    parser.add_argument("--IAW", "--IAdontWriteFile", dest="noWrite", action="store_true", help="Don't write the output file.")
    parser.add_argument("--IAX", "--IAdontStartAgent", dest="noStart", action="store_true", help="Don't invoke launchctl to load Agent.")
    parser.add_argument("--IAa", "--IAadditions", dest="additions", action="store", help="Additional launchctl plist items encoded as JSON list.")
    parser.add_argument("--IAe", "--IAenvironment", dest="environment", action="store", default='["HOST", "PrivateConfig", "HOME", "PATH"]',
                        help="List of environment variables to copy to target environment.")
    allargs = parser.parse_known_args()
    args = allargs[0]
    clientArgs = allargs[1]
    logger.debug('Client args are: %s'%clientArgs)

    targetProgFile = os.path.realpath(args.target)
    if not os.path.exists(targetProgFile):
        logger.critical('The target file \"%s\" does not exist.'%targetProgFile)
        return(1)
    if os.stat(targetProgFile).st_mode & 0O100 == 0:
        logger.critical('The target file \"%s\" is not executable.'%targetProgFile)
        return(2)
    targetProgPath = os.path.dirname(targetProgFile)
    targetProgName, targetProgExt = os.path.splitext(os.path.basename(targetProgFile))

    logger.debug('AbsolutePath of home directory is "%s"'%HomePath)
    logger.debug('Absolute path to target "%s"'%targetProgFile)
    logger.debug('Absolute path of target directory "%s"'%targetProgPath)
    logger.debug('Program name is "%s", the extension is "%s"'%(targetProgName, targetProgExt))
    timeStamp = int(time.time()*1000000)    # current microsec since epoch
    if timeStamp == PrevTimeStamp:
        #    If we're on a system that has only 1 second resolution for time since epoch,
        # make the timestamp unique by adding 1 microsec to the previous timestamp.
        timeStamp = PrevTimeStamp + 1
    PrevTimeStamp = timeStamp
    UID = base64.urlsafe_b64encode(timeStamp.to_bytes((timeStamp.bit_length() + 7)//8,'big')).strip(b'=').decode('UTF-8')
    label = labelTemplate.format(myDomain=myDomain, UID=UID, targetProgName=targetProgName)
    plistDict['Label'] = label

    # Remove current agent.
    removeCurrentAgent(targetProgName)

    ####   Remove option processing.
    if args.remove:
        return(0)
    ####    Finished removing

    plistFileName = os.path.join(PlistFileDir, label + '.plist')
    logger.debug('  Destination for plist file is: "%s"'%plistFileName)
    try:
        executablePath = getTargetExecutable(targetProgFile)
    except Exception as e:
        logger.exception(e)
        raise

    logger.debug('The path to the executable is "%s"'%executablePath)
    plistDict['ProgramArguments'][0] = executablePath
    plistDict['ProgramArguments'][1] = targetProgFile

    for ca in clientArgs:
        # logger.debug('Processing client arg: %s'%ca)
        plistDict['ProgramArguments'] += [ca]
        # logger.debug('ProgramArguments item is now: %s'%plistDict['ProgramArguments'])

    try:
        if args.additions is not None:
            additionalItems = json.loads(args.additions)
            if not isinstance(additionalItems, list):
                raise UserWarning('Additional items must be a list.')
            for thisItem in additionalItems:
                if not isinstance(thisItem, dict):
                    raise UserWarning('Each additional item must be a dict.')
                logger.debug('Adding item: "%s" to plist dictionary.'%thisItem)
                plistDict.update(thisItem)
    except UserWarning as w:
        logger.exception(w)
    except Exception as e:
        logger.critical('JSON for additional items is malformed.')
        logger.exception(e)

    logger.debug('Environment variables to copy to target environment (as str): %s'%args.environment)
    try:
        envVars = json.loads(args.environment)
        logger.debug('Environment variables to copy to target environment: %s'%envVars)
    except Exception as e:
        logger.exception(e)
        return(4)

    for k in envVars:
        plistDict['EnvironmentVariables'][k] = os.environ[k]

    targetLogPath = os.path.join(HomePath, 'Logs', targetProgName)
    plistDict['RunAtLoad'] = args.runAtLoad
    plistDict['KeepAlive'] = args.keepAlive
    plistDict['WorkingDirectory'] = targetProgPath
    plistDict['StandardOutPath'] = os.path.join(targetLogPath, 'output.log')
    plistDict['StandardErrorPath'] = os.path.join(targetLogPath, 'error.log')

    plistContents = PL.dumps(plistDict, sort_keys = False).decode('UTF-8')
    logger.debug('Contents of plist file are to be:\n%s'%plistContents)
    if args.noWrite:
        logger.info('Plist file NOT written to LanchAgents NOR started.')
    else:
        # launchctl creates the StandardErrorPath and StandardOutPath as owned by root.
        # Then when the program starts and tries to write to the files, startup fails.
        #   If the directories already exist, launchctl leaves them alone.
        os.makedirs(targetLogPath, exist_ok=True)

        with open(plistFileName, mode='w') as f:
            numChars = f.write(plistContents)
            logger.debug('Wrote %s chars to plist file.'%numChars)
            # try:
            #     userName = getuser()
            #     logger.debug('Set user to "%s", group to "wheel"'%userName)
            #     shutil.chown(plistFileName, user=userName, group='wheel')
            # except:
            #     logger.debug('Attempt to set group on plist file failed.')
            #     pass
        if args.noStart:
            logger.info('Plist file written, but launchctl not called.')
        else:
            logger.debug('Do launchctl load of %s.'%plistFileName)
            retCode = os.system('launchctl load %s'%plistFileName)
            logger.debug('Launchctl "load" exited with status: %s.'%retCode)
            pass


if __name__ == "__main__":
    logger.info('######################  InstallAgent starts #####################')
    status = main()
    if status == None:
        status = 0
    logger.info('######################  InstallAgent all done with status: %s #####################'%status)
    logging.shutdown()
    pass

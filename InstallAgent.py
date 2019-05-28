#!/usr/bin/env python3
###############
#  Script to:
#  1) create a launchctl plist file for local environment for desired program.
#  2) copy it to ~/Library/LaunchAgents
#  3) launch the agent
#
###############

import os
import argparse
import sys
import time
import configparser
import logging
import logging.config
import logging.handlers
import json
from getpass import getuser as getuser
import shutil

ProgName, ext = os.path.splitext(os.path.basename(sys.argv[0]))
ProgPath = os.path.dirname(os.path.realpath(sys.argv[0]))
logConfFileName = os.path.join(ProgPath, ProgName + '_loggingconf.json')
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
                config_dict['handlers'][p]['filename'] = os.path.join(logPath, config_dict['handlers'][p]['filename'])
        logging.config.dictConfig(config_dict)
    except Exception as e:
        print("loading logger config from file failed.")
        print(e)
        pass

logger = logging.getLogger(__name__)
logger.info('logger name is: "%s"', logger.name)

def getPythonExecutable():
    return os.path.realpath(sys.executable)

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

'''     Unsupported plist keys (for user agents):
  <key>UserName</key>
  <string>{userName}</string>
  <key>GroupName</key>
  <string>{groupName}</string>
'''
plistTemplate = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{myDomain}.{progName}</string>
  <key>Umask</key>
  <string>0002</string>
  <key>ProgramArguments</key>
  <array>
    <string>{executablePath}</string>
    <string>{progFile}</string>{additionalArgs}
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <{keepAlive}/>
  <key>WorkingDirectory</key>
  <string>{progPath}</string>
  <key>StandardErrorPath</key>
  <string>{homePath}/Logs/{progName}/error.log</string>
  <key>StandardOutPath</key>
  <string>{homePath}/Logs/{progName}/output.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOST</key>
    <string>{host}</string>
    <key>PrivateConfig</key>
    <string>{PrivateConfig}</string>
    <key>HOME</key>
    <string>{homePath}</string>
    <key>PATH</key>
    <string>{PATH}</string>
  </dict>
</dict>
</plist>
'''
myDomain = 'net.demayfamily'

def main():
    parser = argparse.ArgumentParser(description = 'Install user level agent and start it.',
        epilog='''The target program is expected to run indefinitely.''')
    parser.add_argument("target", help="Target program")
    parser.add_argument("--IAR", "--IARemove", dest="remove", action="store_true", help="Stops agent, unloads agent, deletes agent's plist file.  Other flags ignored.")
    parser.add_argument("--IAk", "--IAkeepAlive", dest="keepAlive", action="store_true", help="Sets KeepAlive flag in plist to true.")
    parser.add_argument("--IAW", "--IAdontWriteFile", dest="noWrite", action="store_true", help="Don't write the output file.")
    parser.add_argument("--IAX", "--IAdontStartAgent", dest="noStart", action="store_true", help="Don't invoke launchctl to load Agent.")
    allargs = parser.parse_known_args()
    args = allargs[0]
    clientArgs = allargs[1]

    progFile = os.path.realpath(args.target)
    logger.debug('Absolute path to target "%s"'%progFile)
    progPath = os.path.dirname(progFile)
    logger.debug('Absolute path of target directory "%s"'%progPath)
    progName, ext = os.path.splitext(os.path.basename(progFile))
    logger.debug('Program name is "%s", the extension is "%s"'%(progName, ext))
    homePath = os.path.expandvars('$HOME')
    logger.debug('AbsolutePath of home directory is "%s"'%homePath)
    plistFileName = os.path.join(homePath
        , 'Library'
        , 'LaunchAgents'
        , '{myDomain}.{progName}.plist'.format(myDomain = myDomain, progName = progName))
    logger.debug('Destination for plist file is: "%s"'%plistFileName)

    if args.remove:
        if os.path.exists(plistFileName):
            logger.info('Stopping, removing Agent.')
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
        else:
            logger.info('Plist file "%s" does not exist; nothing to do.'%plistFileName)
        return
    if ext not in knownExecutables:
        logger.warning("I don't know how to find an executable for extension: '%s'"%ext)
        return 1

    executablePath = knownExecutables[ext]()
    logger.debug('The path to the executable is "%s"'%executablePath)

    additionalArgs = ""
    for ca in clientArgs:
        additionalArgs += '\n    <string>%s</string>'%ca
    userName = getuser()
    groupName = os.getgroups()[0]
    keepAlive = 'true' if args.keepAlive else 'false'
    host = os.environ['HOST']
    PATH = os.environ['PATH']
    # launchctl creates the StandardErrorPath and StandardOutPath as owned by root.
    # Then when the program starts and tries to write to the files, startup fails.
    #   If the directories already exist, launchctl leaves them alone.
    os.makedirs('{homePath}/Logs/{progName}'.format(homePath=homePath, progName=progName), exist_ok=True)
    PrivateConfig = os.environ['PrivateConfig']
    plistContents = plistTemplate.format(myDomain = myDomain,
                progName = progName,
                userName = userName,
                groupName = groupName,
                progFile = progFile,
                progPath = progPath,
                executablePath = executablePath,
                homePath = homePath,
                additionalArgs = additionalArgs,
                PATH = PATH,
                host = host,
                PrivateConfig = PrivateConfig,
                keepAlive = keepAlive)
    logger.debug('Contents of plist file are to be:\n%s'%plistContents)
    if args.noWrite:
        logger.info('Plist file NOT written to LanchAgents NOR started.')
    else:
        with open(plistFileName, mode='w') as f:
            numChars = f.write(plistContents)
            logger.debug('Wrote %s chars to plist file.  Now set group to "wheel"'%numChars)
            try:
                shutil.chown(plistFileName, user=userName, group='wheel')
            except:
                logger.debug('Attempt to set group on plist file failed.')
                pass
        if args.noStart:
            logger.info('Plist file written, but launchctl not called.')
        else:
            logger.debug('Launchctl stop service (fails if not running).')
            retCode = os.system('launchctl stop %s'%plistFileName)
            logger.debug('Launchctl "stop" exited with status: %s, now unload service.'%retCode)
            retCode = os.system('launchctl unload %s'%plistFileName)
            logger.debug('Launchctl "unload" exited with status: %s, now load service.'%retCode)
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

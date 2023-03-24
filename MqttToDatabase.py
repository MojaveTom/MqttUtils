#!/usr/bin/env python3.11

import mysql.connector
from mysql.connector import Error as SqlError
import time
from datetime import datetime as dt #   https://docs.python.org/3/library/datetime.html#datetime-objects
from datetime import timezone       #   https://docs.python.org/3/library/datetime.html#date-objects
from datetime import time as dtime  #   https://docs.python.org/3/library/datetime.html#time-objects
from datetime import timedelta      #   https://docs.python.org/3/library/datetime.html#timedelta-objects
import os               #   https://docs.python.org/3/library/os.html
import sys              #   https://docs.python.org/3/library/sys.html
import re               #   https://docs.python.org/3/library/re.html
import argparse         #   https://docs.python.org/3/library/argparse.html
import paho.mqtt.client as mqtt     #   https://www.eclipse.org/paho/clients/python/docs/
import paho.mqtt.publish as publish
import configparser
import logging
import logging.config
import logging.handlers
import json

from prodict import Prodict             #   https://github.com/ramazanpolat/prodict
from progparams.ProgramParametersDefinitions import MakeParams
from progparams.GetLoggingDict import GetLoggingDict, setConsoleLoggingLevel, setLogFileLoggingLevel, getConsoleLoggingLevel, getLogFileLoggingLevel

ProgName, ext = os.path.splitext(os.path.basename(sys.argv[0]))
ProgPath = os.path.dirname(os.path.realpath(sys.argv[0]))

##############Logging Settings##############
config_dict = GetLoggingDict(ProgName, ProgPath)
logging.config.dictConfig(config_dict)

logger = logging.getLogger(__name__)
logger.info('logger name is: "%s"', logger.name)

console = logger

debug = logger.debug
info = logger.info
critical = logger.critical

logger.level = logging.DEBUG

########################  GLOBALS
PP = Prodict()

DBConn = None
DBCursor = None
dontWriteDb = False
Topics = set()    # default topics to subscribe
mqtt_msg_table = None
RequiredConfigParams = frozenset((   'inserter_user',
                                     'inserter_password',
                                     'inserter_host',
                                     'inserter_port',
                                     'inserter_schema',
                                     'mqtt_host',
                                     'mqtt_port',
                                     'mqtt_msg_table'))

magicQuitPath = os.path.expandvars('${HOME}/.Close%s'%ProgName)     # Don't use f'...' string since ${HOME} confuses the formatter.

'''
mqttmessages table creation:
CREATE TABLE `mqttmessages` (
  `RecTime` timestamp(6) NOT NULL DEFAULT current_timestamp(6),
  `topic` tinytext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `message` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  PRIMARY KEY (`RecTime`),
  UNIQUE KEY `RecTime` (`RecTime`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_general_ci;

mqttdevice table creation:
CREATE OR REPLACE TABLE `mqttdevices` (
  `deviceid` char(64) NOT NULL,
  `statustime` varchar(30) DEFAULT NULL,
  `message` varchar(511) DEFAULT NULL,
  PRIMARY KEY (`deviceid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_general_ci;
'''

# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    global Topics
    if rc == mqtt.MQTT_ERR_SUCCESS:
        debug('Connected with result code %s',str(rc))
    else:
        logger.error('Connected with error code %s',str(rc))

    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    try:
        debug(f"Subscribing to topic(s): {Topics}")
        (result, mid) = client.subscribe(list(zip(Topics,[0]*len(Topics))))
        debug('Subscription result: %s, message id is: %s', result, mid)
    except Exception as e:
        logger.exception(e)

# The callback for when a PUBLISH message is received from the server.
def on_message(client, UsersData, msg):
    global Topics, DBConn, DBCursor, PP
    debug('in on_message: client "%s", UsersData "%s", msg "%s"', client, UsersData, msg)
    decodedMsg = msg.payload.decode("utf-8")
    msgTopic = str(msg.topic)
    debug(f'Recieved topic "{msgTopic}", Recieved message {decodedMsg}, retained? {msg.retain}')
            # check for quit condition
    if os.path.exists(magicQuitPath):
        debug(f'Quitting because magic file ("{magicQuitPath}") exists.')
        debug('Delete magic file.')
        os.remove(magicQuitPath)
        info('####################  MqttToDatabase quits  #####################')
        exit(0)

    schema = PP.get('DbSchema')     # Handy names for important items
    table = PP.get('MsgTable')
            # For some of my ESP8266 machines, the retain flag is not consistently getting set.
    if msg.retain == 0 and not msgTopic.endswith('/status'):     # => not a retained message
        if schema is not None and table is not None:
            SqlInsert = f"""INSERT INTO `{schema}`.`{table}` SET topic='{msgTopic}', message='{decodedMsg}'"""
            if not dontWriteDb:
                try:
                    DBCursor.execute(SqlInsert)
                    if DBConn.in_transaction: DBConn.commit()
                except SqlError as e:
                    logger.exception("Exception when inserting a message.")
                    logger.exception("SqlError message is: %s", e.msg)
                finally:
                    info(f'Inserted message: "{SqlInsert}"')      # After execute SQL; want to minimize time between msg received and insert
            else:
                info('Query NOT executed: "%s".'%SqlInsert)
        else:
            debug(f'Sql insert message query NOT executed because either the MsgTable or the DBSchema was not defined.')

    else:       # Retained message -- ignored if not a known status message
        debug(f'Retained message received.')
        try:
            msgDict = json.loads(msg.payload)
            debug(f'The message payload was successfully decoded to a python object.  {msgDict}')
        except json.JSONDecodeError as e:
            debug(f'The retained message payload was not valid JSON, so it is ignored.')
            # logger.exception(e)
            return              # Ignore retained messages that are not valid JSON.
        deviceId = None
        statusTime = None
        if msgTopic.endswith('status'):   # Presumably this is one of my devices.
            debug(f"Retained message topic ends with 'status'.")
            deviceId = msgDict.get('MachineID')
            if deviceId is None:
                debug(f'"{msg.payload}" does not contain a MachineID field;  reject message.')
                return
            statusTime = msgDict.get('StatusTime')
            if statusTime is None:
                debug(f'"{msg.payload}" does not contain a StatusTime field;  reject message.')
                return

            thisDeviceTopic = f'{deviceId}/#'
            if thisDeviceTopic not in Topics:
                try:
                    debug(f"Subscribing to topic from status message: {thisDeviceTopic}")
                    (result, mid) = client.subscribe(thisDeviceTopic)
                    debug(f'Subscription result: {result}, message id is: {mid}')
                except Exception as e:
                    logger.exception(e)
            Topics.add(thisDeviceTopic)
        
        if msgTopic.startswith('homeassistant') and msgTopic.endswith('config'):   # Presumably this is a homeassistant config message.
            debug(f"Retained message is a homeassistant config message.")
            deviceId = msgDict.get('uniq_id')
            if deviceId is None:
                debug(f'"{decodedMsg}" does not contain a "uniq_id" field;  reject message.')
                return
            statusTime = dt.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z (%Z)")  # use now time since homeassistant config messages don't have a time.
            if statusTime is None:
                debug(f'Could not fake a status time; reject message.')
                return

        table = PP.get('DeviceTable')
        if schema is not None and table is not None and deviceId is not None and statusTime is not None:    # we have everything we need to insert into the DeviceTable.
            SqlInsert = f"""INSERT INTO `{schema}`.`{table}` SET deviceid='{deviceId}', message='{decodedMsg}', statustime='{statusTime}' ON DUPLICATE KEY UPDATE statustime=VALUES(statustime), message=VALUES(message)"""
            info(SqlInsert)
            if not dontWriteDb or PP.get('OnlyWriteDevices', False):
                try:
                    DBCursor.execute(SqlInsert)
                    if DBConn.in_transaction: DBConn.commit()
                except SqlError as e:
                    logger.exception("Exception when inserting a device.")
                    logger.exception("SqlError message is: %s", e.msg)
            else:
                info(f'''Query NOT executed: "{SqlInsert}".''')
        else:
            debug(f'Not all fields for device table insert are defined.')
            debug(f'schema "{schema}", table "{table}", deviceId "{deviceId}", statusTime "{statusTime}"')

def on_subscribe(client, userdata, mid, granted_qos):
    debug(f'On subscribe callback, mid = {mid}, userdata = "{userdata}"')
    pass

MqttClient = mqtt.Client()


def main():
    global Topics, mqtt_msg_table, DBConn, DBCursor, dontWriteDb, MqttClient, PP

    kwargs = {}
    cfg = MakeParams( **kwargs)
    # setConsoleLoggingLevel(helperFunctionLoggingLevel)      # in case function changed it.
    if cfg is None:
        critical(f"Could not create parameters.  Must quit.")
        return
    else:
        args = Prodict.from_dict(cfg)
        debug(f"MakeParams returns non None dictionary, so args (and PP) become: {args}")
        PP = Prodict.from_dict(cfg)

    dontWriteDb = cfg['DontWriteDb'] or cfg['OnlyWriteDevices']

    db_user = cfg['DbUser']
    db_pwd  = cfg['DbPass']
    db_host = cfg['DbHost']
    db_port = int(cfg['DbPort'])
    myschema = cfg['DbSchema']

    mqtt_host = cfg['MqttHost']
    mqtt_port = cfg['MqttPort']
    mqtt_msg_table  = cfg['MsgTable']

    t = cfg['Topic']
    debug('Topics from config is: "%s".', t)
    t = t.split()
    debug('Split topics from config is: "%s".', t)
    Topics = set(t)
    debug('Topics from config is: "%s".', Topics)

    # if len(Topics) <= 0:
    #     critical('No mqtt subscription topics given or found.  Must exit.')
    #     sys.exit(4)

    info('Database connection args: host: "%s", port: %d, User: "%s", Pass: REDACTED, Schema: "%s"', db_host, db_port, db_user, myschema)
    info('Mqtt parameters:  host: "%s", port: %d, topic(s): "%s", mqtt msg table: "%s".', mqtt_host, mqtt_port, Topics, mqtt_msg_table)

    MqttClient.on_connect = on_connect
    MqttClient.on_message = on_message
    MqttClient.on_subscribe = on_subscribe

    if not dontWriteDb or PP.get('OnlyWriteDevices', False):
        try:
            DBConn = mysql.connector.connect(host=db_host,
                port=db_port,
                user=db_user,
                password= db_pwd,
                db=myschema,
                charset='utf8mb4')
            if DBConn.is_connected():
                info('Connected to MySQL database')
                info(DBConn)
                DBConn.start_transaction()
                DBCursor = DBConn.cursor()
            else:
                logger.error('Failed to connect to database.')
                DBConn = None
                DBCursor = None
        except SqlError as e:
            critical(e)
            DBConn = None
            DBCursor = None

    Topics.add('+/status')          # Make sure there is a topic to get status messages.
    debug(f'The initial set of topics is {Topics}')

    try:
        MqttClient.connect(mqtt_host, mqtt_port, 60)
        MqttClient.loop_forever()
    except Exception as e:
        logger.exception(e)
    finally:
        MqttClient.disconnect()
        if DBConn is not None:
            DBConn.disconnect()

if __name__ == "__main__":
    info(f'####################  MqttToDatabase starts @{datetime.now()}  #####################')
    try:
        main()
    except:
        pass     # On any exception, sleep awhile, then quit.  Launchctl will restart.
    info('Main returned; program errored somehow.  Wait 10 min, then quit -- Launchctl will restart us.')
    time.sleep(600)
    info(f'####################  MqttToDatabase all done @{datetime.now()}  #####################')
    logging.shutdown()
    pass

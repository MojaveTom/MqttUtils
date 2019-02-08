#!/usr/bin/env python3

import mysql.connector
from mysql.connector import Error
import time
import datetime
from datetime import date
from datetime import timedelta
from datetime import datetime
import os
import argparse
import sys
import time
import paho.mqtt.client as mqtt
import configparser
import logging
import logging.config
import logging.handlers
import json

ProgName, ext = os.path.splitext(os.path.basename(sys.argv[0]))
ProgPath = os.path.dirname(sys.argv[0])
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

DBConn = None
DBCursor = None
Topics = []    # default topics to subscribe
mqtt_msg_table = None
RequiredConfigParams = frozenset(('inserter_user', 'inserter_password', 'inserter_host', 'inserter_port', 'inserter_schema', 'mqtt_host', 'mqtt_port', 'mqtt_msg_table'))

def GetConfigFilePath():
    fp = os.path.join(ProgPath, 'secrets.ini')
    if not os.path.isfile(fp):
        fp = os.environ['PrivateConfig']
        if not os.path.isfile(fp):
            logger.error('No configuration file found.')
            sys.exit(1)
    logger.info('Using configuration file at: %s', fp)
    return fp
    

# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    global Topics, DBConn, DBCursor
    if rc == mqtt.MQTT_ERR_SUCCESS:
        logger.debug('Connected with result code %s',str(rc))
    else:
        logger.error('Connected with error code %s',str(rc))

    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    try:
        logger.debug("Subscribing to topic(s): %s", Topics)
        (result, mid) = client.subscribe(list(zip(Topics,[0]*len(Topics))))
        logger.debug('Subscription result: %s, message id is: %s', result, mid)
    except Exception as e:
        logger.exception(e)

# The callback for when a PUBLISH message is received from the server.
def on_message(client, UsersData, msg):
    global Topics, mqtt_msg_table, DBConn, DBCursor
    logger.debug('in on_message: client "%s", UsersData "%s", msg "%s"', client, UsersData, msg)
    logger.debug('Recieved topic "%s", Recieved message "%s", retained? %s', msg.topic, msg.payload.decode('utf-8'), msg.retain)
    if msg.retain == 0:     # => not a retained message
        SqlInsert = "INSERT INTO {table} SET topic='{topic}', message='{message}'".format(table=mqtt_msg_table, topic=msg.topic, message=msg.payload.decode('utf-8'))
        try:
            DBCursor.execute(SqlInsert)
            if DBConn.in_transaction: DBConn.commit()
            pass
        except Error as e:
            logger.exception("Exception when inserting a message.")
            logger.exception("Error message is: %s", e.msg)
        finally:
            logger.info(SqlInsert)      # After execute SQL; want to minimize time between msg received and insert
            pass

def on_subscribe(client, userdata, mid, granted_qos):
    logger.debug('On subscribe callback, mid = %s, userdata = "%s"', mid, userdata)
    pass

logger.info("MqttToDatabase starts")

RecClient = mqtt.Client()
RecClient.on_connect = on_connect
RecClient.on_message = on_message
RecClient.on_subscribe = on_subscribe


def main():
    global Topics, mqtt_msg_table, DBConn, DBCursor
    parser = argparse.ArgumentParser(description = 'Log MQTT messages to database.')
    parser.add_argument("-t", "--topic", dest="topic", action="append", help="MQTT topic to which to subscribe.  May be specified multiple times.")
    parser.add_argument("-o", "--host", dest="MqttHost", action="store", help="MQTT host", default=None)
    parser.add_argument("-p", "--port", dest="MqttPort", action="store", help="MQTT host port", type=int, default=None)
    parser.add_argument("-O", "--Host", dest="DbHost", action="store", help="Database host", default=None)
    parser.add_argument("-P", "--Port", dest="DbPort", action="store", help="Database host port", type=int, default=None)
    parser.add_argument("-U", "--User", dest="DbUser", action="store", help="Database user name", default=None)
    parser.add_argument("-W", "--Password", dest="DbPass", action="store", help="Database user password", default=None)
    parser.add_argument("-S", "--Schema", dest="DbSchema", action="store", help="Database schema", default=None)
    parser.add_argument("-T", "--MsgTable", dest="MsgTable", action="store", help="Database table in which to store messages.", default=None)
    args = parser.parse_args()

    config = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
    configFile = GetConfigFilePath()

    config.read(configFile)
    cfgSection = os.path.basename(sys.argv[0])+"/"+os.environ['HOST']
    logger.info("INI file cofig section is: %s", cfgSection)
    if not config.has_section(cfgSection):
        logger.critical('Config file "%s", has no section "%s".', configFile, cfgSection)
        sys.exit(2)
    if set(config.options(cfgSection)) < RequiredConfigParams:
        logger.critical('Config  section "%s" does not have all required params: "%s", it has params: "%s".', cfgSection, RequiredConfigParams, set(config.options(cfgSection)))
        sys.exit(3)

    cfg = config[cfgSection]

    db_user = cfg['inserter_user']
    db_pwd  = cfg['inserter_password']
    db_host = cfg['inserter_host']
    db_port = int(cfg['inserter_port'])
    myschema = cfg['inserter_schema']

    mqtt_host = cfg['mqtt_host']
    mqtt_port = cfg['mqtt_port']
    mqtt_msg_table  = cfg['mqtt_msg_table']

    if config.has_option(cfgSection, 'mqtt_topics'):
        t = cfg['mqtt_topics']
        logger.debug('Topics from config is: "%s".', t)
        t = t.split()
        logger.debug('Split topics from config is: "%s".', t)
        Topics = t
        logger.debug('Topics from config is: "%s".', Topics)

    if (args.topic != None) and (len(args.topic) > 0): Topics = args.topic
    if (args.MqttHost != None) and (len(args.MqttHost) > 0): mqtt_host = args.MqttHost
    if (args.MqttPort != None) and (len(args.MqttPort) > 0): mqtt_port = args.MqttPort
    if (args.MsgTable != None) and (len(args.MsgTable) > 0): mqtt_msg_table = args.MsgTable
    if (args.DbHost != None) and (len(args.DbHost) > 0): db_host = args.DbHost
    if (args.DbPass != None) and (len(args.DbPass) > 0): db_pwd = args.DbPass
    if (args.DbUser != None) and (len(args.DbUser) > 0): db_user = args.DbUser
    if (args.DbPort != None) and (len(args.DbPort) > 0): db_port = args.DbPort
    if (args.DbSchema != None) and (len(args.DbSchema) > 0): myschema = args.DbSchema
    db_port = int(db_port)
    mqtt_port = int(mqtt_port)

    if len(Topics) <= 0:
        logger.critical('No mqtt subscription topics given.  Must exit.')
        sys.exit(4)
    
    logger.info('Database connection args: host: "%s", port: %d, User: "%s", Pass: REDACTED, Schema: "%s"', db_host, db_port, db_user, myschema)
    logger.info('Mqtt parameters:  host: "%s", port: %d, topic(s): "%s", mqtt msg table: "%s".', mqtt_host, mqtt_port, Topics, mqtt_msg_table)

    try:
        DBConn = mysql.connector.connect(host=db_host,
            port=db_port,
            user=db_user,
            password= db_pwd,
            db=myschema,
            charset='utf8mb4')
        if DBConn.is_connected():
            logger.info('Connected to MySQL database')
            logger.info(DBConn)
            DBConn.start_transaction()
            DBCursor = DBConn.cursor()
            try:
                RecClient.connect(mqtt_host, mqtt_port, 60)
                RecClient.loop_forever()
            except Exception as e:
                logger.exception(e)
            finally:
                RecClient.disconnect()
                DBConn.disconnect()
                pass
        else:
            logger.error('Failed to connect to database.')
    except Error as e:
        logger.critical(e)

if __name__ == "__main__":
    main()
    logging.shutdown()
    pass

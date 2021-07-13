#!/usr/bin/env python3

import time
import paho.mqtt.client as mqtt
import sys
import os
import argparse
import configparser
import logging
import logging.config
import logging.handlers
import json

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

def GetConfigFilePath():
    fp = os.path.join(ProgPath, 'secrets.ini')
    if not os.path.isfile(fp):
        fp = os.environ['PrivateConfig']
        if not os.path.isfile(fp):
            logger.error('No configuration file found.')
            sys.exit(1)
    logger.info('Using configuration file at: %s', fp)
    return fp

######################   Global declarations   #########################
Topics = []
RequiredConfigParams = frozenset(('mqtt_host', 'mqtt_port', 'mqtt_request_topics', 'mqtt_sync_ms_topic', 'mqtt_sync_topic'))
magicQuitPath = os.path.expandvars('${HOME}/.Close%s'%ProgName)

TIME_SYNC_UPDATE_MSEC_TOPIC =    None     # MQTT topic to subscribe for TIME updates
TIME_SYNC_UPDATE_TOPIC      =    None     # MQTT topic to subscribe for TIME updates

DontPublish = False

def SendTime(client):
    if !DontPublish:
        client.publish(TIME_SYNC_UPDATE_MSEC_TOPIC, str("%1.3f"%time.time()))
        client.publish(TIME_SYNC_UPDATE_TOPIC, str(round(time.time())))
        logger.debug("sent time at %s", time.asctime())
    else:
        logger.debug(f'Would have published: {TIME_SYNC_UPDATE_MSEC_TOPIC}: {str("%1.3f"%time.time()} ')
        logger.debug(f'Would have published: {TIME_SYNC_UPDATE_TOPIC}: {round(time.time())} ')

# The callback for when the client receives a CONNACK response from the server.
# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    logger.info("Connected with result code %s", str(rc))
    if rc==0:
        logger.debug("connected OK")
    else:
        logger.error("Bad connection Returned code=%s",rc)
    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    try:
        logger.info("Subscribing to topic(s): %s", Topics)
        (result, mid) = client.subscribe(list(zip(Topics,[0]*len(Topics))))
        logger.debug('Subscription result: %s, message id is: %s', result, mid)
        # while not client.subscribed_flag: #wait in loop
        #     logger.debug("In subscribe wait loop")
        #     time.sleep(2)
        # logger.debug("subscription successful")
    except Exception as e:
        logger.exception(e)
        sys.exit(3)

def on_subscribe(client, userdata, mid, granted_qos):
    logger.debug('On subscribe callback, mid = %s, userdata = "%s"', mid, userdata)
    pass

# The callback for when the client disconnects from the server.
def on_disconnect(client, userdata, rc):
    logger.debug("---- Disconnected with result code %s: %s", str(rc), mqtt.error_string(rc))

# The callback for when a PUBLISH message is received from the server.
def on_message(client, UsersData, msg):
    if (msg.topic in Topics):
        SendTime(client)
    logger.debug("At %s got [%s]: %s", time.asctime(), msg.topic, str(msg.payload, encoding='utf-8'))
    if os.path.exists(magicQuitPath):
        logger.debug('Quitting because magic file exists.')
        logger.debug('Delete magic file.')
        os.remove(magicQuitPath)
        exit(0)

RecClient = mqtt.Client()
RecClient.on_connect = on_connect
RecClient.on_message = on_message
RecClient.on_disconnect = on_disconnect

def main():

    global Topics, TIME_SYNC_UPDATE_MSEC_TOPIC, TIME_SYNC_UPDATE_TOPIC, DontPublish

    parser = argparse.ArgumentParser(description = 'Respond to Time Sync request messages with current time.')
    parser.add_argument("-t", "--topic", dest="topic", action="append", help="MQTT topic to which to subscribe.  May be specified multiple times.")
    parser.add_argument("-o", "--host", dest="MqttHost", action="store", help="MQTT host", default=None)
    parser.add_argument("-p", "--port", dest="MqttPort", action="store", help="MQTT host port", type=int, default=None)
    parser.add_argument("-P", "--DontPublish", dest="dontpub", action="storetrue", help="Do not actually publish time syncs.", type=bool, default=False)
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

    logger.info("INI file cofig section is: %s", cfgSection)

    cfg = config[cfgSection]
    mqtt_host = cfg['mqtt_host']
    mqtt_port = cfg['mqtt_port']
    TIME_SYNC_UPDATE_MSEC_TOPIC = cfg['mqtt_sync_ms_topic']
    TIME_SYNC_UPDATE_TOPIC = cfg['mqtt_sync_topic']

    if config.has_option(cfgSection, 'mqtt_request_topics'):
        t = cfg['mqtt_request_topics']
        logger.debug('Topics from config is: "%s".', t)
        t = t.split()
        logger.debug('Split topics from config is: "%s".', t)
        Topics = t
        logger.debug('Topics from config is: "%s".', Topics)


    if (args.topic != None) and (len(args.topic) > 0): Topics = args.topic
    if (args.MqttHost != None) and (len(args.MqttHost) > 0): mqtt_host = args.MqttHost
    if (args.MqttPort != None) and (len(args.MqttPort) > 0): mqtt_port = args.MqttPort  #DontPublish
    if (args.dontpub != None): DontPublish = args.dontpub
    mqtt_port = int(mqtt_port)
    if (mqtt_host is None) or (mqtt_port is None) or (len(Topics) == 0):
        logger.critical('No mqtt_host OR no mqtt_port OR no topics; must quit.')
        sys.exit(1)

    try:
        logger.debug('Connecting to MQTT server at "%s", on port "%s", for topics "%s".', mqtt_host, mqtt_port, Topics)
        RecClient.connect(mqtt_host, mqtt_port, 60)
        logger.debug('Mqtt connect returned.')
        logger.debug("Loop immediately after connect returns code: %s", mqtt.error_string(RecClient.loop()))
        if (RecClient._state != mqtt.mqtt_cs_connected):
            logger.debug("Not immediately connected.")
    except Exception as e:
        logger.exception(e)
        sys.exit(2)

    try:
        nowTime = time.time()
        localtime = time.localtime(nowTime)
        timeUs = (nowTime - int(nowTime))*1000000
        logger.debug("Begin receive loop at: %s.%06d %s"%(time.strftime("%Y-%m-%d %H:%M:%S", localtime), timeUs,time. strftime("%Z", localtime)))
        RecClient.loop_forever()
    finally:
        logger.debug('Executing finally clause.')
        RecClient.disconnect()
        pass

if __name__ == "__main__":
    main()
    logging.shutdown()
    pass

#!/bin/bash
until false; do
    mosquitto_pub -h 192.168.0.16 -t "TimeSync/Request" -m "HeartBeat"
    sleep 60
done

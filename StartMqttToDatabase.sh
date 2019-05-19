#!/bin/bash
#
#
#    StartMqttToDatabase.sh -- Shell script to kill and restart MqttToDatabase.py
#      program every day at 2315.
#    Copyright (C) 2015  Thomas A. DeMay
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 3 of the License, or
#    any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to the Free Software Foundation, Inc.,
#    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
# *
# */
#
#  This script creates a special file in the user's home directory that the
# program looks for.  When found, the program quits gracefully.
#
#    Script is run in the source directory.
#

declare -i waitCount=20     #  Will cause us to give up clean quit after 200 seconds.
# Get pid of WeatherReader process.
# Look for "WeatherReader" at the end of the process status entry
# wpid is NOT empty if the WeatherReader application is running, and the status is true.
if wpid=$(pgrep "MqttToDatabase.py\$")
then
    touch $HOME/.CloseMqttToDatabase       # Create .CloseMqttToDatabase file if not exist.
    while wpid=$(pgrep "MqttToDatabase.py\$")
    do      ##  Wait for TimeSyncServer program to see .CloseMqttToDatabase file and quit.
        sleep 10
        ## But don't wait forever.
        if [ $((--waitCount)) -lt 0 ]; then break; fi
    done
fi

# if wpid is not empty, clean termination above did not work.
if [ -n "$wpid" ]; then
    kill $wpid                          # kill the process
    rm $HOME/.CloseMqttToDatabase    # remove the .CloseMqttToDatabase file
                                        # so it won't kill the process
                                        # immediately after starting.
fi

# sleep for 10 seconds
sleep 10

# restart MqttToDatabase.py program
####   MAKE SURE THERE IS A LINK TO THE MqttToDatabase.py EXECUTABLE
#### WHERE THIS SCRIPT EXPECTS IT TO BE.
$PWD/MqttToDatabase.py &

# Reschedule this script to run at 2325 tomorrow.
at -fStartMqttToDatabase.sh 2315 >/dev/null 2>&1

#!/usr/bin/python3 -u
# The -u option above turns off block buffering of python output. This 
# assures that each error message gets individually printed to the log file.
#
# Module: radmonAgent.py
#
# Description: This module acts as an agent between the radiation monitoring
# device and Internet web services.  The agent periodically sends an http
# request to the radiation monitoring device and processes the response from
# the device and performs a number of operations:
#     - conversion of data items
#     - update a round robin (rrdtool) database with the radiation data
#     - periodically generate graphic charts for display in html documents
#     - write the processed radmon data to a JSON file for use by html
#       documents
#
# Copyright 2015 Jeff Owrey
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see http://www.gnu.org/license.
#
# Revision History
#   * v20 released 15 Sep 2015 by J L Owrey; first release
#   * v21 released 27 Nov 2017 by J L Owrey; bug fixes; updates
#   * v22 released 03 Mar 2018 by J L Owrey; improved code readability;
#         improved radmon device offline status handling
#   * v23 released 16 Nov 2018 by J L Owrey: improved fault handling
#         and data conversion
#   * v24 released 14 Jun 2021 by J L Owrey; minor revisions
#   * v25 released 9 Jul 2021 by J L Owrey; improved handling of
#         monitor status function
#
#2345678901234567890123456789012345678901234567890123456789012345678901234567890

import os
import sys
import signal
import multiprocessing
import time
import calendar
import json
from urllib.request import urlopen
import rrdbase

   ### ENVIRONMENT ###

_USER = os.environ['USER']
_SERVER_MODE = "primary"
_USE_RADMON_TIMESTAMP = True

   ### DEFAULT RADIATION MONITOR URL ###

_DEFAULT_RADIATION_MONITOR_URL = \
    "{your radiation monitor URL}"

    ### FILE AND FOLDER LOCATIONS ###

# folder for containing dynamic data objects
_DOCROOT_PATH = "/home/%s/public_html/radmon/" % _USER
# folder for charts and output data file
_CHARTS_DIRECTORY = _DOCROOT_PATH + "dynamic/"
# location of data output file
_OUTPUT_DATA_FILE = _DOCROOT_PATH + "dynamic/radmonData.js"
# database that stores radmon data
_RRD_FILE = "/home/%s/database/radmonData.rrd" % _USER

    ### GLOBAL CONSTANTS ###

# maximum number of failed data requests allowed
_MAX_FAILED_DATA_REQUESTS = 2
# maximum number of http request retries  allowed
_MAX_HTTP_RETRIES = 5
# delay time between http request retries
_HTTP_RETRY_DELAY = 1.119
# interval in seconds between data requests
_DEFAULT_DATA_REQUEST_INTERVAL = 5
# number seconds to wait for a response to HTTP request
_HTTP_REQUEST_TIMEOUT = 3

# interval in seconds between database updates
_DATABASE_UPDATE_INTERVAL = 30
# interval in seconds between chart updates
_CHART_UPDATE_INTERVAL = 300
# standard chart width in pixels
_CHART_WIDTH = 600
# standard chart height in pixels
_CHART_HEIGHT = 150

   ### GLOBAL VARIABLES ###

# turn on or off of verbose debugging information
verboseMode = False
debugMode = False
reportUpdateFails = False

# The following two items are used for detecting system faults
# and radiation monitor online or offline status.
# count of failed attempts to get data from radiation monitor
failedUpdateCount = 0
httpRetries = 0
radmonOnline = False

# status of reset command to radiation monitor
remoteDeviceReset = False
# ip address of radiation monitor
radiationMonitorUrl = _DEFAULT_RADIATION_MONITOR_URL
# web update frequency
dataRequestInterval = _DEFAULT_DATA_REQUEST_INTERVAL

# rrdtool database interface handler
rrdb = None

  ###  PRIVATE METHODS  ###

def getTimeStamp():
    """
    Set the error message time stamp to the local system time.
    Parameters: none
    Returns: string containing the time stamp
    """
    return time.strftime( "%m/%d/%Y %T", time.localtime() )
## end def

def setStatusToOffline():
    """Set the detected status of the radiation monitor to
       "offline" and inform downstream clients by removing input
       and output data files.
       Parameters: none
       Returns: nothing
    """
    global radmonOnline

    # Inform downstream clients by removing output data file.
    if os.path.exists(_OUTPUT_DATA_FILE):
       os.remove(_OUTPUT_DATA_FILE)
    # If the radiation monitor was previously online, then send
    # a message that we are now offline.
    if radmonOnline:
        print('%s radiation monitor offline' % getTimeStamp())
    radmonOnline = False
## end def

def terminateAgentProcess(signal, frame):
    """Send a message to log when the agent process gets killed
       by the operating system.  Inform downstream clients
       by removing input and output data files.
       Parameters:
           signal, frame - dummy parameters
       Returns: nothing
    """
    # Inform downstream clients by removing output data file.
    if os.path.exists(_OUTPUT_DATA_FILE):
       os.remove(_OUTPUT_DATA_FILE)
    print('%s terminating radmon agent process' % \
              (getTimeStamp()))
    sys.exit(0)
## end def

  ###  PUBLIC METHODS  ###

def getRadiationData(dData):
    """Send http request to radiation monitoring device.  The
       response from the device contains the radiation data as
       unformatted ascii text.
       Parameters: none 
       Returns: a string containing the radiation data if successful,
                or None if not successful
    """
    global httpRetries

    sUrl = radiationMonitorUrl
    if remoteDeviceReset:
        sUrl += "/reset" # reboot the radiation monitor
    else:
        sUrl += "/rdata" # request data from the monitor

    try:
        currentTime = time.time()
        response = urlopen(sUrl, timeout=_HTTP_REQUEST_TIMEOUT)
        requestTime = time.time() - currentTime

        content = response.read().decode('utf-8')
        content = content.replace('\n', '')
        content = content.replace('\r', '')
        if content == "":
            raise Exception("empty response")

    except Exception as exError:
        # If no response is received from the device, then assume that
        # the device is down or unavailable over the network.  In
        # that case return None to the calling function.
        httpRetries += 1

        if reportUpdateFails:
            print("%s " % getTimeStamp(), end='')
        if reportUpdateFails or verboseMode:
            print("http request failed (%d): %s" % \
                (httpRetries, exError))

        if httpRetries > _MAX_HTTP_RETRIES:
            httpRetries = 0
            return False
        else:
            time.sleep(_HTTP_RETRY_DELAY)
            return getRadiationData(dData)
    ## end try

    if debugMode:
        print(content)
    if verboseMode:
        print("http request successful: %.4f sec" % requestTime)
    
    httpRetries = 0
    dData['content'] = content
    return True
## end def

def parseDataString(dData):
    """Parse the data string returned by the radiation monitor
       into its component parts.
       Parameters:
            dData - a dictionary object to contain the parsed data items
       Returns: True if successful, False otherwise
    """
    # Example radiation monitor data string
    # $,UTC=17:09:33 6/22/2021,CPS=0,CPM=26,uSv/hr=0.14,Mode=SLOW,#
    
    try:
        sData = dData.pop('content')
        lData = sData[2:-2].split(',')
    except Exception as exError:
        print("%s parseDataString: %s" % (getTimeStamp(), exError))
        return False

    # Verfy the expected number of data items have been received.
    if len(lData) != 5:
        print("%s parse failed: corrupted data string" % getTimeStamp())
        return False;

    # Load the parsed data into a dictionary for easy access.
    for item in lData:
        if "=" in item:
            dData[item.split('=')[0]] = item.split('=')[1]

    # Add status to dictionary object
    dData['status'] = 'online'
    dData['serverMode'] = _SERVER_MODE

    return True
## end def

def convertData(dData):
    """Convert individual radiation data items as necessary.
       Parameters:
           dData - a dictionary object containing the radiation data
       Returns: True if successful, False otherwise
    """
    try:
        if _USE_RADMON_TIMESTAMP:
            # Convert the UTC timestamp provided by the radiation monitoring
            # device to epoch local time in seconds.
            ts_utc = time.strptime(dData['UTC'], "%H:%M:%S %m/%d/%Y")
            epoch_local_sec = calendar.timegm(ts_utc)
        else:
            # Use a timestamp generated by the requesting server (this)
            # instead of the timestamp provided by the radiation monitoring
            # device.  Using the server generated timestamp prevents errors
            # that occur when the radiation monitoring device fails to
            # synchronize with a valid NTP time server.
            epoch_local_sec = time.time()

        dData['date'] = \
            time.strftime("%m/%d/%Y %T", time.localtime(epoch_local_sec))      
        dData['mode'] = dData.pop('Mode').lower()
        dData['uSvPerHr'] = '%.2f' % float(dData['uSv/hr'])
        # The rrdtool database stores whole units, so convert uSv to Sv.
        dData['SvPerHr'] = float(dData.pop('uSv/hr')) * 1.0E-06

    except Exception as exError:
        print("%s data conversion failed: %s" % (getTimeStamp(), exError))
        return False

    return True
## end def

def writeOutputFile(dData):
    """Write radiation data items to the output data file, formatted as 
       a JSON file.  This file may then be accessed and used by
       by downstream clients, for instance, in HTML documents.
       Parameters:
           dData - a dictionary object containing the data to be written
                   to the output data file
       Returns: True if successful, False otherwise
    """
    # Format the radmon data as string using java script object notation.
    jsData = json.loads("{}")
    try:
        for key in dData:
            jsData.update({key:dData[key]})
        sData = "[%s]" % json.dumps(jsData)
    except Exception as exError:
        print("%s writeOutputFile: %s" % (getTimeStamp(), exError))
        return False

    if debugMode:
        print(sData)

    # Write the string to the output data file for use by html documents.
    try:
        fc = open(_OUTPUT_DATA_FILE, "w")
        fc.write(sData)
        fc.close()
    except Exception as exError:
        print("%s writeOutputFile: %s" % (getTimeStamp(), exError))
        return False

    return True
## end def

def setRadmonStatus(updateSuccess):
    """Detect if radiation monitor is offline or not available on
       the network. After a set number of attempts to get data
       from the monitor set a flag that the radmon is offline.
       Parameters:
           updateSuccess - a boolean that is True if data request
                           successful, False otherwise
       Returns: nothing
    """
    global failedUpdateCount, radmonOnline

    if updateSuccess:
        failedUpdateCount = 0
        # Set status and send a message to the log if the device
        # previously offline and is now online.
        if not radmonOnline:
            print('%s radiation monitor online' % getTimeStamp())
            radmonOnline = True
        return
    else:
        # The last attempt failed, so update the failed attempts
        # count.
        failedUpdateCount += 1

    if failedUpdateCount == _MAX_FAILED_DATA_REQUESTS:
        # Max number of failed data requests, so set
        # device status to offline.
        setStatusToOffline()
## end def

    ### GRAPH FUNCTIONS ###

def generateGraphs():
    """Generate graphs for display in html documents.
       Parameters: none
       Returns: nothing
    """
    autoScale = False

    # past 24 hours
    rrdb.createAutoGraph('24hr_cpm', 'CPM', 'counts\ per\ minute', 
                'CPM\ -\ Last\ 24\ Hours', 'end-1day', 0, 0, 2, autoScale)
    rrdb.createAutoGraph('24hr_svperhr', 'SvperHr', 'Sv\ per\ hour',
                'Sv/Hr\ -\ Last\ 24\ Hours', 'end-1day', 0, 0, 2, autoScale)
    # past 4 weeks
    rrdb.createAutoGraph('4wk_cpm', 'CPM', 'counts\ per\ minute',
                'CPM\ -\ Last\ 4\ Weeks', 'end-4weeks', 0, 0, 2, autoScale)
    rrdb.createAutoGraph('4wk_svperhr', 'SvperHr', 'Sv\ per\ hour',
                'Sv/Hr\ -\ Last\ 4\ Weeks', 'end-4weeks', 0, 0, 2, autoScale)
    # past year
    rrdb.createAutoGraph('12m_cpm', 'CPM', 'counts\ per\ minute',
                'CPM\ -\ Past\ Year', 'end-12months', 0, 0, 2, autoScale)
    rrdb.createAutoGraph('12m_svperhr', 'SvperHr', 'Sv\ per\ hour',
                'Sv/Hr\ -\ Past\ Year', 'end-12months', 0, 0, 2, autoScale)
## end def

def getCLarguments():
    """Get command line arguments.  There are four possible arguments
          -d turns on debug mode
          -v turns on verbose mode
          -t sets the radiation device query interval
          -u sets the url of the radiation monitoring device
       Returns: nothing
    """
    global verboseMode, debugMode, dataRequestInterval, \
           radiationMonitorUrl, reportUpdateFails

    index = 1
    while index < len(sys.argv):
        if sys.argv[index] == '-v':
            verboseMode = True
        elif sys.argv[index] == '-d':
            verboseMode = True
            debugMode = True
        elif sys.argv[index] == '-r':
            reportUpdateFails = True

        # Update period and url options
        elif sys.argv[index] == '-p':
            try:
                dataRequestInterval = abs(float(sys.argv[index + 1]))
            except:
                print("invalid polling period")
                exit(-1)
            index += 1
        elif sys.argv[index] == '-u':
            radiationMonitorUrl = sys.argv[index + 1]
            if radiationMonitorUrl.find('http://') < 0:
                radiationMonitorUrl = 'http://' + radiationMonitorUrl
            index += 1
        else:
            cmd_name = sys.argv[0].split('/')
            print("Usage: %s [-d] [-p seconds] [-u url}" % cmd_name[-1])
            exit(-1)
        index += 1
## end def

def setup():
    """Handles timing of events and acts as executive routine managing
       all other functions.
       Parameters: none
       Returns: nothing
    """
    global rrdb

    ## Get command line arguments.
    getCLarguments()

    print('====================================================')
    print('%s starting up radmon agent process' % \
                  (getTimeStamp()))

    ## Exit with error if rrdtool database does not exist.
    if not os.path.exists(_RRD_FILE):
        print('rrdtool database does not exist\n' \
              'use createRadmonRrd script to ' \
              'create rrdtool database\n')
        exit(1)

    signal.signal(signal.SIGTERM, terminateAgentProcess)
    signal.signal(signal.SIGINT, terminateAgentProcess)

    # Define object for calling rrdtool database functions.
    rrdb = rrdbase.rrdbase( _RRD_FILE, _CHARTS_DIRECTORY, _CHART_WIDTH, \
                            _CHART_HEIGHT, verboseMode, debugMode )
## end def

def loop():
     # last time output JSON file updated
    lastDataRequestTime = -1
    # last time charts generated
    lastChartUpdateTime = - 1
    # last time the rrdtool database updated
    lastDatabaseUpdateTime = -1

    while True:

        currentTime = time.time() # get current time in seconds

        # Every data update interval request data from the radiation
        # monitor and process the received data.
        if currentTime - lastDataRequestTime > dataRequestInterval:
            lastDataRequestTime = currentTime
            dData = {}

            # Get the data string from the device.
            result = getRadiationData(dData)

            # If successful parse the data.
            if result:
                result = parseDataString(dData)

            # If parsing successful, convert the data.
            if result:
                result = convertData(dData)

            # If conversion successful, write data to data files.
            if result:
                writeOutputFile(dData)

            # At the rrdtool database update interval, update the database.
            if result and (currentTime - lastDatabaseUpdateTime > \
                           _DATABASE_UPDATE_INTERVAL):   
                lastDatabaseUpdateTime = currentTime
                ## Update the round robin database with the parsed data.
                result = rrdb.updateDatabase(dData['date'], \
                             dData['CPM'], dData['SvPerHr'])

            # Set the radmon status to online or offline depending on the
            # success or failure of the above operations.
            setRadmonStatus(result)


        # At the chart generation interval, generate charts.
        if currentTime - lastChartUpdateTime > _CHART_UPDATE_INTERVAL:
            lastChartUpdateTime = currentTime
            p = multiprocessing.Process(target=generateGraphs, args=())
            p.start()

        # Relinquish processing back to the operating system until
        # the next update interval.

        elapsedTime = time.time() - currentTime
        if verboseMode:
            if result:
                print("update successful: %6f sec\n"
                      % elapsedTime)
            else:
                print("update failed: %6f sec\n"
                      % elapsedTime)
        remainingTime = dataRequestInterval - elapsedTime
        if remainingTime > 0.0:
            time.sleep(remainingTime)
    ## end while
## end def

if __name__ == '__main__':
    setup()
    loop()


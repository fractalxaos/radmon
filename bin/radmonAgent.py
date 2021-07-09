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
import subprocess
import multiprocessing
import time
import calendar
import json
from urllib.request import urlopen

   ### ENVIRONMENT ###

_USER = os.environ['USER']
_SERVER_MODE = "primary"
_USE_RADMON_TIMESTAMP = True

   ### DEFAULT RADIATION MONITOR URL ###

_DEFAULT_RADIATION_MONITOR_URL = \
    "{your radiation monitor url}"

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

# max number of failed data requests allowed
_MAX_FAILED_DATA_REQUESTS = 3
# interval in seconds between data requests
_DEFAULT_DATA_REQUEST_INTERVAL = 2
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

# The following two items are used for detecting system faults
# and radiation monitor online or offline status.
# count of failed attempts to get data from radiation monitor
failedUpdateCount = 0
# detected status of radiation monitor device
radmonOnline = False

# status of reset command to radiation monitor
remoteDeviceReset = False
# ip address of radiation monitor
radiationMonitorUrl = _DEFAULT_RADIATION_MONITOR_URL
# web update frequency
dataRequestInterval = _DEFAULT_DATA_REQUEST_INTERVAL

  ###  PRIVATE METHODS  ###

def getTimeStamp():
    """
    Set the error message time stamp to the local system time.
    Parameters: none
    Returns: string containing the time stamp
    """
    return time.strftime( "%m/%d/%Y %T", time.localtime() )
##end def

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
##end def

def terminateAgentProcess(signal, frame):
    """Send a message to log when the agent process gets killed
       by the operating system.  Inform downstream clients
       by removing input and output data files.
       Parameters:
           signal, frame - dummy parameters
       Returns: nothing
    """
    print('%s terminating radmon agent process' % \
              (getTimeStamp()))
    setStatusToOffline()
    sys.exit(0)
##end def

  ###  PUBLIC METHODS  ###

def getRadiationData(dData):
    """Send http request to radiation monitoring device.  The
       response from the device contains the radiation data as
       unformatted ascii text.
       Parameters: none 
       Returns: a string containing the radiation data if successful,
                or None if not successful
    """
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
        if verboseMode:
            print("%s getRadiationData: %s" % (getTimeStamp(), exError))
        return False
    ##end try

    if debugMode:
        print(content)
    if verboseMode:
        print("http request successful: %.4f sec" % requestTime)
    
    dData['content'] = content
    return True
##end def

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
##end def

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
            dData['ELT'] = epoch_local_sec
        else:
            # Use a timestamp generated by the requesting server (this)
            # instead of the timestamp provided by the radiation monitoring
            # device.  Using the server generated timestamp prevents errors
            # that occur when the radiation monitoring device fails to
            # synchronize with a valid NTP time server.
            dData['ELT'] = time.time()

        dData['date'] = \
            time.strftime("%m/%d/%Y %T", time.localtime(dData['ELT']))      
        dData['mode'] = dData.pop('Mode').lower()
        dData['uSvPerHr'] = '%.2f' % float(dData.pop('uSv/hr'))

    except Exception as exError:
        print("%s data conversion failed: %s" % (getTimeStamp(), exError))
        return False

    return True
##end def

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
    elif failedUpdateCount == _MAX_FAILED_DATA_REQUESTS - 1:
        # Max number of failed data requests, so set
        # device status to offline.
        setStatusToOffline()
    ## end if
    failedUpdateCount += 1
##end def

    ### DATABASE FUNCTIONS ###

def updateDatabase(dData):
    """
    Update the rrdtool database by executing an rrdtool system command.
    Format the command using the data extracted from the radiation
    monitor response.   
    Parameters: dData - dictionary object containing data items to be
                        written to the rr database file
    Returns: True if successful, False otherwise
    """
    global remoteDeviceReset

    # The RR database stores whole units, so convert uSv to Sv.
    SvPerHr = float(dData['uSvPerHr']) * 1.0E-06 

    # Format the rrdtool update command.
    strCmd = "rrdtool update %s %s:%s:%s" % \
                       (_RRD_FILE, dData['ELT'], dData['CPM'], SvPerHr)
    if debugMode:
        print("%s" % strCmd) # DEBUG

    # Run the command as a subprocess.
    try:
        subprocess.check_output(strCmd, shell=True,  \
                             stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exError:
        print("%s: rrdtool update failed: %s" % \
                    (getTimeStamp(), exError.output))
        if exError.output.find("illegal attempt to update using time") > -1:
            remoteDeviceReset = True
            print("%s: rebooting radiation monitor" % (getTimeStamp()))
        return False

    if verboseMode and not debugMode:
        print("database update successful")

    return True
##end def

def createGraph(fileName, dataItem, gLabel, gTitle, gStart,
                lower, upper, addTrend, autoScale):
    """Uses rrdtool to create a graph of specified radmon data item.
       Parameters:
           fileName - name of file containing the graph
           dataItem - data item to be graphed
           gLabel - string containing a graph label for the data item
           gTitle - string containing a title for the graph
           gStart - beginning time of the graphed data
           lower - lower bound for graph ordinate #NOT USED
           upper - upper bound for graph ordinate #NOT USED
           addTrend - 0, show only graph data
                      1, show only a trend line
                      2, show a trend line and the graph data
           autoScale - if True, then use vertical axis auto scaling
               (lower and upper parameters are ignored), otherwise use
               lower and upper parameters to set vertical axis scale
       Returns: True if successful, False otherwise
    """
    gPath = _CHARTS_DIRECTORY + fileName + ".png"
    trendWindow = { 'end-1day': 7200,
                    'end-4weeks': 172800,
                    'end-12months': 604800 }
 
    # Format the rrdtool graph command.

    # Set chart start time, height, and width.
    strCmd = "rrdtool graph %s -a PNG -s %s -e now -w %s -h %s " \
             % (gPath, gStart, _CHART_WIDTH, _CHART_HEIGHT)
   
    # Set the range and scaling of the chart y-axis.
    if lower < upper:
        strCmd  +=  "-l %s -u %s -r " % (lower, upper)
    elif autoScale:
        strCmd += "-A "
    strCmd += "-Y "

    # Set the chart ordinate label and chart title. 
    strCmd += "-v %s -t %s " % (gLabel, gTitle)
 
    # Show the data, or a moving average trend line over
    # the data, or both.
    strCmd += "DEF:dSeries=%s:%s:LAST " % (_RRD_FILE, dataItem)
    if addTrend == 0:
        strCmd += "LINE1:dSeries#0400ff "
    elif addTrend == 1:
        strCmd += "CDEF:smoothed=dSeries,%s,TREND LINE2:smoothed#006600 " \
                  % trendWindow[gStart]
    elif addTrend == 2:
        strCmd += "LINE1:dSeries#0400ff "
        strCmd += "CDEF:smoothed=dSeries,%s,TREND LINE2:smoothed#006600 " \
                  % trendWindow[gStart]
     
    if debugMode:
        print("\n%s" % strCmd) # DEBUG
    
    # Run the formatted rrdtool command as a subprocess.
    try:
        result = subprocess.check_output(strCmd, \
                     stderr=subprocess.STDOUT,   \
                     shell=True)
    except subprocess.CalledProcessError as exError:
        print("rrdtool graph failed: %s" % (exError.output))
        return False

    if verboseMode:
        print("rrdtool graph: %s" % result.decode('utf-8'), end='')
    return True

##end def

def generateGraphs():
    """Generate graphs for display in html documents.
       Parameters: none
       Returns: nothing
    """
    autoScale = False

    # past 24 hours
    createGraph('24hr_cpm', 'CPM', 'counts\ per\ minute', 
                'CPM\ -\ Last\ 24\ Hours', 'end-1day', 0, 0, 2, autoScale)
    createGraph('24hr_svperhr', 'SvperHr', 'Sv\ per\ hour',
                'Sv/Hr\ -\ Last\ 24\ Hours', 'end-1day', 0, 0, 2, autoScale)
    # past 4 weeks
    createGraph('4wk_cpm', 'CPM', 'counts\ per\ minute',
                'CPM\ -\ Last\ 4\ Weeks', 'end-4weeks', 0, 0, 2, autoScale)
    createGraph('4wk_svperhr', 'SvperHr', 'Sv\ per\ hour',
                'Sv/Hr\ -\ Last\ 4\ Weeks', 'end-4weeks', 0, 0, 2, autoScale)
    # past year
    createGraph('12m_cpm', 'CPM', 'counts\ per\ minute',
                'CPM\ -\ Past\ Year', 'end-12months', 0, 0, 2, autoScale)
    createGraph('12m_svperhr', 'SvperHr', 'Sv\ per\ hour',
                'Sv/Hr\ -\ Past\ Year', 'end-12months', 0, 0, 2, autoScale)
##end def

def getCLarguments():
    """Get command line arguments.  There are four possible arguments
          -d turns on debug mode
          -v turns on verbose mode
          -t sets the radiation device query interval
          -u sets the url of the radiation monitoring device
       Returns: nothing
    """
    global verboseMode, debugMode, dataRequestInterval, \
           radiationMonitorUrl

    index = 1
    while index < len(sys.argv):
        if sys.argv[index] == '-v':
            verboseMode = True
        elif sys.argv[index] == '-d':
            verboseMode = True
            debugMode = True
        elif sys.argv[index] == '-t':
            dataRequestInterval = abs(int(sys.argv[index + 1]))
            index += 1
        elif sys.argv[index] == '-u':
            radiationMonitorUrl = sys.argv[index + 1]
            if radiationMonitorUrl.find('http://') < 0:
                radiationMonitorUrl = 'http://' + radiationMonitorUrl
            index += 1
        else:
            cmd_name = sys.argv[0].split('/')
            print("Usage: %s [-d] [-t seconds] [-u url}" % cmd_name[-1])
            exit(-1)
        index += 1
##end def

def main():
    """Handles timing of events and acts as executive routine managing
       all other functions.
       Parameters: none
       Returns: nothing
    """
    signal.signal(signal.SIGTERM, terminateAgentProcess)
    signal.signal(signal.SIGINT, terminateAgentProcess)

    print('===================')
    print('%s starting up radmon agent process' % \
                  (getTimeStamp()))

    # last time output JSON file updated
    lastDataRequestTime = -1
    # last time charts generated
    lastChartUpdateTime = - 1
    # last time the rrdtool database updated
    lastDatabaseUpdateTime = -1

    ## Get command line arguments.
    getCLarguments()

    ## Exit with error if rrdtool database does not exist.
    if not os.path.exists(_RRD_FILE):
        print('rrdtool database does not exist\n' \
              'use createRadmonRrd script to ' \
              'create rrdtool database\n')
        exit(1)
 
    ## main loop
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
                result = updateDatabase(dData)

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
    return
## end def

if __name__ == '__main__':
    main()


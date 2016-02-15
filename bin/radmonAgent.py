#!/usr/bin/python -u
## The -u option above turns off block buffering of python output. This assures
## that each error message gets individually printed to the log file.
#
# Module: radmonAgent.py
#
# Description: This module acts as an agent between the radiation monitoring device
# and the Internet web server.  The agent periodically sends an http request to the
# radiation monitoring device and processes the response from the device and performs
# a number of operations:
#     - conversion of data items
#     - update a round robin (rrdtool) database with the radiation data
#     - periodically generate graphic charts for display in html documents
#     - forward the radiation data to other services
#     - write the processed weather data to a JSON file for use by html documents
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
#   * v20 released 15 Sep 2015 by J L Owrey
#
import urllib2
import time
import calendar
import subprocess
import sys
import os
import json
import multiprocessing

    ### FILE AND FOLDER LOCATIONS ###

_USER = os.environ['USER']
_TMP_DIRECTORY = "/tmp/radmon" # folder for charts and output data file
_RRD_FILE = "/home/%s/database/radmonData.rrd" % _USER # database that stores the data
_OUTPUT_DATA_FILE = "/tmp/radmon/radmonData.js" # output file used by HTML docs

    ### GLOBAL CONSTANTS ###

_DEFAULT_WEB_DATA_UPDATE_INTERVAL = 10
_CHART_UPDATE_INTERVAL = 300 # defines how often the charts get updated
_DATABASE_UPDATE_INTERVAL = 30 # defines how often the database gets updated
_HTTP_REQUEST_TIMEOUT = 5 # number seconds to wait for a response to HTTP request
_CHART_WIDTH = 600
_CHART_HEIGHT = 150

   ### GLOBAL VARIABLES ###

webUpdateInterval = _DEFAULT_WEB_DATA_UPDATE_INTERVAL  # web update frequency
deviceUrl = "{your device url}"  # radiation monitor network address
deviceOnline = True
debugOption = False


  ###  PRIVATE METHODS  ###

def getTimeStamp():
    """
    Sets the error message time stamp to the local system time.
    Parameters: none
    Returns string containing the time stamp.
    """
    return time.strftime( "%Y/%m/%d %T", time.localtime() )
##end def

def setOfflineStatus(dData):
    """Set the status of the the upstream device to "offline" and sends
       blank data to the downstream clients.
       Parameters:
           dData - dictionary object containing weather data
       Returns nothing.
    """
    global deviceOnline

    # If the radiation monitor was previously online, then send a message
    # that we are now offline.
    if deviceOnline:
        print "%s: radmon offline" % getTimeStamp()
        deviceOnline = False

    # Set data items to blank.
    dData['UTC'] = ''
    dData['CPM'] = ''
    dData['CPS'] = ''
    dData['uSvPerHr'] = ''
    dData['Mode'] = ''
    dData['status'] = 'offline'

    writeOutputDataFile(dData)
    return
##end def

  ###  PUBLIC METHODS  ###

def getRadmonData(deviceUrl, HttpRequestTimeout):
    """Send http request to radiation monitoring device.  The response
       from the device contains the radiation data.  The data is formatted
       as an html document.
    Parameters: 
        deviceUrl - url of radiation monitoring device
        HttpRequesttimeout - how long to wait for device
                             to respond to http request
    Returns a string containing the radiation data, or None if
    not successful.
    """
    global deviceOnline

    try:
        conn = urllib2.urlopen(deviceUrl + "/rdata", timeout=HttpRequestTimeout)
    except Exception, exError:
        # If no response is received from the device, then assume that
        # the device is down or unavailable over the network.  In
        # that case set the status of the device to offline.
        if debugOption:
            print "getRadmonData: %s\n" % exError
        return None

    # If the radiation monitor was previously offline, then send a message
    # that we are now online.
    if not deviceOnline:
        print "%s radmon online" % getTimeStamp()
        deviceOnline = True

    # Format received data into a single string.
    content = ""
    for line in conn:
         content += line.strip()
    del conn
    return content
##end def

def parseDataString(sData, dData):
    """Parse the radiation data JSON string from the radiation 
       monitoring device into its component parts.  
       Parameters:
           sData - the string containing the data to be parsed
           dData - a dictionary object to contain the parsed data items
       Returns true if successful, false otherwise.
    """
    try:
        sTmp = sData[2:-2]
        lsTmp = sTmp.split(',')
    except Exception, exError:
        print "%s parseDataString: %s" % (getTimeStamp(), exError)
        return False

    # Load the parsed data into a dictionary for easy access.
    for item in lsTmp:
        if "=" in item:
            dData[item.split('=')[0]] = item.split('=')[1]
    dData['status'] = 'online'

    return True
##end def

def convertData(dData):
    """Convert individual radiation data items as necessary.
       Parameters:
           lsData - a list object containing the radiation data
           dData - a dictionary object containing the radiation data
       Returns true if successful, false otherwise.
    """
    result = True
 
    try:
        # Convert UTC from radiation monitoring device to local time.
        ts_utc = time.strptime(dData['UTC'], "%H:%M:%S %m/%d/%Y")
        local_sec = calendar.timegm(ts_utc)
        dData['UTC'] = local_sec

        dData['Mode'] = dData['Mode'].lower()
        dData['uSvPerHr'] = dData.pop('uSv/hr')
    except Exception, exError:
        print "%s convertData: %s" % (getTimeStamp(), exError)
        result = False

    return result
##end def

def writeOutputDataFile(dData):
    """Convert individual weather string data items as necessary.
       Parameters:
           lsData - a list object containing the data to be written
                    to the JSON file
       Returns true if successful, false otherwise.
    """
    # Set date to current time and data
    dData['date'] = getTimeStamp()

    # Format the weather data as string using java script object notation.
    sData = '[{'
    for key in dData:
        sData += "\"%s\":\"%s\"," % (key, dData[key])
    sData = sData[:-1] + '}]'

    # Write the string to the output data file for use by html documents.
    try:
        fc = open(_OUTPUT_DATA_FILE, "w")
        fc.write(sData)
        fc.close()
    except Exception, exError:
        print "%s writeOutputDataFile: %s" % (getTimeStamp(), exError)
        return False

    if debugOption and 0:
        print sData

    return True
## end def

def updateDatabase(dData):
    """
    Updates the rrdtool database by executing an rrdtool system command.
    Formats the command using the data extracted from the radiation
    monitor response.   
    Parameters: dData - dictionary object containing data items to be
                        written to the rr database file
    Returns true if successful, false otherwise.
    """
    # The RR database stores whole units, so convert uSv to Sv.   
    Svvalue = float(dData['uSvPerHr']) * 1.0E-06 # convert micro-Sieverts to Sieverts

    # Create the rrdtool update command.
    strCmd = "rrdtool update %s %s:%s:%s" % \
                       (_RRD_FILE, dData['UTC'], dData['CPM'], Svvalue)
    if debugOption:
        print "%s\n" % strCmd # DEBUG

    # Run the command as a subprocess.
    try:
        subprocess.check_output(strCmd, shell=True,  \
                             stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError, exError:
        print "%s: rrdtool update failed: %s" % \
                                 (getTimeStamp(), exError.output)
        return False

    return True
##end def

def createGraph(fileName, dataItem, gLabel, gTitle, gStart, lower, upper, addTrend):
    """Uses rrdtool to create a graph of specified weather data item.
       Parameters:
           fileName - name of graph image file
           dataItem - data item to be graphed
           gTitle - a title for the graph
           gStart - beginning time of the data to be graphed
       Returns true if successful, false otherwise.
    """
    gPath = _TMP_DIRECTORY + '/' + fileName + ".png"
    trendWindow = { 'end-1day': 7200,
                    'end-4weeks': 172800,
                    'end-12months': 604800 }
 
    # Format the rrdtool graph command.

    # Set chart start time, height, and width.
    strCmd = "rrdtool graph %s -a PNG -s %s -e now -w %s -h %s " \
             % (gPath, gStart, _CHART_WIDTH, _CHART_HEIGHT)
   
    # Set the range of the chart ordinate dataum.
    if lower < upper:
        strCmd  +=  "-l %s -u %s " % (lower, upper)
    else:
        #strCmd += "-A -Y "
        strCmd += "-Y "

    # Set the chart ordinate label and chart title. 
    strCmd += "-v %s -t %s " % (gLabel, gTitle)

    # Show the data, or a moving average trend line over
    # the data, or both.
    strCmd += "DEF:%s=%s:%s:LAST " % (dataItem, _RRD_FILE, dataItem)

    if addTrend == 0 or addTrend == 2:
        strCmd += "LINE1:%s\#0400ff " % (dataItem)
    if addTrend == 1 or addTrend == 2:
        strCmd += "CDEF:smoothed=%s,%s,TREND LINE1:smoothed#ff0000" \
                  % (dataItem, trendWindow[gStart])
       
    if debugOption:
        print "%s\n" % strCmd # DEBUG
    
    # Run the formatted rrdtool command as a subprocess.
    try:
        result = subprocess.check_output(strCmd, \
                     stderr=subprocess.STDOUT,   \
                     shell=True)
    except subprocess.CalledProcessError, exError:
        print "rrdtool graph failed: %s" % (exError.output)
        return False

    if debugOption:
        print "rrdtool graph: %s" % result
    return True

##end def

def getCLarguments():
    """Get command line arguments.  There are three possible arguments
          -d turns on debug mode
          -t sets the radiation device query interval
          -u sets the url of the radiation monitoring device
       Returns nothing.
    """
    global debugOption, webUpdateInterval, deviceUrl

    index = 1
    while index < len(sys.argv):
        if sys.argv[index] == '-d':
            debugOption = True
        elif sys.argv[index] == '-t':
            try:
                webUpdateInterval = abs(int(sys.argv[index + 1]))
            except:
                print "invalid polling period"
                exit(-1)
            index += 1
        elif sys.argv[index] == '-u':
            deviceUrl = sys.argv[index + 1]
            index += 1
        else:
            cmd_name = sys.argv[0].split('/')
            print "Usage: %s {-v} {-d}" % cmd_name[-1]
            exit(-1)
        index += 1
##end def

def generateGraphs():
    """Generate graphs for display in html documents.
       Parameters: none
       Returns nothing.
    """
    createGraph('radGraph1', 'CPM', "'counts per minute'", "'CPM - Last 24 Hours'", 'end-1day', 0, 0, 2)
    createGraph('radGraph2', 'SvperHr', "'Sv per hour'", "'Sv/Hr - Last 24 Hours'", 'end-1day', 0, 0, 2)
    createGraph('radGraph3', 'CPM', "'counts per minute'", "'CPM - Last 4 Weeks'", 'end-4weeks', 0, 0, 2)
    createGraph('radGraph4', 'SvperHr', "'Sv per hour'", "'Sv/Hr - Last 4 Weeks'", 'end-4weeks', 0, 0, 2)
    createGraph('radGraph5', 'CPM', "'counts per minute'", "'CPM - Past Year'", 'end-12months', 0, 0, 2)
    createGraph('radGraph6', 'SvperHr', "'Sv per hour'", "'Sv/Hr - Past Year'", 'end-12months', 0, 0, 2)
##end def

def main():
    """Handles timing of events and acts as executive routine managing all other
       functions.
       Parameters: none
       Returns nothing.
    """

    lastChartUpdateTime = - 1 # last time charts generated
    lastDatabaseUpdateTime = -1 # last time the rrdtool database updated
    lastWebUpdateTime = -1 # last time output JSON file updated
    dData = {}  # dictionary object for temporary data storage
    lsData = [] # list object for temporary data storage

    ## Get command line arguments.
    getCLarguments()

    ## Create www data folder if it does not already exist.
    if not os.path.isdir(_TMP_DIRECTORY):
        os.makedirs(_TMP_DIRECTORY)

    ## Exit with error if cannot find the rrdtool database file.
    if not os.path.exists(_RRD_FILE):
        print "cannot find rrdtool database file: terminating"
        exit(1)
 
    ## main loop
    while True:

        currentTime = time.time()

        # At the radiation device query interval request and process
        # the data from the device.
        if currentTime - lastWebUpdateTime > webUpdateInterval:
            lastWebUpdateTime = currentTime
            result = True

            # Get the data string from the device.
            sData = getRadmonData(deviceUrl, _HTTP_REQUEST_TIMEOUT)
            if sData == None:
                setOfflineStatus(dData)
                result = False

            # If successful parse the data.
            if result:
                result = parseDataString(sData, dData)

            # If parsing successful, convert the data.
            if result:
                result = convertData(dData)

            # If conversion successful, write data to output file.
            if result:
                writeOutputDataFile(dData)

                # At the rrdtool database update interval, update the database.
                if currentTime - lastDatabaseUpdateTime > _DATABASE_UPDATE_INTERVAL:   
                    lastDatabaseUpdateTime = currentTime
                    ## Update the round robin database with the parsed data.
                    result = updateDatabase(dData)

        # At the chart generation interval, generate charts.
        if currentTime - lastChartUpdateTime > _CHART_UPDATE_INTERVAL:
            lastChartUpdateTime = currentTime
            p = multiprocessing.Process(target=generateGraphs, args=())
            p.start()

        # Relinquish processing back to the operating system until
        # the next update interval.

        elapsedTime = time.time() - currentTime
        if debugOption:
            print "web update: %6f sec\n" % elapsedTime
        remainingTime = webUpdateInterval - elapsedTime
        if remainingTime > 0:
            time.sleep(remainingTime)
             
    ## end while
## end def

if __name__ == '__main__':
    main()
        

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

_TMP_DIRECTORY = "/tmp/radmon" # folder for charts and output data file
_RRD_FILE = "/home/{user}/database/radmonData.rrd"  # database that stores the data
_OUTPUT_DATA_FILE = "/tmp/radmon/radmonData.js" # output file used by HTML docs

    ### GLOBAL CONSTANTS ###

_DEFAULT_WEB_DATA_UPDATE_INTERVAL = 10
_CHART_UPDATE_INTERVAL = 60 # defines how often the charts get updated
_DATABASE_UPDATE_INTERVAL = 30 # defines how often the database gets updated
_HTTP_REQUEST_TIMEOUT = 5 # number seconds to wait for a response to HTTP request

   ### GLOBAL VARIABLES ###

webUpdateInterval = _DEFAULT_WEB_DATA_UPDATE_INTERVAL  # web update frequency
deviceUrl = "http://192.168.1.8"  # radiation monitor network address
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

def sendOffLineStatusMessage():
    """Sets the status of the the upstream device to "offline" and sends
       blank data to the downstream clients.
       Parameters: none
       Returns nothing.
    """
    sTmp = "\"date\":\"\",\"CPS\":\"\",\"CPM\":\"\"," \
           "\"uSvPerHr\":\"\",\"Mode\":\"\",\"status\":\"offline\""

    lsTmp = sTmp.split(',')
    lsTmp[0] = "\"date\":\"%s\"" % getTimeStamp()
    writeOutputDataFile(lsTmp)
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
        content = ""
        try:
            conn = urllib2.urlopen(deviceUrl + "/jsdata", timeout=HttpRequestTimeout)
        except Exception, exError:
            # If no response is received from the device, then assume that
            # the device is down or unavailable over the network.  In
            # that case set the status of the device to offline.
            print "%s: device offline: %s" % \
                                (getTimeStamp(), exError)
            return None
        else:
            for line in conn:
                content += line.strip()
            if len(content) == 0:
                print "%s: HTTP download failed: null content" % \
                    (getTimeStamp())
                return None
            del conn
            return content
##end def

def parseDataString(sData, lsData, dData):
    """Parse the radiation data JSON string from the radiation 
       monitoring device into its component parts.  
       Parameters:
           sData - the string containing the data to be parsed
          lsData - a list object to contain the parsed data items
           dData - a dictionary object to contain the parsed data items
       Returns true if successful, false otherwise.
    """
    # Clear data array in preparation for loading reformatted data.
    while len(lsData) > 0:
        elmt = lsData.pop(0)

    try:
        dTmp = json.loads(sData[1:-1])
        sTmp = dTmp['radmon'].encode('ascii', 'ignore')
        lsTmp = sTmp.split(',')
        lsData.extend(lsTmp)
    except Exception, exError:
        print "%s parse failed: %s" % (getTimeStamp(), exError)
        return False

    # Since the device responded, set the status to online.
    lsData.insert(-2, "status=online")

    # Load the parsed data into a dictionary for easy access.
    for item in lsData:
        if "=" in item:
            dData[item.split('=')[0]] = item.split('=')[1]

    return True
##end def

def convertData(lsData, dData):
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
    except:
        print "%s invalid time: %s" % (getTimeStamp(), utc)
        result = False

    # Clear data array in preparation for loading reformatted data.
    while len(lsData) > 0:
        elmt = lsData.pop(0)

    lsData.append("\"UTC\":\"%s\"" % dData['UTC'])
    lsData.append("\"CPS\":\"%s\"" % dData['CPS'])
    lsData.append("\"CPM\":\"%s\"" % dData['CPM'])
    lsData.append("\"uSvPerHr\":\"%s\"" % dData['uSv/hr'])
    lsData.append("\"Mode\":\"%s\"" % dData['Mode'].lower())
    lsData.append("\"status\":\"%s\"" % dData['status'])

    return result
##end def

def writeOutputDataFile(lsData):
    """Convert individual weather string data items as necessary.
       Parameters:
           lsData - a list object containing the data to be written
                    to the JSON file
       Returns true if successful, false otherwise.
    """
    # Convert the list object to a string.
    sTmp = ','.join(lsData)

    # Apply JSON formatting to the string and write it to a
    # file for use by html documents.
    sData = "[{%s}]\n" % (sTmp)

    try:
        fc = open(_OUTPUT_DATA_FILE, "w")
        fc.write(sData)
        fc.close()
    except Exception, exError:
        print "%s: write to JSON file failed: %s" % \
                             (getTimeStamp(), exError)
        return False

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
    Svvalue = float(dData['uSv/hr']) * 1.0E-06 # convert micro-Sieverts to Sieverts

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

def createGraph(fileName, dataItem, gTitle, gStart):
    """Uses rrdtool to create a graph of specified weather data item.
       Parameters:
           fileName - name of graph image file
           dataItem - data item to be graphed
           gTitle - a title for the graph
           gStart - beginning time of the data to be graphed
       Returns true if successful, false otherwise.
    """
    gPath = _TMP_DIRECTORY + '/' + fileName + ".png"

    # Create the rrdtool graph command.
    strFmt = ("rrdtool graph %s -a PNG -s %s -w 600 -h 150 "
                           ##  "-l 50 -u 110 -r "
                               "-v %s -t %s "
                               "DEF:%s=%s:%s:AVERAGE "
                               "LINE2:%s\#0400ff:")         
    strCmd = strFmt % (gPath, gStart, dataItem, gTitle, dataItem, \
                       _RRD_FILE, dataItem, dataItem)
    if debugOption:
        print "%s\n" % strCmd # DEBUG
    
    # Run the command as a subprocess.
    try:
        result = subprocess.check_output(strCmd, stderr=subprocess.STDOUT, \
                     shell=True)
    except subprocess.CalledProcessError, exError:
        print "rdtool graph failed: %s" % (exError.output)
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
    createGraph('radGraph1', 'CPM', "'CPM - Last 24 Hours'", 'end-1day')
    createGraph('radGraph2', 'SvperHr', "'Sv/Hr - Last 24 Hours'", 'end-1day')
    createGraph('radGraph3', 'CPM', "'CPM - Last 4 Weeks'", 'end-4weeks')
    createGraph('radGraph4', 'SvperHr', "'Sv/Hr - Last 4 Weeks'", 'end-4weeks')
    createGraph('radGraph5', 'CPM', "'CPM - Past Year'", 'end-12months')
    createGraph('radGraph6', 'SvperHr', "'Sv/Hr - Past Year'", 'end-12months')
##end def

def main():
    """Handles timing of events and acts as executive routine managing all other
       functions.
       Parameters: none
       Returns nothing.
    """

    lastChartUpdateTime = - 1 # last time charts generated
    lastDatabaseUpdateTime = -1 # last time the rrdtool database updated
    lastWebDataUpdateTime = -1 # last time output JSON file updated
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
        if currentTime - lastWebDataUpdateTime > webUpdateInterval:
            llastWebDataUpdateTime = currentTime
            result = True

            # Get the data string from the device.
            sData = getRadmonData(deviceUrl, _HTTP_REQUEST_TIMEOUT)
            if sData == None:
                sendOffLineStatusMessage()
                result = False

            # If successful parse the data.
            if result:
                result = parseDataString(sData, lsData, dData)

            # If parsing successful, convert the data.
            if result:
                result = convertData(lsData, dData)

            # If conversion successful, write data to output file.
            if result:
                lsData[0] = "\"date\":\"%s\"" % getTimeStamp()
                writeOutputDataFile(lsData)

        # At the rrdtool database update interval, update the database.
        if currentTime - lastDatabaseUpdateTime > _DATABASE_UPDATE_INTERVAL:   
            lastDatabaseUpdateTime = currentTime
            if result:
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
        

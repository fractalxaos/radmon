/*
 Background Radiation Monitor - Web Server
 
 A simple web server that makes available to clients over the Internet
 readings from a MightyOhm Geiger counter. The MightyOhm is connected
 to an Arduino Uno with attached Ethernet shield.  This software module
 runs on the Arduino Uno an embedded HTTP server by which Internet
 applications can query the MightyOhm for Geiger counter readings.
 Also, this software runs a Network Time Protocol (NTP) client, that
 periodically synchronizes the local system clock to network time.
 Included is a simple command line interface that may be used to change
 the network interface IP address, NTP server address, or configure a
 verbose output mode.
 
 Copyright 2018 Jeff Owrey
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see http://www.gnu.org/license.
 
 Circuit:
 * Main components: Arduino Uno, Ethernet shield, Mighty Ohm Geiger counter
 * Ethernet shield attached to pins 10, 11, 12, 13
 * In order to allow the MightyOhm to operate on the Uno's 5 volt power
   supply, and thus make the MightyOhm's serial output compatible with the
   Uno, the following has to be done (see MightyOhm schematic):
     1. Change R6 to 1K Ohm.
     2. Change R11 to 330 Ohm.
     3. Connect +5v from the Uno to MightyOhm J6 pin 1.
     4. Connect GND from the Uno to MightyOhm J6 pin 3.
     5. Connect D5 from the Uno to MightyOhm J7 pin 5.
   
 Misc Notes:
   As of this release the Uno's SRAM gets entirely maxed out by
   this program.  Any modifications to this program that requires
   additional memory seriously entails the risk that the modifications
   will cause the program to become un-stable.
   
 Revision History:  
   * v10 released 25 Feb 2014 by J L Owrey
   * v11 released 24 Jun 2014 by J L Owrey
       - optimization of processByteFromMightyOhm function to conserve SRAM
       - removal of non-used function code
       - defaults to APIPA IP address in the event a DHCP address
         cannot be obtained
   * v12 released 20 Dec 2014 by J L Owrey
       - removed Timestamp global variable to make more dynamic
         memory available for local variables
       - optimized clock network synch algorithm
       - optimized serial update algorithm
   * v13 released 22 Jul 2015 by J L Owrey
       - add use of "F" function to store constant strings in
         program flash memory in order to save SRAM space
   * v14 released 19 Aug 2015 by J L Owrey
       - add ability to respond to web a client request with either
         a JSON compatible string or a standard HTML document
   * v15 released 20 Feb 2016 by J L Owrey
       - improved http request handling
       - simplified raw data request format
       - simplified serial data output
   * v16 released 16 Sep 2017 by J L Owrey
       - added capability of rebooting via network http request,
         i.e., "http://{device IP address}/reset"
   * v17 released 29 Oct 2019 by J L Owrey
       - modified NTP server address user setting to allow fully
         qualified domain names as well as IP addresses.  Default
         NTP address set to "pool.ntp.org" per ntp.org request to use
         (in order to facilitate load balancing) the fully qualified
         domain name instead of individual server IP addresses.
   * v18 released 01 Nov 2019 by J L Owrey
       - fixed a bug in NTP time synchronization whereby the network time
         synchronization would only occur during boot up.  Thereafter NTP 
         time synchronization would fail to happen, resulting in a large 
         amount of clock drift.
   * v19 released 10 Jul 2022 by J L Owrey
       - improved processing of serial data from the MightyOhm Geiger counter

12345678901234567890123456789012345678901234567890123456789012345678901234567890         
*/

/***  PREPROCESSOR DEFINES  ***/

//#define DEBUG

/*
 Define the header and version number displayed at startup
 and also by the 'view settings' command.
*/
#define STARTUP_HEADER "\n\rRadmon v1.9 (c) 2022"
#define RADMON_VERSION "v1.9"
/*
 The following define sets the MAC address of the device.  This
 address is a permanent attribute of the device's Ethernet interface,
 and never, ever, should be changed.  This address was provided
 by the Arduino Ethernet shield manufacturer for use with this
 specific instance of the Ethernet shield.  This MAC address should
 be shown on a label affixed to the device housing.
*/
#define ETHERNET_MAC_ADDRESS 0x90, 0xA2, 0xDA, 0x0D, 0x84, 0xF6
/*
 The following defines an APIPA default address in the event that
 DHCP mode is ON and a DHCP address cannot be obtained.
*/
#define DEFAULT_APIPA_IP_ADDRESS "169.254.100.10"
/*
 The following define sets the period of a 'heartbeat' string sent
 out over the device's USB port.  This heartbeat consists of a serial
 data string containing the current radiation reading and GM time.
*/
#define SERIAL_UPDATE_INTERVAL 5000  //milli-seconds
/*
 The following define sets the port number the HTTP service will use to
 listen for requests from Internet clients.  Normally HTTP requests use
 port 80.
*/
#define HTTP_SERVER_PORT 80
/*
 The following defines are for configuring a local NTP client
 for synchronizing the local system clock to network time.
 Note that the ntp server address should be sent to the local
 server pool of the country where the radmon will be used.  See
 the web site 'ntp.org' for details. Users in the USA should set
 the ntp server to 'us.pool.ntp.org'.
*/
#define DEFAULT_NTP_SERVER_ADDR "us.pool.ntp.org"
#define NTP_PORT 8888
#define NTP_PACKET_SIZE 48 // NTP time in the first 48 bytes of the message
/*
 The following defines how often the system clock gets synchronized
 to network time.
*/
#define NTP_SYNCH_INTERVAL 43200 // number in seconds - 2 times a day
/*
 Number of retries if first time server request fails.
*/
#define TIME_SERVER_REQUEST_RETRIES 3
/*
 The following defines the size of the buffer space required for the
 serial data string from the Mighty Ohm Geiger counter.  The serial
 data string is defined as the text from newline character to newline
 character.
*/
#define MIGHTYOHM_DATA_STRING_LENGTH 65
/*
 The beginning of the MightyOhm data string always begins with the
 same three characters.  These three characters determine the 
 beginning of a new line of data from the MightyOhm.
*/
#define MIGHTYOHM_DATA_STRING_HEADER "CPS"
/*
 Set the depth of the string buffer that receives the http
 request header from the client.  Must be large enough to
 capture 'GET /rdata '.
*/
#define REQUEST_STRING_BUFFER_LENGTH 24

/***  LIBRARY MODULES USED  ***/

#include <Time.h>
#include <SPI.h>         
#include <Ethernet.h>
#include <EthernetUdp.h>
#include <SoftwareSerial.h>
#include <EEPROM.h>;

/***  GLOBAL DECLARATIONS ***/

/*
 Create and initialize a mac address object for the Ethernet interface. 
*/
byte mac[] = { ETHERNET_MAC_ADDRESS };
/*
 Create and initialize an HTTP server object.  The object is initialized
 to the TCP port the HTTP server will use to listen for clients.
*/
EthernetServer httpServer(HTTP_SERVER_PORT);
/*
 Create a UDP client object for sending packets to
 and receiveing packets from an NTP time server.
*/
EthernetUDP Udp;
/*
 Create a software serial port for receiving serial data from
 the MightyOhm. Note that the Uno pin 5 receives serial data
 FROM the MightyOhm.  The Uno's pin 6 is not used, as there is
 no need to send serial data to the MightyOhm. 
*/
SoftwareSerial MightyOhmTxOut(5, 6);
/*
 Create global variables to store the MightOhm data, next heartbeat
 time, and next synchronization time.
*/
char mightyOhmData[MIGHTYOHM_DATA_STRING_LENGTH + 1];
unsigned long nextSerialUpdateTime = 0;
unsigned long nextClockSynchTime = 0;
/*
 Create global variables to store the verbose mode state (ON or OFF)
 and the IP address mode state (static or DHCP).
*/
boolean bVerbose;
boolean bUseStaticIP;
/*
 Create and initialize global arrays to hold the current IP address
 and the NTP server address.
*/
byte ipAddr[4];
char timeServer[32];

/*** SYSTEM STARTUP  ***/

void setup()
{
  /*
   Open serial communications to and from the Uno's USB port.
  */
  Serial.begin(9600);
  /* 
   Print to the USB port a header showing Radmon
   version of this program and the copyright notice.
  */
  Serial.println(F(STARTUP_HEADER));
  /*
    Get the system configuration from EEPROM.
  */
  readSettingsFromEEPROM();
  /*
   Start up the Ethernet interface using either a static or
   DHCP supplied address (depending on stored system configuration).
  */
  if (bUseStaticIP)
  {
    Ethernet.begin(mac, ipAddr);
  }
  else
  {
    if (Ethernet.begin(mac) == 0)
    {
      /* DHCP not responding so use APIPA address */
      parseIpAddress(ipAddr, DEFAULT_APIPA_IP_ADDRESS);
      Ethernet.begin(mac, ipAddr);
      Serial.println(F("DHCP failed - using APIPA "));
    }
  }
  Serial.print(F("IP address: ")); Serial.println(Ethernet.localIP());
  /*
    Synchronize the system clock to network time.
  */
  synchronizeSystemClock();
  nextClockSynchTime = now() + NTP_SYNCH_INTERVAL;
  /*
   Start up the HTTP server.
  */
  Serial.println(F("Starting http server..."));
  httpServer.begin();
  /*
    Open serial communications to the MightyOhm device.
  */  
  MightyOhmTxOut.begin(9600);
  /*
   Initialize MightyOhm data string to empty.
  */
  mightyOhmData[0] = 0;
  return;
}

/*** MAIN LOOP ***/

void loop() {
  /*
   Check for user keyboard 'c' pressed.  This character switches
   to command mode.
  */   
  if (Serial.available()) {
    // get incoming byte
    if (Serial.read() == 'c') {
      commandMode();
    }
  }
  
  /*
    Poll serial input buffer from MightyOhm for new data and 
    process received bytes to form a complete data string.
  */
  while (MightyOhmTxOut.available()) {
    processByteFromMightyOhm(MightyOhmTxOut.read());
  }
  
  /*
    In verbose mode, send the MightyOhm data string to the
    serial port at regular intervals.
  */
  if (bVerbose) {
    if (millis() > nextSerialUpdateTime) {
      Serial.println(mightyOhmData);
      /* 
       Set the time for the next serial update to occur.
      */
      nextSerialUpdateTime = millis() + SERIAL_UPDATE_INTERVAL;
    }
  }
  
  /*
   Periodically synchronize local system clock to time
   provided by NTP time server.
  */
  if (now() > nextClockSynchTime) {
    synchronizeSystemClock();
    /* 
     Set the time for the next network NTP
     time synchronization to occur.
    */
    nextClockSynchTime = now() + NTP_SYNCH_INTERVAL;
  }
  
  /*
   Listen for and and process requests from HTTP clients.
  */  
  listenForNetworkClients();

  #ifdef DEBUG
    Serial.print("lp time: "); Serial.println(millis() - currentTime);
  #endif
}

/*
  Handle HTTP GET requests from an HTTP client.
*/  
void listenForNetworkClients()
{
  // listen for incoming clients
  EthernetClient client = httpServer.available();
  if (client) {
    char sBuf[REQUEST_STRING_BUFFER_LENGTH];
    byte i;
    char c, c_prev;
    boolean processedCommand;
    boolean firstLineFound;

    Serial.println(F("\nclient request"));

    i = 0;
    c_prev = 0;
    sBuf[0] = 0;
    processedCommand = false;
    firstLineFound = false;
  
    /*
     The beginning and end of an HTTP client request is always signaled
     by a blank line, that is, by two consecutive line feed and carriage 
     return characters "\r\n\r\n".  The following lines of code 
     look for this condition, as well as the url extension (following
     "GET").
    */
    
    while (client.connected())  {
      if (client.available()) {
        c = client.read();

        if (bVerbose) {
          Serial.print(c);
        }
              
        if (c == '\r') {
          continue; // discard character
        }  
        else if (c == '\n') {
          if (firstLineFound && c_prev == '\n') {
             break;
          }
        } 
        
        if (!processedCommand) {
          
          if (c != '\n') {
            if(i > REQUEST_STRING_BUFFER_LENGTH - 2) {
              i = 0;
              sBuf[0] = 0;
            }
            sBuf[i++] = c;
            sBuf[i] = 0;
          }

          if (!firstLineFound && strstr(sBuf, "GET /") != NULL) {
            firstLineFound = true;
            strcpy(sBuf, "/");
            i = 1;
          }

          if (firstLineFound && (c == '\n' || i >
              REQUEST_STRING_BUFFER_LENGTH - 2))
          {
            processedCommand = true;
          }
        }
        c_prev = c;
      } // end single character processing
    } // end character processing loop

    /*
     Send a standard HTTP response header to the
     client's GET request.
    */
    transmitHttpHeader(client);
    
    char * pStr = strtok(sBuf, " ");
    if (pStr != NULL)
    {
      if (strcmp(pStr, "/rdata") == 0) {
        transmitRawData(client);
      }
      else if (strcmp(pStr, "/") == 0) {
        transmitWebPage(client);
      }
      else if(strcmp(pStr, "/reset") == 0) {
        client.print(F("ok"));
        delay(10);
        // close the connection and reboot:
        client.stop();
        software_Reset();
      }
      else {
        transmitErrorPage(client);
      }
    }
    client.println();

    #ifdef DEBUG
      Serial.println(mightyOhmData);  //debug
    #endif
    
    // give the web browser time to receive the data
    delay(20);
    // close the connection:
    client.stop();
  }
}

/*
 Send standard http response header back to
 requesting client,
*/
void transmitHttpHeader(EthernetClient client) {
  client.print(F("HTTP/1.1 200 OK\r\n"          \
                 "Content-Type: text/html\r\n"  \
                 "Connnection: close\r\n"       \
                 "Refresh: 5\r\n"               \
                 "\r\n"                         \
                 ));
}

/*
 Send to the client the MightyOhm Geiger counter's
 current readings, embedded in an HTML document.
*/
void transmitWebPage(EthernetClient client) {
  char strBuffer[MIGHTYOHM_DATA_STRING_LENGTH];

  strcpy(strBuffer, mightyOhmData);
  /*
   Send the actual HTML page the user will see in their web
   browser.
  */
  client.print(F("<!DOCTYPE HTML>"                               \
                 "<html><head><title>Radiation Monitor</title>"  \
                 "<style>pre {font: 16px arial, sans-serif;}"    \
                 "p {font: 16px arial, sans-serif;}"             \
                 "h2 {font: 24px arial, sans-serif;}</style>"    \
                 "</head><body><h2>Radiation Monitor</h2>"       \
                 "<p><a href=\"http://intravisions.com/\">"      \
                 "<i>IntraVisions.com</i></a></p>"               \
                 "<hr>"));
  /* Data Items */             
  client.print(F("<pre>UTC &#9;"));
  client.print(strtok(strBuffer, ","));
  client.print(F("<br>"));
  client.print(strtok(NULL, ", "));
  client.print(F(" &#9;"));
  client.print(strtok(NULL, ", "));
  client.print(F("<br>"));
  client.print(strtok(NULL, ", "));
  client.print(F(" &#9;"));
  client.print(strtok(NULL, ", "));
  client.print(F("<br>"));
  client.print(strtok(NULL, ", "));
  client.print(F(" &#9;"));
  client.print(strtok(NULL, ", "));
  client.print(F("<br>"));
  client.print(F("Mode &#9;"));
  client.print(strtok(NULL, ", "));
  client.print(F("<br></pre></body></html>"));
}  

/*
 Send to the client the MightyOhm Geiger counter's
 current readings, embedded in a JSON compatible string.
*/
void transmitRawData(EthernetClient client) {
  char strBuffer[MIGHTYOHM_DATA_STRING_LENGTH];

  strcpy(strBuffer, mightyOhmData);
  /*
   Format and transmit a JSON compatible data string.
  */
  client.print(F("$,UTC="));
  client.print(strtok(strBuffer, " "));
  client.print(F(" "));
  client.print(strtok(NULL, ", "));
  client.print(F(","));
  client.print(strtok(NULL, ", "));
  client.print(F("="));
  client.print(strtok(NULL, ", "));
  client.print(F(","));
  client.print(strtok(NULL, ", "));
  client.print(F("="));
  client.print(strtok(NULL, ", "));
  client.print(F(","));
  client.print(strtok(NULL, ", "));
  client.print(F("="));
  client.print(strtok(NULL, ", "));
  client.print(F(","));
  client.print(F("Mode="));
  client.print(strtok(NULL, ", "));
  client.print(F(",#\n"));
}

/*
 Send an error message web page back to the requesting
 client when the client provides an invalid url extension.
*/
void transmitErrorPage(EthernetClient client) {
  client.print(F("<!DOCTYPE HTML>"                                      \
                 "<html><head><title>Radiation Monitor</title></head>"  \
                 "<body><h2>404 Not Found</h2>"                         \
                 "</body></html>"
                 ));
}

/*
 Process bytes received from the MightyOhm Geiger counter,
 one at a time, to create a well formed string.
*/
void processByteFromMightyOhm( char RxByte )
{
  static char readBuffer[MIGHTYOHM_DATA_STRING_LENGTH];
  static byte cIndex = 0;
  int headerPos = 0;
  
  /*
     Discard carriage return characters.
  */
  if (RxByte == '\r')
  {
    return;
  }
  /*
   A new line character indicates the line of data from
   the MightyOhm is complete and can be written to the
   MightyOhm data buffer.
  */
  else if (RxByte == '\n')
  {
    /*
     If a complete line of data has been received from the MightyOhm
     Geiger counter, then add a timestamp and copy the line to the
     MightyOhm data buffer.  A line is complete if the line
     begins with a proper header and ends with a newline character.
    */
    headerPos = strstr(readBuffer, MIGHTYOHM_DATA_STRING_HEADER) - readBuffer;
    if( headerPos == 0 )
    {
      /*
       Insert a timestamp at the beginning of the MightyOhm data buffer.
       */
      sprintf( mightyOhmData, "%d:%02d:%02d %d/%d/%d, ",       \
            hour(), minute(), second(), month(), day(), year() );
      /*
       Now copy the rest of the data in the temporary read buffer to the
       MightyOhm data buffer.
      */ 
      strcat(mightyOhmData, readBuffer);
    }
    /*
     Flush the temporary read buffer.
    */
    cIndex = 0;
    readBuffer[0] = 0;
    return;
  }
  /*
   Read characters into a temporary buffer until
   the line of data is complete or the buffer is full.
  */
  if(cIndex < MIGHTYOHM_DATA_STRING_LENGTH)
  {
    readBuffer[cIndex] = RxByte;
    cIndex += 1;
    readBuffer[cIndex] = 0;
  }
  return;
} 

/*
 Synchronize the local system clock to
 network time provided by NTP time server.
*/
void synchronizeSystemClock()
{
  byte count;

  Serial.print(F("Synchronizing with NTP server: "));
  Serial.print(timeServer);Serial.println(F("..."));

  /*
   * NOTICE!!!    NOTICE!!!   NOTICE!!!
   * Due to a bug in the Ethernet library, it is necessary to reinitialize 
   * the ethernet UDP library everytime after an  after an EthernetClient 
   * class object has been instantiated.  Also, the Udp stop() function 
   * must be called at the end of each session.
   */
  Udp.begin(NTP_PORT);  // see above comment

  count = 1;
  while (true)  // Attempt to synchronize 3 times
  {
    if (syncToNetworkTime() == 1) {
      //  Synchronization successful
      break;
    }
    if (count == TIME_SERVER_REQUEST_RETRIES) {
      Serial.print(F("synch failed: "));
      break;
    }
    count++;
    delay(2000);
  }
  if (count > 1) {
    Serial.print(count);Serial.println(F(" retries"));
  }
  
  Udp.stop(); // see above comment
  return;
}

/* 
  Send a UDP request packet to an NTP time server and listen for a reply.
  When the reply arrives, parse the received UPD packet and compute unix
  epoch time.  Then set the local system clock to the epoch time.
*/
int syncToNetworkTime()
{
  /*
   Send a request to the NTP time server.  Define a buffer to hold outgoing
   and incoming packets.
  */
  byte packetBuffer[ NTP_PACKET_SIZE]; // buffer to hold packets
  /*
   Send an NTP packet to the time server and allow for network lag
   before checking if a reply is available.
  */
  sendNTPpacket(timeServer, packetBuffer);
  /*
   Wait for response from NTP time server.
  */
  delay(1000);  // allow 1000 milli-seconds for network lag

  if ( Udp.parsePacket() )
  {  
    /*
     A UDP packet has arrived, so read the data from it.
    */
    Udp.read( packetBuffer, NTP_PACKET_SIZE );
    /*
     The timestamp starts at byte 40 of the received packet and is four
     bytes, or two words, long. First, esxtract the two words.
    */
    unsigned long highWord = word(packetBuffer[40], packetBuffer[41]);
    unsigned long lowWord = word(packetBuffer[42], packetBuffer[43]);
    /*  
     Combine the four bytes (two words) into a long integer
     this is NTP time (seconds since Jan 1 1900).
    */
    unsigned long secsSince1900 = highWord << 16 | lowWord;
    /*  
     Now convert NTP time into UTC time.  Note that
     Unix time starts on Jan 1 1970. In seconds,
     that's 2208988800.  Therfore,
     
         epoch = secsSince1900 - 2208988800UL
         
     Set the local system clock with this value.
    */
    setTime(secsSince1900 - 2208988800UL);
    return 1;
  }
  else
  {
    return 0;
  } /* end if */
}

/*
 Send an NTP request to the NTP time server.
*/
void sendNTPpacket( char * serverAddress, byte * packetBuffer )
{
  /*
   Set all bytes in the buffer to 0.
  */
  memset( packetBuffer, 0, NTP_PACKET_SIZE );
  /*
   Initialize values needed to form NTP request.
  */
  packetBuffer[0] = 0b11100011;  // LI, Version, Mode
  packetBuffer[1] = 0;           // Stratum, or type of clock
  packetBuffer[2] = 6;           // Polling Interval
  packetBuffer[3] = 0xEC;        // Peer Clock Precision
  /*
   Set the remaining 8 bytes to zero for Root Delay & Root Dispersion.
  */
  packetBuffer[12]  = 49; 
  packetBuffer[13]  = 0x4E;
  packetBuffer[14]  = 49;
  packetBuffer[15]  = 52;
  /*
   All NTP fields have been given values, so now
   send a packet requesting a timestamp.
  */
  Udp.beginPacket( serverAddress, 123 ); // NTP requests are to port 123
  Udp.write( packetBuffer, NTP_PACKET_SIZE );
  Udp.endPacket();
  return;
}

/***  COMMAND LINE INTERFACE  ***/

/*
 Print a command menu to the USB port.  Then wait for a
 response from the user.  When the response has been
 received, execute the command.
*/
void commandMode()
{
  char sCmdBuf[2];
  
  getCurrentIP();  // used for display of settings

  Serial.println();
  displayMenu(); // display the menu
  
  while(true)
  {
    /*
     Get the command from the user.
    */
    Serial.print(F(">"));
    getSerialLine(sCmdBuf, 2);
    Serial.print(F("\n\r"));
    /* 
     Execute the command.
    */
    switch (sCmdBuf[0])
    {
      case '0':
        displayMenu();
        break;
      case '1':
        displaySettings();
        break;
      case '2':
        setIP();
        break;
      case '3':
        setNTPServer();
        break;
      case '4':
        toggleVerbose();
        break;
      case '5':
        readSettingsFromEEPROM();
        return;
      case '6':
        writeSettingsToEEPROM();
        /*
         A software reboot is necessary to force the 
         Arduino to request an IP address from a DHCP
         server or to initialize the Ethernet interface
         with a static IP address.
        */
        delay(100);
        software_Reset();
        return;
      default:
        Serial.println(F("invalid command"));
    } /* end switch */
  } /* end while */
  return;
}

/*
 Displays the menu.
*/
void displayMenu()
{
  /*
   Print the menu.
  */
  Serial.print( F("Available commands (type a number):\r\n" \
                  "  0 - display this menu\r\n"    \
                  "  1 - view settings\r\n"        \
                  "  2 - set IP address\r\n"       \
                  "  3 - set NTP server\r\n"       \
                  "  4 - toggle verbose\r\n"       \
                  "  5 - exit without saving\r\n"  \
                  "  6 - save & restart\r\n"       \
              ));  
}

/*
 Displays the current system settings.  Displays
 RadMon software version, local IP address, NTP server
 address, and verbose mode setting.
*/
void displaySettings()
{
  char sBuf[16];
  
  // Display RadMon version
  Serial.print(F("Firmware "));
  Serial.print(F(RADMON_VERSION));
  Serial.println();

  // Display local IP address
  sprintf(sBuf, "%d.%d.%d.%d", ipAddr[0], ipAddr[1], ipAddr[2], ipAddr[3]);
  if (bUseStaticIP)
  {
    Serial.print(F("Static IP: "));
  }
  else
  {
    Serial.print(F("DHCP IP: "));
  }
  Serial.println(sBuf);
  
  // Display NTP server IP address
  Serial.print(F("NTP server: ")); 
  Serial.println(timeServer);

  // Display verbose mode setting
  printVerboseMode();
  return;
}

/*
 Sets the local IP address. If the user sends a carriage
 return as the first character, then switch to acquiring
 IP address via DHCP server.
*/
void setIP()
{
  char sBuf[16];

  Serial.print(F("enter IP (<CR> for DHCP): "));
  getSerialLine(sBuf, 16);
  
  if(strlen(sBuf) == 0)
  {
    bUseStaticIP = false;
    strcpy(sBuf, "0.0.0.0");
    parseIpAddress(ipAddr, sBuf);
  }
  else
  {
    bUseStaticIP = true;
    parseIpAddress(ipAddr, sBuf);
  }
  Serial.println();
  return;
}

/*
 Sets the NTP server IP address.  If the user sends a
 carriage return as the first character, then use the
 default IP address for the NTP server.
*/
void setNTPServer()
{
  char sBuf[32];
  
  Serial.print(F("enter NTP server (<CR> for default): "));
  getSerialLine(sBuf, 32);

  if (strlen(sBuf) == 0)
  {
    strcpy(timeServer, DEFAULT_NTP_SERVER_ADDR);
  }
  else
  {
    strcpy(timeServer, sBuf);
  }
  Serial.println();
  return;
}

/*
 Turns verbose mode ON or OFF.
*/
void toggleVerbose()
{
  bVerbose = !bVerbose;
  printVerboseMode();
  return;
}

/***  GENERAL HELPER FUNCTIONS  ***/

/*
 Print current verbose mode.
*/
void printVerboseMode()
{
  Serial.print(F("Verbose: "));
  if (bVerbose)
  {
    Serial.println(F("ON"));
  }
  else
  {
    Serial.println(F("OFF"));
  }
  return;
}

/*
 Get the current IP address from the Ethernet interface
*/
void getCurrentIP()
{
  ipAddr[0] = Ethernet.localIP()[0];
  ipAddr[1] = Ethernet.localIP()[1];
  ipAddr[2] = Ethernet.localIP()[2];
  ipAddr[3] = Ethernet.localIP()[3];
  return;
}

/*
 Gets a line of data from the user via USB port.
*/
char* getSerialLine(char* sBuffer, int bufferLength)
{
  byte index;
  char cRx;

  /* 
   Discard extranious characters that may still be in the
   USB serial stream read buffer.  Most often these characters
   will be unprocessed carriage return or line feed characters.
  */
  delay(10);
  while (Serial.available())
  {
    cRx = Serial.read();
  }

  /*
   Read and process characters from the user as they arrive in
   the USB serial read buffer.
  */
  index = 0;
  while(true)
  {
    /*
     Wait until the user starts pressing keys and bytes
     arrive in the serial read buffer.
    */
    if (Serial.available())
    {
      cRx = Serial.read();
      if (cRx == '\r' || cRx == '\n')
      {
        /*
         The user has finished typing the command and
         has pressed the Enter key. So, discard the
         carriage return and newline characters and then
         return control to the calling function.
        */
        break;
      }
      else if (cRx == 8 || cRx == 127)
      {
        if (index > 0)
        {
          /*
           The user has hit the delete-backspace key,
           so send out a backspace, followed by a space,
           followed by another backspace character.
           This allows for in-line ediiting.
          */
          Serial.write(8);
          Serial.write(32);
          Serial.write(8); 
          index -= 1;
        }
      }
      else if ( index < (bufferLength - 1) )
      {
        /*
         The received character is valid, so write it
         to the buffer. Once the buffer becomes full
         do not write any more characters to it.  When
         the user pressses the enter key, the string
         will be null terminated and control will pass
         back to the calling function.
        */
        Serial.write(cRx); // echo character to terminal
        sBuffer[index] = cRx;
        index += 1;
      } /* end if */
    } /* end if */
  } /* end while */
  sBuffer[index] = 0; // terminate the string
  return sBuffer;
}

/*
 Writes system configuration settings to non-volitile
 EEPROM.  The items written are the local IP address,
 the NTP server IP address, the state of verbose mode,
 and local IP mode (static or DHCP).
*/
void writeSettingsToEEPROM()
{
  byte ix;
  char c;
  for (ix = 0; ix < 4; ix++)
  {
    EEPROM.write(ix, ipAddr[ix]);
  }
  EEPROM.write(4, bVerbose);
  EEPROM.write(5, bUseStaticIP);
  ix = 0;
  while(1) {
    c = timeServer[ix];
    EEPROM.write(6 + ix, c);
    if (c == 0 || ix > 31) break;
    ix++;
  }
  return;
}

/*
 Reads system configuration settings from non-volitile
 EEPROM.  The items read are the local IP address,
 the NTP server IP address, the state of verbose mode,
 and local IP mode (static or DHCP).
*/
void readSettingsFromEEPROM()
{
  byte ix;
  char c;
  for (ix = 0; ix < 4; ix++)
  {
    ipAddr[ix] = EEPROM.read(ix);
  }
  bVerbose = EEPROM.read(4);
  bUseStaticIP = EEPROM.read(5);
  ix = 0;
  while(1) {
    c = EEPROM.read(6 + ix);
    timeServer[ix] = c;
    if (c == 0 || ix > 31) break;
    ix++;
  }
  return;
}

/*
 Parses an IP address given in "nnn.nnn.nnn.nnn" string
 format into four bytes and stores them in an array. Note
 that this function destroys the contents of the sIP
 character array.  Therefore this array cannot be
 reinitialized after calling this function.
*/
void parseIpAddress(byte* byBuf, char* sIP)
{
  byBuf[0] = atoi(strtok(sIP, "."));
  byBuf[1] = atoi(strtok(NULL, "."));
  byBuf[2] = atoi(strtok(NULL, "."));
  byBuf[3] = atoi(strtok(NULL, "."));
  return;
}

/*
 Restarts the Uno and runs this program from beginning.  This
 function gets called after a change made from the user
 interface when the user selects "save and restart".
*/
void software_Reset() 
{
  asm volatile ("  jmp 0");
  return; 
}  

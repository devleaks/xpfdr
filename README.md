# Flight Data Recorder for X-Plane

Flight Data Recorder is a customizable flight data recording plugin for X-Plane flight simulator.
It generates X-Plane FDR files from a running flight.


# Operations

The plugin installs a permanent supervisor procedure that determines if the FDR recording needs to occur.
It automatically starts when aircraft movement is detected, it stops when there is no movement for 10 minutes.

Alternatively, it is possible to manually start and stop the recording through the _Start or stop FDR_ Plugin Menu entry.
An _enabled_ marker (white dot) sits in front of the menu entry when the recorder is running.
It is possible to bind the _Start or stop FDR_ command to a cockpit or joystick button.

When recording, FDR detects and logs nearby navigation aids.
FDR logs navaids around the aircraft and navaids used by the aircraft
by finding them through their frequencies.
FDR logs navaids of type VOR, DME, NDB, fixes, and airports.


## Output

FDR recording files are stored in the `<X-Plane 12 Folder>/Output/fdr/` folder.
Files are named after the start time of the record.


### FDR File Format

FDR files slightly diverge from "formal" FDR v4 format
by allowing a fractional part to seconds (milliseconds or microseconds)
for more precision.


### FDR Meta Data

In addition to mandatory information in the record file,
FDR stores meta data information for further processing and handling.
Meta data is saved as a FDR record COMMent and can be ignored.
Meta Data is used, for example, by the FDR reader.

In the FDR record file, the recorder writes

  - Meta data about the dataref requested (units, sizes, etc.)
  - The list of units for each column in a record if available.
  - A list of columns names for a record
  - The start and stop date/time of the recording in both simulator UTC time and computer local time.

Information is written as a comment before the data records.


## Recording Preferences

On startup, FDR locates and loads preferences stored in a preference file.
Preferences are configuration values (like the frequency of the collection, etc.)
and the list of X-Plane datarefs to be monitored.

There can be several preference files in X-Plane, one per aircraft, and a generic global one.

FDR first look for a aircraft specific FDR preference file in the home directory of an aircraft
`<X-Plane 12 Folder>/Aircraft/.../myaircraft/fdr.prf`.
This allows for recording *aircraft-specific* data.
This is very convenient as values recorded for a smaller GA or a larger airliner may differ.
(When the aircraft is changed, its preferences are unloaded and the preferences of the new aircraft are loaded.)

If no aircraft specific preference file is found, FDR look in X-Plane Preference folder
`<X-Plane 12 Folder>/Output/preferences/fdr.prf`.
This preference file should only contain generic data, not specific to particular aircraft.


The preference file is a Yaml-formatted readable text file structured as follow:

```yaml
fdr_arch: APPLE
description: Demonstration preference file
frequency: 5
report_frequency: 100
chocks: AirbusFBW/Chocks
commands:
  - sim/map/show_current
fdr_info:
  - name: aircraft_icao
    dataref: sim/aircraft/view/acf_ICAO
fdr_data:
  - name: true_air_speed
    dataref: sim/flightmodel/position/true_airspeed
    unit: m/s
  - name: vertical_speed
    dataref: sim/cockpit2/gauges/indicators/vvi_fpm_pilot
    unit: m/s # dataref is ft/min, converted by callback
    callback: ${x} 0.00508 *
```

 - `fdr_arch` identifies the FDR file architecture, either APPLE or IBM. Used to determine line termitors.
    (CR for APPLE, CR+LF for IBM).

 - `description` is an information field used in the log file to identify the preferences used.

 - `frequency` is the time, in seconds, between 2 data collection.

 - `report_frequency` is the number of data collections reported in the log file.
    It allows for simple monitoring of the data collection process.
    Above, every 100 records, a message is written into log.txt.

 - `chocks` is a dataref name that will be used to check whether chocks are set (non zero value) or not (zero value).

 - `fdr_info` is a list of _Data Definition_ to identy a dataref value that is fetched only *once*
   at the start of the recording.
   The value is saved as a comment in the header file of the recording.
   Example of FDR info fields may include departure and arrival airport, weather information...
   as long as the data is available as a dataref.

 - `fdr_data` is a list of _Data Definition_ that are collected and reported.

 - `commands` is a list of commands, expressed as X-Plane path.
    The execution of any of these command in logged.
    (This is an experimental feature.)


### Collected _Data Definition_

Collected data is described by the following fields:

  - `name`: Name of the data field, used as a column header in the FDR file. Mandatory.
  - `dataref`: Name of dataref, its value is part of the data record. Mandatory.
  - `units`: Information field of dataref value unit. Saved as a comment in the header of the record file.
     Optional but highly recommanded.
  - `factor`: Convertion factor (float value) used by FDR DREF parameter. Optional.
  - `callback`: Reverse polish notation expression, in which `${x}` is replaced with the dataref value. Optional.

The callback string is a Reverse polish notation expression.
Its goal is a provide an easy mechanism to alter raw dataref values to meaningful record value
with minimal impact.

Typically, it can be used for unit adjustment expressions like

 - `${x} 0.00508 *` : convert feet per minute to meters per second (see example above)
 - `${x} 0.3048 *` : convert ft to m
 - `${x} 32 - 1.8 /` : convert Farenheit to Celsius for temperature
 - `${x} 0 round 0 eq` : returns 1.0 when value rounds to zero

In the above expression `${x}` is the raw _numeric_ dataref value.

This scheme is a alternate, more sophisticated method than the built-in FDR DREF factor parameter,
which remains available as the factor attribute in the Data Definition.


### Experimental Feature for Array Datarefs

It is possible to list dataref with a python `slice()` syntax.

```
  - name: eng_n1
    dataref: sim/flightmodel/engine/ENGN_N1_[0:4]
```

Range `0:4` is called a python array _slice_ and follow a specific syntax.

The above slice is equivalent to

```
  - name: eng_n1[0]
    dataref: sim/flightmodel/engine/engn_n1_[0]
  - name: eng_n1[1]
    dataref: sim/flightmodel/engine/engn_n1_[1]
  - name: eng_n1[2]
    dataref: sim/flightmodel/engine/engn_n1_[2]
  - name: eng_n1[3]
    dataref: sim/flightmodel/engine/engn_n1_[3]
```

Alternatively, it is possible to list indices of interest like so:

```
  - name: eng_n1
    dataref: sim/flightmodel/engine/ENGN_N1_[1,3]
```

which is equivalent to

```
  - name: eng_n1[1]
    dataref: sim/flightmodel/engine/engn_n1_[1]
  - name: eng_n1[3]
    dataref: sim/flightmodel/engine/engn_n1_[3]
```

Index list must be a comma separated list of integer value.

The drawback of these slices or multi-index selection
is that all values of the dataref array are fetched
during each data collection, but only those values that are requested are returned.
(On a longer term, this can become a performance issue if many arrays are requested.
As an alternative, it is always possible to fetch a single array value.)


*This is an experimental feature and may not work as expected. Use with caution.*


### Default Behavior and Values

Without preference file, FDR generates Version 4 file for APPLE architecture.
The recording frequency is 10 seconds, and reporting frequency occurs every 100 records.
(Reporting is written in X-Plane log.txt file and is useful to monitor that FDR is logging
events in the FDR file.)
Without preference file, FDR only record mandatory header fields once,
and mandatory data (time, position, attitude, 2 convenient values, total 9 values, see below) every 10 seconds.
It is a lightweight process that has no impact on the frame rate.

When the plugin is installed, this occurs automatically without user interaction.


### Mandatory Data

FDR collects the following data which is required in the header of the FDR file:

  - `ACFT`: the aircraft file to use, with full directory path from the X-Plane folder
    (ex: `Aircraft/Airbus/ToLiss A321.acf`).
  - `TAIL`: tail number of the aircraft (ex: `C-GTLU`). Must come immediately after the `ACFT` line.
  - `TIME`: ZULU time of the begining of the flight (ex: `18:54:32`) (TIME is optional in FDR v4).
  - `DATE`: date of the flight (ex: `03/18/26`, month/day/year format).
  - `PRES`: sea-level pressure during the flight in inches Hg (ex: `29.92`).
  - `TEMP`: sea-level temperatre during the flight in degrees Farenheit (ex: `65`).
  - `WIND`: wind during th flight in degrees, then knots (ex: `230,17`: 270°, 17kt).


FDR collects the following data which is the minimum required in the FDR file:

  - UTC time of day (with fractional second if available: `18:54:32.678324`)
  - longitude
  - latitude
  - altitude (MSL, WSG84 ellipsoid, in feet)
  - heading
  - pitch
  - roll

UTC time is the simulator UTC time when the flight occurs.

In addition to these mandatory values, FDR always records the following two convenient values:

  - ground speed
  - elevation (above ground level, in meters)

Both are collected to display conventional flight report with the viewer.

In a record, all values are decimal floating point values, separated by a `,`
with the exception of time which is formatted as shown above and always is
the first value of the record.


### Optiopnal Additional Data

Additional `fdr_data` is saved after these mandatory values as additional columns,
one column per additional data.


# Installation

Flight Data Recorder is a X-Plane plugin written in python.
It needs [XPPython3](https://xppython3.readthedocs.io/en/latest/) X-Plane plugin to run.

Install `PI_fdr.py` file in `<X-Plane 12 Folder>/Resources/plugins/PythonPlugins`.
Reload scripts in XPPython3 through the Plugin menu entry.

On first start, or after XPPython3 upgrades, the script may download missing python package like Yaml.
When completed, simply reload XPPython3 script again.


## Reader

There is a compagnon script `fdr_reader.py` that reads a FDR record file and generates

  - a GeoJSON file that can be viewed on [geojson.io](geojson.io) for example,
  - a CSV file with all data.

In the GeoJSON file, FDR data is added as a list of feature properties along with (3D) Point position.
The GeoJSON file also contain additional Features like the whole flight path as a LineString.

In the CSV file, no meta data is available, just records.
(There is no nav aid location, and no command trigger report in the CSV file.)


## Viewer

There is a compagnon web page `frd_viewer.html` to display either a GeoJSON formatted FDR file
or a Version 4 FDR file in a simple, basic map and charting page.

You can drop FDR v4 files, GeoJSON or CSV files *generated by fdr_reader*.

*The viewer is under development.*

The layout of charts is automagic, based on the number of featured data.

If the FDR file has been produced by the plugin,
it contains additional information and meta data
that allow for better display of information in the viewer.

  - Collected navaids are displayed,
  - Moment of execution of monitored commands are also shown.

If using FDR default values/settings recorded without preference file,
FDR Viewer display a Flightradar24/Flight Aware type of graph with

  - A map of the flight,
  - Ground speed and altitude MSL,
  - Mandatory values collected by FDR: Heading, pitch, and roll.

![fdr viewer](https://raw.githubusercontent.com/devleaks/xpfdr/refs/heads/main/fdr_viewer/media/fdr_viewer.png)

If additional values are requested through a preference file,
all additional values are presented in similar graphs.

Map is presented thanks to [Leaflet](https://leafletjs.com).
Charts are presented thanks to [ChartJS](https://www.chartjs.org).
All code by devleaks, a HI. Hence bugs.


## Troubleshooting

FDR logs a few messages in X-Plane `log.txt` file, especially reports it is working
and logging events.

The script will not work on X-Plane release 11 as it depends on newer XPPython3 features.


# See Also

  - `<X-Plane 12 Folder>/Instruction/FDR Example Version 3.fdr`
  - `<X-Plane 12 Folder>/Instruction/FDR Example Version 4.fdr`

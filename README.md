# Flight Data Recorder for X-Plane

Flight Data Recorder is a customizable flight data recording plugin for X-Plane flight simulator.
It generates X-Plane FDR files (version 3 or 4) from a running flight.


## Recording

The plugin installs a permanent supervisor procedure that determines if the FDR recording needs to occur.
It automatically starts when a movement is detected, it stops when there is no movement for 10 minutes.

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

FDR slightly diverge from "formal" FDR v3 and v4 format
by allowing a fractional part to seconds (milliseconds or microseconds)
for more precision.


### FDR Meta Data

In addition to mandatory information in the record file,
FDR stores meta data information for further processing and handling.
Meta data is saved as a FDR record COMMent and can be ignored.
Meta Data is used, for example, by the FDR reader.

In the FDR record file, the recorder writes

  - The list of units for each column in a record if available.
  - A list of columns names for a record

Information is written as a comment before the data records.


## Recording Preferences

FDR first look for a aircraft specific FDR preference file in the home directory of an aircraft
`<X-Plane 12 Folder>/Aircraft/.../myaircraft/fdr.prf`.
This allows for recording *aircraft-specific* data.
This is very convenient as values recorded for a smaller GA or a larger airliner
differ slightly.

Preferences are looked up again when the aircraft is changed.

IF no aircraft specific preference file is found, FDR look in X-Plane Preference folder
`<X-Plane 12 Folder>/Output/preferences/fdr.prf`.
This preference file should only contain generic data, not specific to particular aircraft.


The preference file is a Yaml-formatted readable text file structured as follow:

```yaml
fdr_version: 4
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

 - `fdr_version` identifies the version of the recording file that is generated. Version 3 and 4 are supported.

 - `fdr_arch` identifies the FDR file architecture, either APPLE or IBM. Used to determine line termitors.

 - `description` is an information field used in the log file to identify the preferences used.

 - `frequency` is the time, in seconds, between 2 data collection.

 - `report_frequency` is the number of data collections reported in the log file.
    It allows for simple monitoring of the data collection process.
    Every 100 records, a message is written into log.txt

 - `chocks` is a dataref name that will be used to check whether chocks are set (non zero value) or not (zero value).

 - `fdr_info` is a list of data structure to identy a dataref value that is fetched *once* only at the start of the recording.
   The value is saved as a comment in the header file of the recording.
   Example of FDR info fields may include departure and arrival airport, weather information...
   as long as the data is available as a dataref.

 - `fdr_data` is a list of data structure that are collected and reported.

 - `commands` is a list of commands, expressed as X-Plane path.
    The execution of any of these command in logged.
    (This is an experimental feature.)


### Collected Data Structure

Collected data is described by the following fields:
  - `name`: Name of the data field, used as a column header in the FDR file. Mandatory.
  - `dataref`: Name of dataref, its value is part of the data record. Mandatory.
  - `units`: Information field of dataref value unit. Saved as a comment in the header of the record file.
     Optional but highly recommanded.
  - `factor`: Convertion factor (float value) used by FDR DREF parameter. Optional.
  - `callback`: Reverse polish notation expression, in which `${x}` is replaced with the dataref value. Optional.

Callback expression is very limited in size and capabilities.
It is a Rever Polish Notation expression.
Its goal is a provide an easy mechanism to alter raw dataref values to meaningful record value
with minimal impact.

Typical, unit adjustment expressions like

 - `${x} 0.00508 *` : convert feet per minute to meters per second (see example above)
 - `${x} 0.3048 *` : convert ft to m
 - `${x} 32 - 1.8 /` : convert Farenheit to Celsius for temperature
 - `${x} 0 round 0 eq` : returns 1.0 when value rounds to zero

In the above expression `${x}` is the raw _numeric_ dataref value.

This scheme is a alternate, more sophisticated method than the built-in FDR DREF factor parameter.


### Experimental Feature for Array datarefs

It is possible to list dataref with a python `slice()` syntax.

```
  - name: eng_n1
    dataref: sim/flightmodel/engine/ENGN_N1_[0:4]
```

Range `0:4` is called a python array _slice_ and follow a specific syntax.

The above slice is equivalent to

```
  - name: eng_n1[0]
    dataref: sim/flightmodel/engine/ENGN_N1_[0]
  - name: eng_n1[1]
    dataref: sim/flightmodel/engine/ENGN_N1_[1]
  - name: eng_n1[2]
    dataref: sim/flightmodel/engine/ENGN_N1_[2]
  - name: eng_n1[3]
    dataref: sim/flightmodel/engine/ENGN_N1_[3]
```

Alternatively, it is possible to list indices of interest like so:

```
  - name: eng_n1
    dataref: sim/flightmodel/engine/ENGN_N1_[1,3]
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
and mandatory data (time, position, attitude, total 7 values, see below) every 10 seconds.

It is a lightweight process that has no impact on the frame rate.

When the plugin is installed, this occurs automatically without user interaction.


### Mandatory Data

FDR collects the following data which is required in the header of the FDR file:
  - `ACFT`: the aircraft file to use, with full directory path from the X-Plane folder
    (ex: `Aircraft/Heavy Metal/Boeing 747.acf`).
  - `TAIL`: tail number of the aircraft (ex: `N8141Q`). Must come immediately after the `ACFT` line.
  - `TIME`: ZULU time of the beginning of the flight (ex: `18:54:32`).
  - `DATE`: date of the flight (ex: `03/18/26`, month/day/year format).
  - `PRES`: sea-level pressure during the flight in inches Hg (ex: `29.92`).
  - `TEMP`: sea-level temperatre during the flight in degrees Farenheit (ex: `65`).
  - `WIND`: wind during th flight in degrees then knots (ex: `230,17`).

(Note: FDR Version 3 and Version 4 _required_ fields differ slightly.)

FDR collects the following data which is the minimum required in the FDR file:
  - UTC time of day (with fractional second if available)
  - longitude
  - latitude
  - elevation (MSL, WSG84 ellipsoid, in feet)
  - heading
  - pitch
  - roll

In addition to these mandatory values, FDR always records the following two convenient values:
  - ground speed
  - altitude (above ground level, in meters)
Both are collected to display conventional flight report with the viewer.

`fdr_data` data is saved after these mandatory values as additional columns,
one column per additional data.


## Installation

Flight Data Recorder is a X-Plane plugin written in python.
It needs [XPPython3](https://xppython3.readthedocs.io/en/latest/) X-Plane plugin to run.

Install `PI_fdr.py` file in `<X-Plane 12 Folder>/Resources/plugins/PythonPlugins`.
Reload scripts in XPPython3 through the Plugin menu entry.

On first start, or after XPPython3 upgrades, the script may download missing python package like Yaml.
When completed, simply reload XPPython3 script again.


## Reader

There is a compagnon script `fdr_reader.py` that reads a FDR record file and generates
  - a GeoJSON file that can be viewed on geojson.io for example,
  - a CSV file with all data.

In the GeoJSON file, FDR data is added as a list of feature properties along with (3D) Point position.


## Viewer

There is a compagnon web page `frd_viewer.html` to display either a GeoJSON formatted FDR file
or a Version 4 FDR file in a simple, basic map and charting page.

You can drop FDR v3 or v4 files, GeoJSON or CSV files *generated by fdr_reader*.

*The viewer is under development.*

The layout of charts is automagic, based on the number of featured data.

If the FDR file has been produced by the plugin,
it contains additional information and meta data
that allow for better display of information in the viewer.

  - Collected navaids are displayed,
  - Moment of execution of monitored commands are also shown.

If using FDR default values/settings without preference file,
FDR Viewer display a Flightradar24/Flight Aware type of graph with
  - A map of the flight,
  - Ground speed and altitude above ground,
  - Mandatory values collected by FDR: Heading, pitch, and roll.

If additional values are requested through a preference file,
all additional values are presented in similar graphs.

![fdr viewer](https://raw.githubusercontent.com/devleaks/xpfdr/refs/heads/main/fdr_viewer/media/fdr_viewer.png)

Map is presented by [Leaflet](https://leafletjs.com). Charts are presented by [ChartJS](https://www.chartjs.org).
All code by Pierre, a HI. Hence bugs.


## Troubleshooting

FDR logs a few messages in X-Plane `log.txt` file, especially reports it is working
and logging events.

The script will not work on X-Plane release 11 as it depends on newer XPPython3 features.


# See Also

  - `<X-Plane 12 Folder>/Instruction/FDR Example Version 3.fdr`
  - `<X-Plane 12 Folder>/Instruction/FDR Example Version 4.fdr`

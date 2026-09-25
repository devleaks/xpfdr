# Flight Data Recorder - ToLiss Airbus Specifics


The flight data recorder contains special features for Airbus-type airliners.
FDR attempt to guess the flight phase according to Airbus' definition.


# Recording Start / Stop

The CVR and (D)FDR are energized automatically during the following conditions:
  - On the ground for five minutes following electrical power.
  - On the ground continuously with at least one engine running.
  - Continuously in flight regardless if engines are operating.
  - The CVR and DFDR both automatically stop five minutes after the last engine is shut down.

# Flight Phase

![Airbus Flight Phases](https://raw.githubusercontent.com/devleaks/xpfdr/refs/heads/main/fdr_viewer/media/airbus-flight-phases.png)



## Collection Dynamic Adjustments

The main purpose of determinating the flight phase is _dynamic collection rate_ adjustment.

Depending on the flight phase, data is collected more or less quickly.
In particular, during the following two moments:

  - between reaching 80kt on takeoff roll until 1500ft is reached
  - between descending below 800ft and 80kt is reached on landing roll

During the cruise, data collection rate can be reduced.

Collection rate has no influence of NavAid recording or Command execution detection.


## Requirements

The following dataref need to be collected:

    - sim/cockpit2/switches/avionics_power_on
    - AirbusFBW/EngineThrust_N[0:2]
    - AirbusFBW/ECAMFlightPhase

Note: On A340, it might be necessary to collect `AirbusFBW/EngineThrust_N[0:4]`.


# Datarefs Of Interest

TBD


## Dataref with Value

TBD


## Commands

TBD

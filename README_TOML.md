# TOML Formatted Preference File

As a workaround if the python yaml package fails to install,
it is possible to enter preferences in a TOML formatted file.

In both case, file name must remain the same `fdr.prf`.

## YAML Formatted Preference File

```yaml
description: Sample test preference file
frequency: 1
report_frequency: 200
fdr_info:
  # REQUIRED FOR FLIGHT PHASE
  - name: elec_pwr
    dataref: sim/cockpit2/switches/avionics_power_on
fdr_data:
  - name: true_air_speed
    dataref: sim/flightmodel/position/true_airspeed
    unit: m/s
  - name: vspeed
    dataref: sim/cockpit2/gauges/indicators/vvi_fpm_pilot
    unit: ft/min
    callback: "lambda x: x * 1.0"
  - name: tracking
    dataref: sim/cockpit2/gauges/indicators/ground_track_true_pilot
    unit: T
commands:
    - AirbusFBW/CaptCautPush
    - AirbusFBW/CopilotCautPush
    - AirbusFBW/CaptWarnPush
    - AirbusFBW/CopilotWarnPush
    - sim/map/show_current
```

## TOML Formatted (same) Preference File

```toml
description = "Sample test preference file"
frequency = 1
report_frequency = 200
commands = [
  "AirbusFBW/CaptCautPush",
  "AirbusFBW/CopilotCautPush",
  "AirbusFBW/CaptWarnPush",
  "AirbusFBW/CopilotWarnPush",
  "sim/map/show_current"
]

[[fdr_info]]
name = "elec_pwr"
dataref = "sim/cockpit2/switches/avionics_power_on"

[[fdr_data]]
name = "true_air_speed"
dataref = "sim/flightmodel/position/true_airspeed"
unit = "m/s"

[[fdr_data]]
name = "vspeed"
dataref = "sim/cockpit2/gauges/indicators/vvi_fpm_pilot"
unit = "ft/min"
callback = "lambda x: x * 1.0"

[[fdr_data]]
name = "tracking"
dataref = "sim/cockpit2/gauges/indicators/ground_track_true_pilot"
unit = "T"
```


FDR first tries to parse the preference file with the TOML parser.
It it fails, preferences are parsed with the Yaml parser if it is avaialble.
It it still fails, no preference is added to FDR but it keeps
working with its default values.
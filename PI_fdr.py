"""X-Plane Flight Data Recorder

XPPython3 Plug In to create a FDR file during a flight.

See Also
    https://www.x-plane.com/kb/creating-fdr-files/
    <X-Plane 12 Folder>/Instructions/FDR Example Version 3.fdr
    <X-Plane 12 Folder>/Instructions/FDR Example Version 4.fdr

Fields permitted (in any order):
================

COMM: any comment

ACFT: the aircraft file to use, with full directory path from the X-Plane folder (ex: Aircraft/Heavy Metal/Boeing 747.acf).
TAIL: tail number of the aircraft (ex: N8141Q). Must come immediately after the ACFT line.
TIME: ZULU time of the beginning of the flight (ex: 18:54:32).
DATE: date of the flight (ex: 03/05/02).
PRES: sea-level pressure during the flight in inches HG (ex: 29.92).
TEMP: sea-level temperatre during the flight in degrees farenheit (ex: 65).
WIND: wind during th flight in degrees then knots (ex: 230,17).
CALI: the actual takeoff or touchdown logitude, latitude, and elevation in feet for calibration to X-Plane scenery. (ex: -118.34, 34.57, 456).

WARN: time to play a warning sound file, with full directory path from X-Plane itself to the .wav file (ex: 10,Resources/sounds/alert/1000ft.WAV).
TEXT: time & text to be read aloud by computer speech synthesis software (10,Copilot left the cockpit here).
MARK: time at which a text marker will appear in the time slider (ex: 15,Approach began here).
EVNT: highlights the flight path at the specified time, for a specified duration (ex: 10.5).

DATA: comma-delimited floating-point numbers that make up the bulk of the .fdr data (see explanation table below)

Keyworkd DATA is optional in FDR Version 4.

Example:

ACFT, Aircraft/Laminar Research/Lancair Evolution/N844X.acf
TAIL, N844X
DATE, 01/18/2023
PRES, 30.01
DISA, 0
WIND, 270,15

COMM utc time, lat, lon, alt...
12:34:56.789, 2, 3, 4

*By convention*, *penultimate* comment before data contains the header column name (FDRData.name)
(Last comment before contains start of log information.)

CHANGELOG

1.0.0 07-SEP-2026 Initial reelase
1.1.0 07-SEP-2026 Adjusted callbacks expression to use RPN rather than python eval of lambda expression (too dangerous for production release)
1.2.0 08-SEP-2026 Added python slice() dataref array range parsing like [:-6] and index list like [1,3,5]
1.2.1 08-SEP-2026 Added option to change auto stop timeout (default to 10 minutes)
1.3.0 08-SEP-2026 Added Airbus ECAM flight phase detection on ToLiss Airbus aircrafts.
1.4.0 14-SEP-2026 Added navaid log
1.5.0 15-SEP-2026 Register command executions
1.5.1 15-SEP-2026 Display command execution on map
1.5.2 15-SEP-2026 Added ground speed and altitude AGL to defaults
1.5.3 15-SEP-2026 Maintenance release, code cleanup
1.6.0 20-SEP-2026 First distribuable release with viewer
1.6.1 21-SEP-2026 Drop support to generate older file, generate A or I

"""

import os
import re
import math
# import tomllib
from enum import IntEnum
from dataclasses import dataclass
from functools import reduce
from datetime import datetime, timedelta, timezone
from traceback import print_exc
from typing import Callable, Any, List

XP_MESSAGE_OF_INTEREST = []
try:
    import xp
    from XPPython3.utils import xp_pip
    from XPPython3.utils.datarefs import find_dataref

    XP_MESSAGE_OF_INTEREST = [xp.MSG_AIRPORT_LOADED, xp.MSG_SCENERY_LOADED]

except ModuleNotFoundError:
    print("not using X-Plane")


# Will try to remove Yaml and favor TOML later
#
yaml = False
missing_modules = []
try:
    import ruamel
    from ruamel.yaml import YAML

    ruamel.yaml.representer.RoundTripRepresenter.ignore_aliases = lambda x, y: True
    yaml = YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
except ModuleNotFoundError:
    missing_modules.append("ruamel.yaml")


# Changelog

# Constants, default values
#
PLUGIN_ROOT_PATH = os.path.dirname(os.path.abspath(__file__))  # .../PythonPlugins
SCRIPT_NAME = os.path.basename(__file__)

# Script meta
NAME = "FDR"
VERSION = "1.6.0"
DESCRIPTION = "Flight Data Recordder"

# Script UI
FDR_MENU = "Start or stop FDR"
FDR_RESET_COMMAND = "xppython3/fdr/start_stop_toggle"
FDR_RESET_COMMAND_DESC = "Start or stop a new FDR session"
FDR_PLUGIN_SIGNATURE = "com.xppython3.fdr"

# Default values
FDR_PREFERENCE_FILE = "fdr.prf"
FDR_VERSION = 4  # 3 or 4
FDR_ARCH = "APPLE"  # "APPLE" or "IBM"

SHOW_TRACE = True
WRITE_FREQUENCY = 10.0  # seconds
REPORT_FREQUENCY = 100  # number of writes before logging
AUTOSTART = True
AUTOSTART_FREQUENCY = 10.0  # secs
AUTOSTART_THRESHOLD = 2.0  # m/s
AUTOSTOP_THRESHOLD = 600.0  # seconds
AIRBUSPHASE = False
WRITE_ASAP = True

LINREG_LEN = 10  # number of points in linear regression
DREF_SUB = "${x}"

# Thresholds
MIN_SPEED = 1.0  # m/s, below that speed is stopped
MIN_LIFTOFF_ABGL = 10.0  # m  > means in air, ABGL is CG of aircraft, != 0 when on ground.
MAX_LANDING_ABGL = 30.0  # m  < means on the ground (almost)


# Helpers and data class container
#
class RPC:
    # Simple implementation of a reverse polish calculator in Python.
    # Stolen here: https://github.com/scriptprinter/reverse-polish-calculator
    # Stack elements should be float

    def __init__(self, expression):
        self.tokens = []

        if type(expression) is not str:
            expression = str(expression)

        for part in expression.split(" "):
            try:
                self.tokens.append(float(part))
            except:
                self.tokens.append(part)

    def calculate(self, return_stack=False):
        stack = []

        for token in self.tokens:
            if isinstance(token, float):
                stack.append(token)
            elif token == "+":
                stack.append(stack.pop() + stack.pop())
            elif token == "-":
                number2 = stack.pop()
                stack.append(stack.pop() - number2)
            elif token == "*":
                stack.append(stack.pop() * stack.pop())
            elif token == "/":
                number2 = stack.pop()
                stack.append(stack.pop() / number2)
            elif token == "%" or token == "mod":
                number2 = stack.pop()
                stack.append(stack.pop() % number2)
            elif token == "floor":
                stack.append(math.floor(stack.pop()))
            elif token == "ceil":
                stack.append(math.ceil(stack.pop()))
            elif token == "round":  # round to integer
                stack.append(round(stack.pop(), 0))
            elif token == "roundn":  # round to integer
                number2 = stack.pop()
                stack.append(round(stack.pop(), int(number2)))
            elif token == "abs":  # absolute value
                stack.append(abs(stack.pop()))
            elif token == "chs":  # change sign
                stack.append(-1.0 * stack.pop())
            elif token == "eq":  # test for equality, pushes 1 if equal, 0 otherwise
                stack.append(1.0 if (stack.pop() == stack.pop()) else 0.0)
            elif token == "lt":  # test for <, pushes 1 if <, 0 otherwise
                stack.append(1.0 if (stack.pop() < stack.pop()) else 0.0)
            elif token == "gt":  # test for >, pushes 1 if >, 0 otherwise
                stack.append(1.0 if (stack.pop() > stack.pop()) else 0.0)
            elif token == "not":  # test for equality, pushes 1 if equal, 0 otherwise
                stack.append(0 if stack.pop() != 0 else 1)
            elif token == "inf":  # inf is used as a keyword to return a special value
                stack.append(math.inf)
            elif token == "cos":  # calculate cosine, input expected in degrees
                angle_in_degrees = stack.pop()
                angle_in_radians = math.radians(angle_in_degrees)
                stack.append(math.cos(angle_in_radians))
            elif token == "sin":  # calculate sine, input expected in degrees
                angle_in_degrees = stack.pop()
                angle_in_radians = math.radians(angle_in_degrees)
                stack.append(math.sin(angle_in_radians))
            else:
                print(f"RPC: invalid token {token}")

        return stack if return_stack else stack.pop()


class OOOI(IntEnum):
    OUT = 0
    OFF = 1
    ON = 2
    IN = 3


class FLIGHT(IntEnum):
    UNKNOWN = 0
    ON_BLOCK = 1  # assuming parked at gate, jetway, parking, etc.
    STOPPED = 2  # and not on blocks, ex. stoppped on taxiway, holding position...
    MOVING_ON_GROUND = 3
    IN_AIR = 4


@dataclass
class FDRData:
    name: str  # tail number
    dataref: str  # sim/aircraft/view/acf_tailnum
    pyslice: slice | None = None
    _indices: list | None = None
    callback: str | None = None
    unit: str | None = None
    force_datatype: str | None = None
    factor: float = 1.0
    chart: str | None = None  # hint to group data in same chart
    dref = None

    @classmethod
    def new(cls, dataref: str):
        name = dataref[dataref.rindex("/") + 1 :]
        return cls(name=name, dataref=dataref)

    def init(self) -> bool:
        # One day, we may accept values like "sim/dataref_array[1,5,7,9]"
        setattr(self, "_dataref_src", self.dataref)  # keep a copy of original request
        whole_dref = self.dataref
        try:
            has_slice = re.match(r"(?P<path>[^\[]+)\[(?P<s>[-\d]*)(:(?P<e>[-\d]*)?(:(?P<i>[-\d]*))?)+\]", self.dataref)  # python slice syntax
            # print(f"{NAME} {VERSION}::FDRData.init: parsing: {whole_dref} {has_slice}")
            if has_slice:
                whole_dref = has_slice.group("path")
                s0 = None if not has_slice.group("s") or has_slice.group("s") == "" else int(has_slice.group("s"))
                e0 = None if not has_slice.group("e") or has_slice.group("e") == "" else int(has_slice.group("e"))
                i0 = None if not has_slice.group("i") or has_slice.group("i") == "" else int(has_slice.group("i"))
                self.pyslice = slice(s0, e0, i0)
                # print(f"{NAME} {VERSION}::FDRData.init: array slice currently experimental: {self.name} {self.dataref}")
                self.dref = find_dataref(whole_dref)
                self.dataref = whole_dref
                # print(f"{NAME} {VERSION}::FDRData.init: {whole_dref}: len={self.length}, {self.pyslice} -> {self.indices})")
                print(f"{NAME} {VERSION}::FDRData.init: registered {whole_dref}[{self.indices}]) *** EXPERIMENTAL/SLICE")
                # self.info()
                return True
            if "[" in whole_dref:
                s = whole_dref[whole_dref.index("[") + 1 : whole_dref.index("]")]
                if "," in s:
                    self._indices = {int(i) for i in s.replace(" ", "").split(",")}
                    whole_dref = whole_dref[: whole_dref.index("[")]
                    # print(f"{NAME} {VERSION}::FDRData.init: array indices currently experimental: {self.name} {self.dataref}")
                    self.dref = find_dataref(whole_dref)
                    # print(f"{NAME} {VERSION}::FDRData.init: {whole_dref}: len={self.length}, '{s}' -> {self._indices}")
                    self.dataref = whole_dref
                    # self.info()
                    return True
                # else:
                #     print(f"{NAME} {VERSION}::FDRData.init: unique index: {whole_dref}")
            self.dref = find_dataref(whole_dref)
            # self.info()
            return self.dref is not None
        except Exception as e:
            print(f"{NAME} {VERSION}::FDRData.init: {whole_dref} init failed: {e}")
            print_exc()
        return False

    def info(self):
        if self.dref is None:
            print(f"{NAME} {VERSION}::FDRData.info: {self.dataref} no dref")
            return 0
        info = self.dataref
        if "[" in info:
            info = info[: info.index("[")]
        if self.is_array:
            l = self.dataref_array_length
            if l is not None:
                info += f"[{l}]"
        if len(self.dref.types) > 1:
            print(f"{NAME} {VERSION}::FDRData.info: WARNING: more than one type")
            info += f"::{','.join(self.dref.types)}"
        else:
            info += f"::{self.dref.types[0].replace('_array', '').replace('data', 'byte')}"
        print(f"{NAME} {VERSION}::FDRData.info: {info}")

    def fetched(self):
        if self.dref is None:
            print(f"{NAME} {VERSION}::FDRData.info: {self.dataref} no dref")
            return 0
        if self.value_length > 1:
            print(f"{NAME} {VERSION}::FDRData.fetched: {self.dataref}[{self.indices}]")
        else:
            print(f"{NAME} {VERSION}::FDRData.fetched: {self.dataref}")

    def fun(self) -> str | None:
        cheat = self._indices
        if self.value_length > 1:
            self._indices = self.indices
        s = repr(self)
        self._indices = cheat
        return s

    @property
    def is_array(self) -> bool:
        if self.dref is None:
            print(f"{NAME} {VERSION}::FDRData.is_array: {self.dataref} no dref")
            return False
        return "float_array" in self.dref.types or "int_array" in self.dref.types or "data" in self.dref.types

    @property
    def dataref_array_length(self) -> int:
        # return *dataref length* if it is an array (int or float)
        LENGTH = "_dataref_array_length"
        if self.dref is None:
            print(f"{NAME} {VERSION}::FDRData.dataref_array_length: {self.dataref} no dref")
            return 0
        if hasattr(self, LENGTH):  # cached
            return getattr(self, LENGTH)
        v = self.dref.value
        if "data" in self.dref.types:
            v = self.dref.bytes
        if v is None:
            return 0
        if isinstance(v, (list, tuple, dict, bytes)):
            l = len(v)
            setattr(self, LENGTH, l)
            return l
        setattr(self, LENGTH, 1)
        return 1

    @property
    def writable(self) -> bool:
        if self.dref is None:
            print(f"{NAME} {VERSION}::FDRData.writable: {self.dataref} no dref")
            return False
        return xp.canWriteDataRef(self.dref)

    @property
    def value_length(self) -> int:
        # return this FDRData value length, 1 for scalar, 0 if None
        if self.dref is None:
            print(f"{NAME} {VERSION}::FDRData.value_length: {self.dataref} no dref")
            return 0
        v = self.value
        if v is None:
            return 0
        if isinstance(v, (list, tuple, dict)):
            return len(v)
        return 1

    @property
    def indices(self) -> list:
        if self.dref is None:
            print(f"{NAME} {VERSION}::FDRData.indices: {self.dataref} no dref")
            return []
        # selected indices
        if self._indices is not None:
            return self._indices
        l = self.dataref_array_length
        # if only one index requested
        if l < 2:
            return {0}
        # slice()
        if self.pyslice is None:
            return list(range(l))  # all indices
        return list(range(l))[self.pyslice]

    def applyCallback(self, value: float | int) -> float | int:
        v = value
        if value is not None and self.callback is not None:  # if array, should use callback on each value?
            expr = self.callback.replace(DREF_SUB, str(value))
            rpc = RPC(expr)
            v = rpc.calculate()
            # print(f"{NAME} {VERSION}::FDRData.value: RPC {self.name}: {self.callback} => {expr} => {v}")
        return v

    @property
    def value(self) -> int | float | str | list | None:
        if self.dref is None:
            print(f"{NAME} {VERSION}::FDRData.value: {self.name} {self.dataref} no dref")
            try:  # try to re-init it
                self.init()
                if self.dref is not None:
                    print(f"{NAME} {VERSION}::FDRData.value: {self.name} {self.dataref} inited with delay")
                else:
                    return None
            except Exception as e:
                print(f"{NAME} {VERSION}::FDRData.value: init {self.name} {self.dataref} exception: {e}")
            return None
        v = None
        try:
            v = self.dref.value
            if self.is_array:
                if "[0]" in self.dataref:  # bug XPPython3, returns while array for a[0] instead of scalar value
                    print(f"{NAME} {VERSION}::FDRData.value: workaround for index 0 of array ({self.dataref}={v[0]} (xppython3={xp.VERSION})")
                    v = v[0]
                elif isinstance(v, (list, tuple)):
                    if self._indices is not None:
                        return [self.applyCallback(v[i]) for i in self._indices]
                    if self.pyslice is not None:
                        return [self.applyCallback(i) for i in v[self.pyslice]]
                    return v
            v = self.applyCallback(v)
        except Exception as e:
            print(f"{NAME} {VERSION}::FDRData.value: callback {self.name} {self.dataref} exception: {e}")
            v = None
        return v


class NAVAID_TYPE(IntEnum):
    Nav_Unknown = 0
    Nav_Airport = 1
    Nav_NDB = 2
    Nav_VOR = 4
    Nav_ILS = 8
    Nav_Localizer = 16
    Nav_GlideSlope = 32
    Nav_OuterMarker = 64
    Nav_MiddleMarker = 128
    Nav_InnerMarker = 256
    Nav_Fix = 512
    Nav_DME = 1024
    Nav_LatLon = 2048
    Nav_TACAN = 4096


@dataclass
class NavAid:
    name: str
    lat: float
    lon: float
    navType: NAVAID_TYPE
    navAidId: str
    height: float = 0.0
    heading: float = 0.0
    frequency: int = 0  # / 100
    reg: bool = False


@dataclass
class Command:
    name: str
    when: str
    index: int
    phase: int
    before: int


# Collected once for session, displayed in FDR report header
HEADER = [
    FDRData(name="ACFT", dataref="sim/aircraft/view/acf_relative_path"),
    FDRData(name="TAIL", dataref="sim/aircraft/view/acf_tailnum"),
    FDRData(name="ICAO", dataref="sim/aircraft/view/acf_ICAO"),
    FDRData(name="AUTH", dataref="sim/aircraft/view/acf_author"),
    FDRData(name="DMON", dataref="sim/cockpit2/clock_timer/current_month"),
    FDRData(name="DDAY", dataref="sim/cockpit2/clock_timer/current_day"),
    FDRData(name="SEAL", dataref="sim/weather/region/sealevel_pressure_pas", callback=f"{DREF_SUB} 0.00029529980164712 *"),  # 1 pascal = 0.00029529980164712 in hg
    FDRData(name="WSPD", dataref="sim/weather/aircraft/wind_now_speed_msc", callback=f"{DREF_SUB} 1.94384449 *"),  # 1 m/s = 1,94384449 kt, FDR expects kt
    FDRData(name="WDIR", dataref="sim/weather/aircraft/wind_now_direction_degt"),
    FDRData(name="DISA", dataref="sim/weather/region/temperatures_aloft_deg_c[0]"),  # not sure where to fetch temperature offset from ISA
    FDRData(name="REPL", dataref="sim/operation/prefs/replay_mode"),  # no FDR onreplays (sim/time/is_in_replay)
    FDRData(name="ZDAY", dataref="sim/time/zulu_date_days"),  # used to get simulator time
    FDRData(name="ZSEC", dataref="sim/time/zulu_time_sec"),  # used to get simulator date (assume current year)
    FDRData(name="CHOK", dataref="sim/flightmodel2/gear/is_chocked"),  # used for formal OOOI
]
# Through preferences, user can define a set of fdr_info datarefs to complement header information

# "Mandatory" FDR data at start of each CSV line
# They MUST BE the ZULU time, then the longitude, latitude, altitude in feet, magnetic heading in degrees, then pitch and roll in degrees.
FDR_DATA = [
    FDRData(name="longitude", dataref="sim/flightmodel/position/longitude"),
    FDRData(name="latitude", dataref="sim/flightmodel/position/latitude"),
    FDRData(name="altitude", dataref="sim/flightmodel/position/elevation", callback=f"{DREF_SUB} 3.28084 *", unit="ft"),  # m to ft, FDR expects ft
    FDRData(name="heading", dataref="sim/cockpit2/gauges/indicators/heading_electric_deg_mag_pilot"),
    FDRData(name="pitch", dataref="sim/cockpit2/gauges/indicators/pitch_electric_deg_pilot", chart="Attitude"),
    FDRData(name="roll", dataref="sim/cockpit2/gauges/indicators/roll_electric_deg_pilot", chart="Attitude"),
    FDRData(name="gs", dataref="sim/flightmodel2/position/groundspeed", unit="m/s"),
    FDRData(name="agl", dataref="sim/flightmodel2/position/y_agl"),
]
# Through preferences, user can define a set of fdr_data datarefs.

# One day, they be part of preferences
NAVAID_FREQUENCIES = [
    FDRData.new(dataref="sim/cockpit/radios/adf1_freq_hz"),
    FDRData.new(dataref="sim/cockpit/radios/adf2_freq_hz"),
    FDRData.new(dataref="sim/cockpit/radios/dme_freq_hz"),
    FDRData.new(dataref="sim/cockpit/radios/nav1_freq_hz"),
    FDRData.new(dataref="sim/cockpit/radios/nav2_freq_hz"),
]


# #############################################################################
#
# A I R B U S   F L I G H T   P H A S E
#
# Airbus Flight Phase specific thresholds
# S.I., for A321, may need adjustment on acf model, engines, etc. We'll see later
#
# Why Airbus flight phase?
# Logging can record numerous data often.
# For simulation, a way to tune this is to adjust collection frequency with the flight phase:
# Faster collection on takeoff, approach, landing, slower collection on cruise, when stopped...
#

S80KT = 80 * 0.5144444  # m/s
FAST = 500  # 1 Mach = 340.29m/s, sea level
A1500FT = 1500 * 0.3048  # m
A800FT = 800 * 0.3048  # m
MIN_ABGL = 10.0  # m, must take into account aircraft CG elev ABGL, make higher for A380
ENG_PWR = 1500  # Thrust in N to assume engine to power
ENG_OFF = 10  # Thrust in N, minimal to assume engine started
FIVEMIN = 300.0  # secs


class AIRBUS_PHASE(IntEnum):
    OFF = 0  # cold and dark
    ELECPOWER = 1  # Coffie machine available
    FIRSTENGSTARTED = 2  # Expresso, capuccino possible
    FIRSTENGTOPOWER = 3
    ACCEL80KT = 4   # super-frequent for take off
    LIFTOFF = 5
    ABOVE1500FT = 6  # reduce progressively for cruise
    BELOW800FT = 7  # super-frequent for approach
    TOUCHDOWN = 8
    DECEL80KT = 9   # reduce progressively for taxi, parking...
    SECONDENGSHUTDOWN = 10
    FIVEMINAFTER = 11


@dataclass
class FlightPhase:
    phase: AIRBUS_PHASE
    when: datetime


class AirbusFlightPhase:
    """Airbus ECAM Flight Phase detection
    For this optional class to work, the following datarefs are necessary (examples fdr.prf file):

        frequency: 1
        report_frequency: 100
        chocks: AirbusFBW/Chocks
        fdr_data:
          - name: ground_speed
            dataref: sim/flightmodel/position/groundspeed
            unit: m/s
          - name: ecam_flight_phase
            dataref: AirbusFBW/ECAMFlightPhase
          - name: elec_pwr
            dataref: sim/cockpit2/switches/avionics_power_on
          - name: eng_pwr
            dataref: AirbusFBW/EngineThrust_N
    """

    def __init__(self, dt: datetime, datarefs: dict, alt_reg: Callable, spd_reg: Callable, airtime: Callable) -> None:
        self.AIRBUS_PROCESS = {
            AIRBUS_PHASE.OFF: self.test_elecpwr,
            AIRBUS_PHASE.ELECPOWER: self.test_engon,
            AIRBUS_PHASE.FIRSTENGSTARTED: self.test_engpwr,
            AIRBUS_PHASE.FIRSTENGTOPOWER: self.test_accel80kt,
            AIRBUS_PHASE.ACCEL80KT: self.test_liftoff,
            AIRBUS_PHASE.LIFTOFF: self.test_alt1500ft,
            AIRBUS_PHASE.ABOVE1500FT: self.test_alt800ft,
            AIRBUS_PHASE.BELOW800FT: self.test_touchdown,
            AIRBUS_PHASE.TOUCHDOWN: self.test_decel80kt,
            AIRBUS_PHASE.DECEL80KT: self.test_shutdown,
            AIRBUS_PHASE.SECONDENGSHUTDOWN: self.test_after,
            AIRBUS_PHASE.FIVEMINAFTER: self.test_off,
        }
        self._e = -1
        self.datarefs = datarefs
        self.alt_reg = alt_reg
        self.spd_reg = spd_reg
        self.had_air_time = airtime
        self._sequence = []
        self._inited = False
        self._initial_phase = None
        self.current = FlightPhase(phase=AIRBUS_PHASE.OFF, when=dt)

        if not self.valid:
            self.debug("invalid, may be some dataref missing?", force=True)
        else:
            self.debug("valid", force=True)
            self._sequence.append(self.current)
            self.current = self.flight_phase(dt=dt)

    @property
    def valid(self) -> bool:
        needed = [
            "AirbusFBW/ECAMFlightPhase",  # ecam_flight_phase, not formally required, but used to test ToLiss
            "AirbusFBW/EngineThrust_N",  # eng_pwr
            "sim/cockpit2/switches/avionics_power_on",  # elec_pwr
            "sim/flightmodel/position/groundspeed",  # ground_speed
            "sim/flightmodel2/position/y_agl",  # ABGL
        ]
        valid_list = [k.dataref for k in self.datarefs.values()]
        test = [d for d in needed if d not in valid_list]
        if len(test) > 0:
            self.debug(f"missing dataref {test}, invalid", force=True)
            self.debug(f"{valid_list}", force=True)
            return False
        return True

    def speed_regression_reliable(self) -> bool:
        r, e, cnt, diff = self.speed_lr()
        return cnt > 4

    def altitude_regression_reliable(self) -> bool:
        r, e, cnt, diff = self.vertical_lr()
        return cnt > 4

    def debug(self, message, force: bool = False):
        # ideal message is function_name: message
        if SHOW_TRACE or force:
            print(f"{NAME} {VERSION}::AirbusFlightPhase:{message}")

    def flight_phase(self, dt: datetime) -> FlightPhase:
        def set_inited(message) -> FlightPhase:
            self._initial_phase = self.current
            self._inited = True
            self.debug(f"flight_phase/init: {message}")
            self.debug(f"flight_phase: initialized to {self.current.phase.name}", force=True)
            return self.current

        def next_phase():
            new_phase = FlightPhase(phase=AIRBUS_PHASE((self.current.phase.value + 1) % 12), when=dt)
            msg = "" if self._inited else "flight_phase/init: "
            self.debug(f"{msg}{self.current.phase.name} > {new_phase.phase.name} at {dt.replace(microsecond=0)}", force=True)
            self._sequence.append(new_phase)
            self.current = new_phase

        def set_phase(phase: AIRBUS_PHASE, message) -> FlightPhase:
            new_phase = FlightPhase(phase=phase, when=dt)
            self.debug(f"flight_phase/init: SET > {new_phase.phase.name} at {dt.replace(microsecond=0)}", force=True)
            self._sequence.append(new_phase)
            self.current = new_phase
            return set_inited(message)

        if not self.valid:
            self.debug("flight_phase: not valid", force=True)
            return self.current

        # This is a test to see if ToLiss datarefs are available with reliable values
        # Fails during initialization of aircraft.
        ecam = self.ecam_flight_phase
        if ecam == -1:
            self.debug("flight_phase: not ready")
            return self.current

        change_phase = self.AIRBUS_PROCESS[self.current.phase]
        # self.debug(f"flight_phase: {self.current.phase.name}, test is {test}")
        if change_phase():
            next_phase()
            return self.flight_phase(dt=dt)

        # ####################@
        # Lot of work to determine situation and deduce flight phase on start.
        # Easy situation (at gate, ramp, cold start, etc.) are easy.
        # In flight starts are more difficult. Not 100% reliable.
        #
        if not self._inited:  # need to check more... note: WE have no statistical regression value
            self.debug(f"flight_phase/init:: not inited, current={self.current.phase.name}, air time={self.had_air_time()}, ecam={ecam}")
            if self.current.phase == AIRBUS_PHASE.FIRSTENGSTARTED and self.test_engpwr():
                next_phase()
                return self.flight_phase(dt=dt)
            if self.current.phase == AIRBUS_PHASE.FIRSTENGTOPOWER and self.get_value("gs", 0) > S80KT:
                next_phase()
                return self.flight_phase(dt=dt)
            if self.current.phase == AIRBUS_PHASE.FIRSTENGTOPOWER:
                ## GREY MATTER: Less than 80KT. Stopped?
                if self.get_value("gs", FAST) < MIN_SPEED:  # Engine on and stopped
                    # are we stopped before the flight or after the flight?
                    if self.had_air_time():
                        return set_phase(phase=AIRBUS_PHASE.DECEL80KT, message="stopped and had air time")  # wait for engine to stop
                    return set_inited("stopped, no air time")  #  wait for movement
                ## DARK GREY MATTER: Less than 80KT and not stopped: Accelerating or decelerating?
                if self.speed_regression_reliable:
                    if self.spd_reg()[0] > 0.0:  # taxiing or accelerating, we will eventually reach 80kt
                        return set_inited("not stopped, accelerating")
                    # Decelerating: taxiing or end of roll?
                    if self.had_air_time():  # we landed, we are aleady under 80kt
                        return set_phase(phase=AIRBUS_PHASE.DECEL80KT, message="not stopped, decelerating, had air time")
                # We cannot decide now, we are not _inited, wait for more speed stats
                self.debug("flight_phase/init:: speed regression unreliable")
                return self.current

            if self.current.phase == AIRBUS_PHASE.ACCEL80KT and self.get_value("agl", 0) > MIN_ABGL:
                next_phase()
                return self.flight_phase(dt=dt)

            if self.current.phase == AIRBUS_PHASE.ACCEL80KT and self.had_air_time():  # just landed
                return set_phase(phase=AIRBUS_PHASE.LANDING, message=f"had air time, below {MIN_ABGL}m, above 80kt")

            if self.current.phase == AIRBUS_PHASE.LIFTOFF and self.get_value("agl", 0) > A1500FT:
                next_phase()
                return set_inited("flying above 1500FT")  # we're above 1500ft, we cannot say much now

            if self.current.phase == AIRBUS_PHASE.LIFTOFF:
                ## GREY MATTER: Less than 1500FT, but in the air...
                if self.altitude_regression_reliable:
                    if self.alt_reg()[0] > 0:  # climbing, we will eventually reach >1500ft
                        return set_inited("lifted off, climbing")
                    # Descending
                    if self.get_value("agl", 0) > A800FT:  # we're between 1500 and 800ft, descending, we will eventually reach <800ft
                        return set_phase(phase=AIRBUS_PHASE.ABOVE1500FT, message="descending, between 800 and 1500ft")
                    # Just touching down
                    if self.get_value("agl", A1500FT) < MIN_ABGL:  # descending, we're below MAX_LANDING_ABGL, we'll touch down
                        return set_phase(phase=AIRBUS_PHASE.LANDING, message=f"descending, below {MIN_ABGL}")
                    if self.get_value("agl", A1500FT) < A800FT:  # we're between 800ft and MAX_LANDING_ABGL, descending, we already passed 800ft going down
                        return set_phase(phase=AIRBUS_PHASE.BELOW800FT, message=f"descending, between 800 and {MIN_ABGL}")
                self.debug("flight_phase/init:: altitude regression unreliable")
                return self.current

            if not self.test_engpwr() and self.had_air_time():
                return set_phase(phase=AIRBUS_PHASE.SECONDENGSHUTDOWN, message="no power, had air time, cooling down 5 min")  # wait for five minutes

            if self.current.phase == AIRBUS_PHASE.ABOVE1500FT and self.get_value("agl", A1500FT) < A800FT:
                next_phase()
                return self.flight_phase(dt=dt)
            if self.current.phase == AIRBUS_PHASE.BELOW800FT and self.get_value("agl", A1500FT) < MIN_ABGL:
                next_phase()
                return self.flight_phase(dt=dt)
            if self.current.phase == AIRBUS_PHASE.TOUCHDOWN and self.get_value("gs", FAST) < S80KT:
                next_phase()
                return self.flight_phase(dt=dt)
            if self.current.phase == AIRBUS_PHASE.DECEL80KT and self.test_shutdown():
                next_phase()
                return self.flight_phase(dt=dt)
            if self.current.phase == AIRBUS_PHASE.SECONDENGSHUTDOWN and self.test_off():
                next_phase()
                return self.flight_phase(dt=dt)
            set_inited("all conditions failed")
        #
        # ####################@

        return self.current

    def get_value(self, name: str, default: Any) -> int | float | list:
        d = self.datarefs.get(name)
        if d is None:
            self.debug(f"get_value: dataref {name} not found", force=True)
            return default
        return d.value

    @property
    def ecam_flight_phase(self) -> int:
        return self.get_value("ecam_flight_phase", -1)

    def test_elecpwr(self) -> bool:
        self.debug(f"test_elecpwr: {self.get_value('elec_pwr', 0)}")
        return self.get_value("elec_pwr", 0) == 1

    def test_engon(self) -> bool:
        engs = self.get_value("eng_pwr", [])
        if engs is None:
            return False
        self.debug(f"test_engon: {engs} #{self._e} > {ENG_OFF}")
        if len(engs) == 0:
            return False
        for i in range(len(engs)):
            e = engs[i]
            if e > ENG_OFF:
                if self._e == -1:  # remember which one starting
                    self._e = i
                    self.debug(f"test_engon: engine #{self._e} started")
                return True
        return False

    def test_engpwr(self) -> bool:
        engs = self.get_value("eng_pwr", [])
        if engs is None:
            return False
        self.debug(f"test_engpwr: {engs} #{self._e} > {ENG_PWR}")
        if len(engs) == 0:
            return False
        if self._e > -1 and self._e < len(engs):  # the one starting
            self.debug(f"test_engpwr: engine #{self._e} available")
            return engs[self._e] > ENG_PWR
        # else, test them all and ok if at least one at power
        for e in engs:
            if e > ENG_PWR:
                self.debug("test_engpwr: engine available")
                return True
        return False

    def test_accel80kt(self) -> bool:
        self.debug(f"test_accel80kt: {self.spd_reg()} {self.get_value('ground_speed', 0.0)} > {S80KT}")
        return self.spd_reg()[0] > 0 and self.get_value("gs", 0) > S80KT

    def test_liftoff(self) -> bool:
        self.debug(f"test_liftoff: {self.alt_reg()} {self.get_value('ABGL', 0.0)} > { 2* MIN_ABGL}")
        return self.alt_reg()[0] > 0 and self.get_value("agl", 0) > MIN_ABGL * 2

    def test_alt1500ft(self) -> bool:
        self.debug(f"test_alt1500ft: {self.alt_reg()} {self.get_value('ABGL', 0.0)} > {A1500FT}")
        return self.alt_reg()[0] > 0 and self.get_value("agl", 0) > A1500FT

    def test_alt800ft(self) -> bool:
        self.debug(f"test_alt800ft: {self.alt_reg()} {self.get_value('ABGL', A1500FT)} < {A800FT}")
        return self.alt_reg()[0] < 0 and self.get_value("agl", 0) < A800FT

    def test_touchdown(self) -> bool:
        self.debug(f"test_touchdown: {self.get_value('ABGL', A1500FT)} < {MIN_ABGL}")
        return self.get_value("agl", A1500FT) < MIN_ABGL

    def test_decel80kt(self) -> bool:
        self.debug(f"test_decel80kt: {self.spd_reg()} {self.get_value('ground_speed', 100.0)} < {S80KT}")
        return self.spd_reg()[0] < 0 and self.get_value("gs", FAST) < S80KT

    def test_shutdown(self) -> bool:
        engs = self.get_value("eng_pwr", [])
        self.debug(f"test_shutdown: {engs} < {ENG_OFF}")
        if len(engs) < 2:
            return False
        offs = [e < ENG_OFF for e in engs]
        if all(offs):
            self._e = -1
            return True
        return False

    def test_after(self) -> bool:
        how_long = (datetime.now(tz=timezone.utc) - self.current.when).total_seconds()
        self.debug(f"test_after: {self.current.phase.name} {how_long} > {FIVEMIN}")
        return self.current.phase == AIRBUS_PHASE.SECONDENGSHUTDOWN and how_long > FIVEMIN

    def test_off(self) -> bool:
        self.debug(f"test_off: {self.get_value('elec_pwr', 1)}")
        return self.get_value("elec_pwr", 1) == 0

    def save(self, file):
        # On file close, Writes encountered navaids to FDR as comments
        for ph in self._sequence:
            s = "* " if ph == self._initial_phase else ""
            print(f"COMM, Airbus flight phase {ph.phase.name} {s}{ph.when.isoformat()}", file=file)

#
#
# #############################################################################


class PythonInterface:

    def __init__(self) -> None:
        self.Name = NAME
        self.Sig = PLUGIN_ROOT_PATH.strip("/").replace("/", ".")
        self.Desc = DESCRIPTION + " (Rel. " + VERSION + ")"
        self.Info = self.Name + f" {VERSION}"

        self._enabled = False

        self.fdrCmdRef = None
        self.menuIdx = None

        self.recorderFL = None
        self.refRecorder = "FDR:record"

        self.supervisorFL = None
        self.refSupervisor = "FDR:supervisor"

        self.file = None
        self.prefs = {}

        self.header = {d.name: d for d in HEADER}  # collected once
        self.fdr_mand = {d.name: d for d in FDR_DATA}  # mandatory reported values

        self.custom_chocks = None

        # navaids
        self.navaid_freqs:List[FDRData] = NAVAID_FREQUENCIES
        self.navaids: Dict[str, NavAid] = {}
        self.navaid_counter = 0

        # commands
        self.commands = ["sim/map/show_current"]  # test
        self.commandRefs = {}
        self.commandRefCons = {}
        self.commandExecs = []

        # Working variables
        self._estimated_state = FLIGHT.UNKNOWN
        self._had_air_time: bool | None = None
        self.last_agl = 0
        self.chocks_removed = None
        self.oooi = {i: None for i in range(len(OOOI))}
        self.oooi_notes = {i: None for i in range(len(OOOI))}
        self.start_time = None
        self.last_stop = None
        self.writes = 0
        self.elevs: List[float] = []
        self.speeds: List[float] = []

        self._afp = None  # Experimental, ToLiss/Airbus specific
        self.err_cnt = 0
        self.err_rst = datetime.now().astimezone()
        self.err_lst = None

        # Can be changed in preferences
        self.last_acf = ""
        self.arch = FDR_ARCH
        self.frequency = WRITE_FREQUENCY
        self.report_frequency = REPORT_FREQUENCY
        self.fdr_info = {}
        self.fdr_data = {}
        self.navaid_freqs_optional:List[FDRData] = []

    @property
    def fdr_all_data_values(self) -> List[FDRData]:
        # all datarefs to collect at each iteration
        return list(self.fdr_mand.values()) + list(self.fdr_data.values())

    @property
    def all_navaid_freqs(self) -> List[FDRData]:
        # all datarefs to collect at each iteration
        return self.navaid_freqs + self.navaid_freqs_optional
    #
    # ERROR and MISBEHAVIOR
    #
    def error(self):
        self.err_cnt += 1
        self.err_lst = datetime.now().astimezone()

    def reset_error(self):
        self.err_cnt = 0
        self.err_rst = datetime.now().astimezone()

    def has_errors(self):
        return self.err_cnt > 0

    def has_many_errors(self):
        ERR_RATE = 1 / self.frequency  # 1 err / frequency seconds
        if not self.has_errors():
            return False
        t = (datetime.now().astimezone() - self.err_lst).total_seconds()
        return (self.err_cnt / t) >= ERR_RATE

    #
    # HELPERS
    #
    @property
    def chocked(self) -> bool:
        c = self.header.get("CHOK") if self.custom_chocks is None else self.custom_chocks
        v = None
        try:
            v = c.value
        except Exception as e:
            self.debug(f"chocked: exception: {e}", force=True)
        if v is None:
            return False
        return v != 0 if not (isinstance(v, (list, tuple))) else any(t != 0 for t in v)

    def had_air_time(self) -> bool:
        return self._had_air_time

    def how_long_stopped(self) -> float:
        # returns total seconds since first stop noticed
        if self.estimated_state not in [FLIGHT.ON_BLOCK, FLIGHT.STOPPED]:
            return 0.0
        if self.last_stop is None:
            self.last_stop = self.system_now_datetime
            self.debug("how_long_stopped: stopped")
        return round((self.system_now_datetime - self.last_stop).total_seconds(), 0)

    @property
    def flight_status(self) -> FLIGHT:
        # Are we moving? Are we in the air?
        # Are we moving?
        try:
            # ################################################
            #
            if self._afp is not None:
                dummy = self._afp.flight_phase(dt=self.simulator_zulu_datetime)
            #
            # ################################################

            gndsp = self.fdr_mand.get("gs").value
            if gndsp is None:  # we don't know...
                self.debug("flight_status: no movement info")
                return FLIGHT.UNKNOWN
            self.add_speed(self.system_now_datetime, gndsp)
            if gndsp < AUTOSTART_THRESHOLD:
                if self.chocked:
                    self.debug("flight_status: on chocks")
                    return FLIGHT.ON_BLOCK
                else:
                    if self.last_stop is None:
                        self.last_stop = self.system_now_datetime
                        self.debug("flight_status: stopped")
                    return FLIGHT.STOPPED
            # Yes we are moving...
            if self.last_stop is not None:
                self.debug("flight_status: started moving")
                self.last_stop = None
            # Are we in the air?
            elev = self.fdr_mand.get("agl").value
            if elev is None or elev < MIN_LIFTOFF_ABGL:
                return FLIGHT.MOVING_ON_GROUND
            # Yes we are in the air...
            if not self.had_air_time():
                self._had_air_time = True
                self.debug("flight_status: air time")

            # Additional: Are we taking of or landing?
            # @todo: possible dynamic adjustment of FDR frequency:
            #        less in cruise, more close to the ground
            self.add_elev(self.system_now_datetime, elev)
            r, e, cnt, diff = self.vertical_lr()
            t = self.elevs[-1][0] - self.elevs[0][0]
            # self.debug(f"flight_status: vertical regression: {round(r, 2)} m/s ({round(r*196.85039, 0)} ft/m) (delta t={round(t, 2)} secs, {LINREG_LEN} pts), err={round(e, 2)}")
            if elev < MAX_LANDING_ABGL and r < 0.0:
                self.calibration(takeoff=False)
                self.debug("flight_status: landing")
                # self.frequency = 1.0
            elif self.estimated_state == FLIGHT.MOVING_ON_GROUND and elev > MIN_LIFTOFF_ABGL and r > 0.0:
                self.calibration(takeoff=True)
                self.debug("flight_status: takeoff")
                # self.frequency = 5.0
            self.last_agl = elev
            return FLIGHT.IN_AIR
        except Exception as e:
            self.debug(f"flight_status: exception {e}")
            print_exc()
            return FLIGHT.UNKNOWN

    @property
    def estimated_state(self) -> FLIGHT:
        return self._estimated_state

    @estimated_state.setter
    def estimated_state(self, new_state: FLIGHT):
        # OOOI logic
        def was(e: FLIGHT):
            return self.estimated_state == e

        if self._estimated_state == new_state:
            return

        zulu = self.simulator_zulu_datetime.replace(microsecond=0)  # .isoformat().replace('+00:00', 'Z')
        oooi_msg = None

        if was(FLIGHT.UNKNOWN) or new_state == FLIGHT.UNKNOWN:
            self.debug(f"estimated_state: {self._estimated_state.name} => {new_state.name} (at {zulu})")
            self._estimated_state = new_state
            return

        if new_state == FLIGHT.ON_BLOCK:
            if was(FLIGHT.UNKNOWN):
                self._estimated_state = new_state
            elif was(FLIGHT.STOPPED) or was(FLIGHT.MOVING_ON_GROUND):
                if self.had_air_time():
                    self.oooi[OOOI.IN] = zulu
                    oooi_msg = OOOI.IN
                else:
                    self.debug("estimated_state: back on block")
            else:
                self.debug("estimated_state: on block without being stopped")

        elif new_state == FLIGHT.STOPPED:
            if was(FLIGHT.ON_BLOCK):
                self.chocks_removed = zulu
                self.debug("estimated_state: removed chocks")
            elif was(FLIGHT.MOVING_ON_GROUND):
                if self.had_air_time():
                    self.debug("estimated_state: had air time, stopped, may be parked? tentative IN")
                    self.oooi[OOOI.IN] = zulu
                    oooi_msg = OOOI.IN
                    self.oooi_notes[OOOI.IN] = "not on blocks, may be stopped on taxiway or apron?"
                else:
                    self.debug("estimated_state: stopped")

        elif new_state == FLIGHT.MOVING_ON_GROUND:
            if was(FLIGHT.IN_AIR):  # landed
                self.oooi[OOOI.ON] = zulu
                oooi_msg = OOOI.ON
            elif was(FLIGHT.ON_BLOCK) or was(FLIGHT.STOPPED) and not self.had_air_time():
                if was(FLIGHT.ON_BLOCK):
                    self.chocks_removed = zulu
                if self.oooi[OOOI.OUT] is None:
                    self.oooi[OOOI.OUT] = zulu
                    oooi_msg = OOOI.OUT

        elif new_state == FLIGHT.IN_AIR:
            self._had_air_time = True
            if was(FLIGHT.MOVING_ON_GROUND):  # take-off
                self.oooi[OOOI.OFF] = zulu
                oooi_msg = OOOI.OFF
            else:
                self.debug("estimated_state: got in air without on ground movement?")

        self.debug(f"estimated_state: {self._estimated_state.name} => {new_state.name} (at {zulu})")
        if oooi_msg is not None:
            m = self.oooi_notes[oooi_msg]
            m = "" if m is None else f"({m})"
            self.debug(f"OOOI: {oooi_msg.name} at {zulu} {m}", force=True)
        self._estimated_state = new_state

    def calibration(self, takeoff: bool = True):
        movement = "TAKEOFF" if takeoff else "LANDING"
        try:
            lat = self.fdr_mand.get("latitude").value
            lon = self.fdr_mand.get("longitude").value
            alt = self.fdr_mand.get("agl").value
            self.debug(f"CALI lat={lat}, lon={lon}, alt={alt}", force=True)
            self.debug(f"COMM CALI {movement} PRECISION: recording frequency={self.frequency} secs.", force=True)
            self.debug(f"COMM CALI {movement} not written to FDR file", force=True)
        except Exception as e:
            self.debug(f"calibration: error: {e}", force=True)

    def add_elev(self, dt: datetime, alt: float):
        # Add (timestamp, elevation) to limited list for regression
        if type(alt) in [int, float]:
            self.elevs.append((dt.timestamp(), alt))
        if len(self.elevs) > LINREG_LEN:
            self.elevs = self.elevs[-10:]

    def vertical_lr(self) -> tuple:
        # Linear regression on last altitude checkpoints to monitor trend (descending/ascending)
        # Returns   a, error, number of points, last - oldest
        if len(self.elevs) < 3:
            diff = 0 if len(self.elevs) < 2 else self.elevs[-1][1] - self.elevs[0][1]
            return 0.0, 0.0, len(self.elevs), diff
        x = [a[0] for a in self.elevs]
        mx = sum(x) / len(x)
        y = [a[1] for a in self.elevs]
        my = sum(y) / len(y)
        nx2 = sum([(a[0] - mx) * (a[0] - mx) for a in self.elevs])
        ny2 = sum([(a[1] - my) * (a[1] - my) for a in self.elevs])
        nxy = sum([(a[0] - mx) * (a[1] - my) for a in self.elevs])
        r2 = ny2 / (len(self.elevs) - 2)
        r = math.sqrt(r2)
        return nxy / math.sqrt(nx2 * ny2) if nx2 != 0.0 and ny2 != 0.0 else 0.0, r, len(self.elevs), self.elevs[-1][1] - self.elevs[0][1]

    def add_speed(self, dt: datetime, speed: float):
        # Add (timestamp, elevation) to limited list for regression
        if type(speed) in [int, float]:
            self.speeds.append((dt.timestamp(), speed))
        if len(self.speeds) > LINREG_LEN:
            self.speeds = self.speeds[-10:]

    def speed_lr(self) -> tuple:
        # Linear regression on last speed checkpoints to monitor trend (accelerating/decelerating)
        if len(self.speeds) < 3:
            diff = 0 if len(self.speeds) < 2 else self.speeds[-1][1] - self.speeds[0][1]
            return 0.0, 0.0, len(self.speeds), diff
        x = [a[0] for a in self.speeds]
        mx = sum(x) / len(x)
        y = [a[1] for a in self.speeds]
        my = sum(y) / len(y)
        nx2 = sum([(a[0] - mx) * (a[0] - mx) for a in self.speeds])
        ny2 = sum([(a[1] - my) * (a[1] - my) for a in self.speeds])
        nxy = sum([(a[0] - mx) * (a[1] - my) for a in self.speeds])
        r2 = ny2 / (len(self.speeds) - 2)
        r = math.sqrt(r2)
        return nxy / math.sqrt(nx2 * ny2) if nx2 != 0.0 and ny2 != 0.0 else 0.0, r, len(self.speeds), self.speeds[-1][1] - self.speeds[0][1]

    @property
    def replay_mode(self) -> bool:
        # Are we in replay mode
        v = self.header.get("REPL").value
        return v is not None and v != 0

    @property
    def simulator_zulu_datetime(self) -> datetime:
        now = datetime.now(tz=timezone.utc)
        days = self.header.get("ZDAY").value
        secs = self.header.get("ZSEC").value
        if days is None or secs is None:  # fallback, as if X-Plane was using "system time"
            self.debug("simulator_zulu_datetime: could not get simulator time, returning system time", force=True)
            return self.system_now_datetime.replace(tzinfo=timezone.utc)
        return (
            datetime(year=now.year, month=1, day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc) + timedelta(days=days) + timedelta(seconds=secs)
            if days is not None and secs is not None
            else now
        )

    @property
    def system_now_datetime(self) -> datetime:
        # lsystem time in local timezone
        return datetime.now().astimezone().replace(microsecond=0)

    def debug(self, message, force: bool = False):
        # ideal message is function_name: message
        if SHOW_TRACE or force:
            print(f"{self.Info}::{message}")

    #
    # XPPYTHON INTERFACE
    #
    def XPluginStart(self) -> tuple[str, str, str]:
        self.debug("XPluginStart: starting..")

        if len(missing_modules) > 0:
            try:
                xp_pip.load_packages(missing_modules, "Loading missing modules", "Modules loaded.\nCheck for errors, and RESTART X-Plane.")
                self.debug(f"XPluginEnable: loaded packages {missing_modules}", force=True)
            except Exception as e:
                self.debug(f"XPluginEnable: could not load packages {missing_modules}: {e}", force=True)

        for d in self.header.values():
            d.init()

        for d in self.fdr_mand.values():
            d.init()

        for d in self.navaid_freqs:
            d.init()

        # Install output dir
        outdir = os.path.join(xp.getSystemPath(), "Output", "fdr")
        if not os.path.isdir(outdir):
            os.makedirs(outdir)

        # Install plugin in X-Plane
        self.fdrCmdRef = xp.createCommand(FDR_RESET_COMMAND, FDR_RESET_COMMAND_DESC)
        xp.registerCommandHandler(self.fdrCmdRef, self.fdrCmd, 1, None)
        if self.fdrCmdRef is not None:
            self.debug("XPluginStart: command registered")
        else:
            self.debug("XPluginStop: command not registered")

        self.menuIdx = xp.appendMenuItemWithCommand(xp.findPluginsMenu(), FDR_MENU, self.fdrCmdRef)
        if self.menuIdx is None or (self.menuIdx is not None and self.menuIdx < 0):
            self.debug("XPluginStart: menu not added")
        else:
            xp.checkMenuItem(xp.findPluginsMenu(), self.menuIdx, 1)
            self.debug("XPluginStart: menu added")

        self.debug("XPluginStart: ..started")
        return self.Name, self.Sig, self.Desc

    def XPluginStop(self):
        self.debug("XPluginStop: stopping..")

        if self.fdrCmdRef:
            xp.unregisterCommandHandler(self.fdrCmdRef, self.fdrCmd, 1, None)
            self.fdrCmdRef = None
            self.debug("XPluginStop: command unregistered")
        else:
            self.debug("XPluginStop: command not unregistered")

        if self.menuIdx is not None and self.menuIdx >= 0:
            oldidx = self.menuIdx
            xp.removeMenuItem(xp.findPluginsMenu(), self.menuIdx)
            self.menuIdx = None
            self.debug("XPluginStop: menu removed")
        else:
            self.debug("XPluginStop: menu not removed")

        self.debug("XPluginStop: ..stopped")

    def XPluginEnable(self) -> int:
        self.debug("XPluginEnable: enabling..")
        self.load_preferences()
        if AUTOSTART:
            self.start_supervisor()
        self._enabled = True
        self.debug("XPluginEnable: ..enabled")
        return 1

    def XPluginDisable(self):
        self.debug("XPluginEnable: disabling..")
        if self._enabled:
            self.stop_recording()
            self.close_fdr_file()
            if AUTOSTART:
                self.stop_supervisor()
            self.debug("XPluginDisable: ..disabled")
        else:
            self.debug("XPluginDisable: ..was not enabled")
        self._enabled = False

    def requiresReload(self, inMessage) -> bool:
        return inMessage in XP_MESSAGE_OF_INTEREST  # xp.MSG_DATAREFS_ADDED

    def XPluginReceiveMessage(self, inFromWho, inMessage, inParam):
        self.debug(f"XPluginReceiveMessage: received {inMessage} (interest={self.requiresReload(inMessage)})", force=True)
        if self.requiresReload(inMessage):
            if self.load_acf_preferences():
                self.debug(f"XPluginReceiveMessage: received {inMessage}, preference reloaded", force=True)
            else:
                self.debug(f"XPluginReceiveMessage: received {inMessage}, preference not reloaded")

        # if inMessage != xp.MSG_PLANE_CRASHED:
        #     self.stop_recording()
        #     self.close_fdr_file()
        #     self.debug("XPluginReceiveMessage: PLANE_CRASHED, FDR terminated", force=True)

        # if inMessage != xp.MSG_PLANE_UNLOADED:
        #     self.stop_recording()
        #     self.close_fdr_file()
        #     self.debug("XPluginReceiveMessage: PLANE_UNLOADED, FDR terminated", force=True)

        if inMessage != xp.MSG_PLANE_LOADED:
            return
        if not self._enabled:
            return

        self.debug("XPluginReceiveMessage: PLANE_LOADED", force=True)
        acfpath = self.header.get("ACFT").value
        if acfpath is not None and acfpath == self.last_acf:
            self.debug("XPluginReceiveMessage: aircraft preference file already loaded")
            return
        if self.load_acf_preferences():
            self.debug("XPluginReceiveMessage: PLANE_LOADED, preference loaded", force=True)

    def fdrCmd(self, commandRef, phase: int, refCon: Any):
        if not self._enabled:
            self.debug("fdrCmd: not enabled", force=True)
            return 1

        if phase != 0:
            return 1

        if self.file is None:  # toggle ON
            outfile = self.open_fdr_file()
            self.start_recording()
            self.debug(f"fdrCmd: FDR started manually, saving FDR into {outfile}", force=True)
        else:  # toggle OFF
            self.stop_recording()
            self.close_fdr_file()
            self.debug("fdrCmd: FDR stopped manually", force=True)
        return 1

    #
    # PREFERENCES
    #
    @property
    def need_delayed_init(self) -> bool:
        return self.custom_chocks is None and self.prefs.get("chocks") is not None

    def delayed_init(self):
        if self.custom_chocks is None:
            custom_chocks = self.prefs.get("chocks")
            if custom_chocks is not None and (self.custom_chocks is None or custom_chocks != self.custom_chocks.dataref):
                cs_fdrdata = FDRData("CHOK", dataref=custom_chocks)
                if cs_fdrdata.init():
                    self.custom_chocks = cs_fdrdata
                    self.debug(f"delayed_init: using custom chocks dataref {custom_chocks}", force=True)
                else:
                    self.debug(f"delayed_init: failed to init custom chocks dataref {custom_chocks}, using default chocks dataref", force=True)

    def install_preferences(self, newprefs: dict) -> bool:
        global AUTOSTOP_THRESHOLD, AUTOSTART, AIRBUSPHASE, SHOW_TRACE

        SHOW_TRACE = newprefs.get("trace", SHOW_TRACE)

        desc = newprefs.get("description")
        if desc is not None:
            self.debug(f"install_preferences: installing {desc}..", force=True)

        self.arch = newprefs.get("fdr_arch", FDR_ARCH)
        if self.arch not in [FDR_ARCH, "IBM"]:
            self.arch = FDR_ARCH

        AIRBUSPHASE = newprefs.get("airbus", False)
        AUTOSTART = newprefs.get("autostart", True)
        if not AUTOSTART and self.supervisor_running:
            self.stop_supervisor()
        AUTOSTOP_THRESHOLD = newprefs.get("stop_timeout", 600)

        self.frequency = abs(newprefs.get("frequency", WRITE_FREQUENCY))  # no per frame request
        self.report_frequency = max(newprefs.get("report_frequency", REPORT_FREQUENCY), REPORT_FREQUENCY)  # set to 0 to ignore

        custom_chocks = newprefs.get("chocks")
        if custom_chocks is not None:
            if self.custom_chocks is None or custom_chocks != self.custom_chocks.dataref:
                cs_fdrdata = FDRData("CHOK", dataref=custom_chocks)
                if cs_fdrdata.init():
                    self.custom_chocks = cs_fdrdata
                    self.debug(f"install_preferences: using custom chocks dataref {custom_chocks}", force=True)
                else:
                    self.debug(f"install_preferences: failed to init custom chocks dataref {custom_chocks}, using default chocks dataref", force=True)
        else:
            self.debug("install_preferences: using default chocks dataref")
            self.custom_chocks = None

        # Add optional datarefs
        opts = newprefs.get("fdr_data", {})
        if len(opts) > 0:
            if len(self.fdr_data) > 1:
                self.debug(f"install_preferences: uninstalling {len(self.fdr_data)} optional datarefs", force=True)
            self.fdr_data = {}
            for d in opts:
                callback = d.get("callback")
                if callback is not None:
                    del d["callback"]
                f = FDRData(**d)
                f.init()
                self.fdr_data[f.name] = f
            self.debug(f"install_preferences: added {len(self.fdr_data)} datarefs to monitor", force=True)

        # Add information datarefs
        opts = newprefs.get("fdr_info", {})
        if len(opts) > 0:
            if len(self.fdr_info) > 1:
                self.debug(f"uninstalling {len(self.fdr_info)} info datarefs", force=True)
            self.fdr_info = {}
            for d in opts:
                f = FDRData(**d)
                f.init()
                self.fdr_info[f.name] = f
            self.debug(f"install_preferences: added {len(self.fdr_info)} info datarefs", force=True)

        # commands
        cmds = newprefs.get("commands", {})
        if len(cmds) > 0:
            self.commands = cmds

        # navaid frequencies
        opts = newprefs.get("navaid_freqs_optional", {})
        if len(opts) > 0:
            if len(self.navaid_freqs_optional) > 1:
                self.debug(f"uninstalling {len(self.navaid_freqs_optional)} navaid frequencies", force=True)
            self.navaid_freqs_optional = {}
            for d in opts:
                f = FDRData.new(dataref=d)
                f.init()
                self.navaid_freqs_optional.append(f)
            self.debug(f"install_preferences: added {len(self.navaid_freqs_optional)} navaid frequencies", force=True)

        self.prefs = newprefs
        if desc is not None:
            self.debug(f"..{desc} installed", force=True)

        # ################################################
        #
        icao = self.header.get("ICAO").value
        author = self.header.get("AUTH").value
        self.debug(f"install_preferences: {icao} by {author}", force=True)
        if author is not None:
            author = author.trim().replace(" ", "").lower()
        if AIRBUSPHASE and icao in ["A321", "A21N"] and author in ["glidingkiwi", "toliss"]:
            all_datarefs_by_name = self.header | self.fdr_info | self.fdr_mand | self.fdr_data
            self._afp = AirbusFlightPhase(
                dt=self.simulator_zulu_datetime, datarefs=all_datarefs_by_name, alt_reg=self.vertical_lr, spd_reg=self.speed_lr, airtime=self.had_air_time
            )
            if self._afp.valid:
                self.debug("install_preferences: AirbusFlightPhase enabled", force=True)
            else:
                self.debug("install_preferences: AirbusFlightPhase invalid, disabled", force=True)
                self._afp = None
        #
        # ################################################
        return True

    def load_acf_preferences(self) -> bool:
        try:
            acfpath = self.header.get("ACFT").value
            if acfpath is not None and acfpath == self.last_acf:  # DO NOT CHECK IF FILE HAS CHANGED!
                self.debug("load_acf_preferences: aircraft preference file already loaded")
                return True
            if acfpath is not None:
                acffile = os.path.join(xp.getSystemPath(), acfpath)
                acffile = os.path.join(os.path.dirname(acffile), FDR_PREFERENCE_FILE)
                if os.path.exists(acffile):  # try aircraft-specific pref
                    self.debug(f"load_acf_preferences: aircraft preference file found at {acffile}", force=True)
                    with open(acffile, "r") as fp:
                        prefs = yaml.load(fp)
                    # with open(acffile.replace("yaml", "toml"), "rb") as fp:
                    #     test = tomllib.load(fp)
                    #     self.debug(f"TOML >>> {test}")
                    if len(prefs) > 0:  # cleanly install prefs
                        was_started = False
                        if self.file is not None:  # close old one
                            was_started = True
                            self.stop_recording()
                            self.close_fdr_file()
                            self.debug("load_acf_preferences: FDR stopped for old preferences", force=True)
                        self.install_preferences(prefs)
                        self.last_acf = acfpath
                        if was_started:  # open new one
                            outfile = self.open_fdr_file()
                            self.start_recording()
                            self.debug(f"load_acf_preferences: FDR started with new preferences, saving FDR into {outfile}", force=True)
                    self.debug("load_acf_preferences: aircraft preference file loaded")
                    return True
                else:
                    if SHOW_TRACE:
                        self.debug(f"load_acf_preferences: no aircraft preference file {acffile}")
                    else:
                        self.debug("no aircraft preference file", force=True)
        except Exception as e:
            self.debug(f"load_acf_preferences: exception: {e}", force=True)
            print_exc()
        return False

    def load_preferences(self) -> bool:
        if self.load_acf_preferences():
            # self.debug(f"load_preferences: already loaded")
            return True  # do not load global preferences
        preffile = os.path.join(xp.getSystemPath(), "Output", "preferences", FDR_PREFERENCE_FILE)
        if os.path.exists(preffile):
            self.debug(f"load_preferences: preference file found at {preffile}", force=True)
            try:
                with open(preffile, "r") as fp:
                    prefs = yaml.load(fp)
                self.install_preferences(prefs)
                self.debug("load_acf_preferences: preference file loaded")
                return True
            except Exception as e:
                self.debug(f"load_preferences: exception: {e}", force=True)
                self.prefs = {}
                return False

        if SHOW_TRACE:
            self.debug(f"load_preferences: no preference file {preffile}")
        else:
            self.debug("no preference file", force=True)
        return False

    #
    # SUPERVISON (auto-start/stop FDR, runs infrequently)
    #
    @property
    def supervisor_running(self) -> bool:
        return self.supervisorFL is not None

    def supervisor(self, elapsedSinceLastCall, elapsedTimeSinceLastFlightLoop, counter, inRefcon):
        try:
            if self.need_delayed_init:
                self.delayed_init()
            self.collect_navaids()
            self.estimated_state = self.flight_status
            if self.replay_mode and self.recorder_running:
                self.debug("supervisor: replay mode detected, stoping FDR..", force=True)
                self.stop_recording()
                self.close_fdr_file()
                self.debug("supervisor: ..FDR stopped", force=True)
            if self.estimated_state in [FLIGHT.MOVING_ON_GROUND, FLIGHT.IN_AIR] and not self.recorder_running:  # toggle ON
                if self.replay_mode:
                    self.debug("supervisor: replay mode detected, no start", force=True)
                else:
                    self.debug("supervisor: move detected, starting FDR..", force=True)
                    outfile = self.open_fdr_file()
                    self.start_recording()
                    self.debug(f"supervisor: ..started, saving FDR into {outfile}", force=True)
            else:  # stop after a 10 minute continuous stopped time out?
                tdiff = self.how_long_stopped()
                if tdiff > AUTOSTOP_THRESHOLD and self.recorder_running:
                    self.debug(f"supervisor: stopped for {tdiff} seconds, stopping FDR..", force=True)
                    if self.file is not None:
                        self.stop_recording()
                        self.close_fdr_file()
                        self.debug("supervisor: ..FDR stopped", force=True)
                    else:
                        self.debug("supervisor: file aready closed?", force=True)
        except Exception as e:
            self.debug(f"supervisor: exception: {e}", force=True)
        return AUTOSTART_FREQUENCY

    def start_supervisor(self):
        if self.supervisorFL is None:
            self.supervisorFL = xp.createFlightLoop(callback=self.supervisor, phase=xp.FlightLoop_Phase_AfterFlightModel, refCon=self.refSupervisor)
            xp.scheduleFlightLoop(self.supervisorFL, AUTOSTART_FREQUENCY, 1)
            self.debug("start_supervisor: started", force=True)

    def stop_supervisor(self):
        if self.supervisorFL is not None:
            xp.destroyFlightLoop(self.supervisorFL)
            self.supervisorFL = None
            self.debug("stop_supervisor: stopped", force=True)

    #
    # RECORDER
    #
    def open_fdr_file(self) -> str:
        outdir = os.path.join(xp.getSystemPath(), "Output", "fdr")
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
        outfile = os.path.join(outdir, f"fdr{self.simulator_zulu_datetime.strftime("%Y%m%d%H%M%S")}.fdr")
        self.file = open(outfile, "w")
        return outfile

    def fdr_write_line(self, text):
        if self.file is not None:
            try:
                text = ''.join(c for c in text if c.isprintable() or c == "\n" or c == "\r")
                print(text, end="\n" if self.arch == FDR_ARCH else "\r\n", flush=True, file=self.file)
            except Exception as e:
                self.debug(f"write_fdr: exception: {e}", force=True)
        else:
            self.debug("write_fdr: no file", force=True)

    def close_fdr_file(self):
        if self.file is not None:
            self.file.close()
            self.file = None
            self.debug("close_fdr_file: file closed", force=True)

    def start_situation(self):
        if self.file is None:
            return
        self.estimated_state = self.flight_status
        self.fdr_write_line(f"\nCOMM, INFO Flight state {self.estimated_state.name}")
        lat = self.fdr_mand.get("latitude").value
        lon = self.fdr_mand.get("longitude").value
        alt = self.fdr_mand.get("agl").value
        hdg = self.fdr_mand.get("heading").value
        spd = self.fdr_mand.get("gs").value
        self.fdr_write_line(f"COMM, INFO lat={lat}, lon={lon}, alt={alt}, hdg={hdg}, speed={spd}")
        self.fdr_write_line(f"COMM, INFO supervisor={AUTOSTART_FREQUENCY} recorder={self.frequency}")
        self.fdr_write_line(f"COMM, INFO custom_chocks={self.custom_chocks.dataref if self.custom_chocks is not None else 'none'}")

        # FDR Info
        if len(self.fdr_info) > 0:
            for d in self.fdr_info:
                if d.dref is None:
                    self.debug(f"start_situation: dataref {d} not found", force=True)
                    self.fdr_write_line(f"COMM, INFO dataref {d} not found")
                    continue
                self.fdr_write_line(f"COMM, INFO {d.name}: {d.dataref}={d.value}")

    def save_oooi(self):
        if all(self.oooi.values()):
            self.fdr_write_line("COMM, OOOI ----")
            self.debug("OOOI ----")
            return
        for o in OOOI:
            t = self.oooi[o]
            c = self.oooi_notes[o]
            self.debug(f"OOOI {o.name} {t}" + (f" ({c})" if c is not None else ""), force=True)
            if t is not None:
                self.fdr_write_line(f"COMM, OOOI {o.name} {t.isoformat()}" + (f" ({c})" if c is not None else ""))

    def fdr_header_lines(self):
        print(f"{FDR_ARCH[0]}\r{FDR_VERSION}\n", file=self.file)

        # Script info, use local time
        self.fdr_write_line(f"COMM, created by {SCRIPT_NAME} rel. {VERSION} on {self.system_now_datetime.isoformat()}\n")

        # FDR Meta data
        self.fdr_write_line(f"ACFT, {self.header.get('ACFT').value}")
        self.fdr_write_line(f"TAIL, {self.header.get('TAIL').value}")
        self.fdr_write_line(f"DATE, {self.simulator_zulu_datetime.strftime("%m/%d/%Y")}")  # MM/DD/YYYY
        self.fdr_write_line(f"PRES, {round(self.header.get('SEAL').value, 2)}")
        self.fdr_write_line(f"DISA, {round(self.header.get('DISA').value, 2)}")
        self.fdr_write_line(f"WIND, {int(self.header.get('WDIR').value)}," + f" {round(self.header.get('WSPD').value, 2)}")

        # FDR Datarefs
        if len(self.fdr_data) > 0:
            self.fdr_write_line("\n")
            for d in self.fdr_data.values():
                if d.dref is None:
                    self.debug(f"dataref {d} not found, not monitored", force=True)
                    self.fdr_write_line(f"COMM, dataref {d} not found, not monitored")
                    continue
                if d.writable:
                    self.fdr_write_line(f"DREF, {d.dataref}  {d.factor}")
                else:
                    self.fdr_write_line(f"DREF, {d.dataref}  {d.factor}  // not writable")

        # FDRReader meta
        self.fdr_write_line("\n")
        for d in self.fdr_all_data_values:
            self.fdr_write_line(f"COMM, {d.fun()}")

        # Additional comments
        self.start_situation()

        # CSV Header
        columns = []
        for d in self.fdr_all_data_values:
            if "zulu" in d.dataref:
                continue
            if d.value_length < 2:
                columns.append(d.name)
            else:
                for i in d.indices:
                    columns.append(f"{d.name}[{i}]")
        columns = ", ".join(columns)
        self.fdr_write_line("\nCOMM, UTC time, " + columns + "\n")
        self.debug("FDR header written")

    def fdr_data_line(self) -> str:
        def expand(l: list) -> list:
            return reduce(lambda r, e: r + ([str(i) for i in e] if isinstance(e, (list, tuple)) else [str(e)]), l, [])

        data = self.simulator_zulu_datetime.strftime("%H:%M:%S.%f")
        data = data + "," + ",".join(expand([d.value for d in self.fdr_all_data_values if "zulu" not in d.dataref]))
        return data + "\n"

    @property
    def recorder_running(self) -> bool:
        return self.file is not None and self.recorderFL is not None

    def record(self, elapsedSinceLastCall, elapsedTimeSinceLastFlightLoop, counter, inRefcon):
        try:
            if self.file is not None:
                self.fdr_write_line(self.fdr_data_line())
                self.writes = self.writes + 1
                self.file.flush()
                if self.report_frequency > 0 and self.writes % self.report_frequency == 0:
                    self.debug(f"loop: at {self.simulator_zulu_datetime.strftime('%H:%M:%S')} {self.writes} events since {self.start_time.strftime('%H:%M:%S')}", force=True)
            else:
                self.debug("loop: no fdr file", force=True)
        except Exception as e:
            self.debug(f"record: exception: {e}", force=True)

        return self.frequency

    def start_recording(self):
        if self.file is not None:
            self.start_command_logging()
            self.start_time = self.simulator_zulu_datetime
            self.last_stop = None
            self.writes = 0
            self.fdr_header_lines()
            if self.recorderFL is None:
                self.recorderFL = xp.createFlightLoop(callback=self.record, phase=xp.FlightLoop_Phase_AfterFlightModel, refCon=self.refRecorder)
                xp.scheduleFlightLoop(self.recorderFL, self.frequency, 1)
                xp.checkMenuItem(xp.findPluginsMenu(), self.menuIdx, 2)
                st = self.simulator_zulu_datetime.isoformat()
                self.fdr_write_line(f"COMM, start recording on {self.system_now_datetime.isoformat()} (sim time={st})\n")
                self.debug(f"start_recording: started at {self.start_time.isoformat()}")
        else:
            self.debug("start_recording: no file, not started")

    def stop_recording(self):
        if self.recorderFL is not None:
            self.stop_command_logging()
            xp.destroyFlightLoop(self.recorderFL)
            xp.checkMenuItem(xp.findPluginsMenu(), self.menuIdx, 1)
            self.recorderFL = None
            if self.file is not None:
                self.save_oooi()
                if not WRITE_ASAP:
                    self.save_command_execution()
                    self.save_navaids()
                if self._afp is not None:
                    self._afp.save(file=self.file)
                self.fdr_write_line(f"\n\nCOMM, end recording on {self.system_now_datetime.isoformat()} ({self.writes} writes)")
                self.fdr_write_line(f"COMM, created by {SCRIPT_NAME} rel. {VERSION} on {self.system_now_datetime.isoformat()}\n")
            self.debug(f"stop_recording: stopped at {self.start_time.isoformat()}")

    #
    # NAVAIDS
    # Record nav aids around the aircraft
    # or pointed by aircraft nav tuned frequencies
    #
    def save_navaids(self):
        # On file close, Writes encountered navaids to FDR as comments
        for n in self.navaids.values():
            n.navType = n.navType.name
            self.fdr_write_line(f"COMM, {n}")

    def collect_navaids(self):
        if not self.recorder_running:
            return
        NAVAID_CYCLE = [xp.Nav_NDB, xp.Nav_Fix, xp.Nav_VOR, xp.Nav_Fix, xp.Nav_DME, xp.Nav_Fix]
        # ?? sim/cockpit2/radios/actuators/tac1_channel
        # ?? sim/cockpit2/radios/actuators/tac2_channel
        try:
            # do not always search for several types to find more nav aids around
            lat = self.fdr_mand.get("latitude").value
            lon = self.fdr_mand.get("longitude").value
            types = NAVAID_CYCLE[self.navaid_counter % len(NAVAID_CYCLE)]
            self.navaid_counter += 1
            navaid = xp.findNavAid(lat=lat, lon=lon, navType=types)
            if navaid != xp.NAV_NOT_FOUND:
                d = xp.getNavAidInfo(navaid)
                k = f"{d.type}:{d.name}"
                if k not in self.navaids:
                    c = NavAid(
                        name=d.name,
                        navType=NAVAID_TYPE(d.type),
                        lat=d.latitude,
                        lon=d.longitude,
                        height=d.height,
                        frequency=d.frequency,
                        heading=d.heading,
                        navAidId=d.navAidID,
                        reg=d.reg,
                    )
                    self.navaids[k] = c
                    if WRITE_ASAP:
                        self.fdr_write_line(f"COMM, {c}")
                    self.debug(f"collect_navaids: {c}")

            for radio in self.all_navaid_freqs:
                freq = radio.value
                if freq is not None:
                    if freq > 80000:
                        freq = freq / 100
                    # navaid = xp.findNavAid(freq=freq)
                    navaid = xp.findNavAid(lat=lat, lon=lon, freq=freq)
                    if navaid != xp.NAV_NOT_FOUND:
                        d = xp.getNavAidInfo(navaid)
                        k = f"{d.type}:{d.name}"
                        if k not in self.navaids:
                            c = NavAid(
                                name=d.name,
                                navType=NAVAID_TYPE(d.type),
                                lat=d.latitude,
                                lon=d.longitude,
                                height=d.height,
                                frequency=d.frequency,
                                heading=d.heading,
                                navAidId=d.navAidID,
                                reg=d.reg,
                            )
                            self.navaids[k] = c
                            if WRITE_ASAP:
                                self.fdr_write_line(f"COMM, {c}")
                            self.debug(f"collect_navaids: R {freq} {c}")
        except Exception as e:
            self.debug(f"collect_navaids: error {e}")
            print_exc()

    #
    # COMMANDS
    # Monitors command execution
    #
    def save_command_execution(self):
        # On file close, Writes encountered navaids to FDR as comments
        for c in self.commandExecs:
            self.fdr_write_line(f"COMM, {c}")

    def logCommandExecution(self, commandRef, phase, refcon):
        RECORD_PHASE = [2]
        if phase in RECORD_PHASE:
            c = Command(name=refcon["command"], before=refcon["before"], phase=phase, index=self.writes, when=self.simulator_zulu_datetime.isoformat())
            self.commandExecs.append(c)
            self.debug(f"logCommandExecution: {c}")
            if WRITE_ASAP:
                self.fdr_write_line(f"COMM, {c}")
        return 1

    def start_command_logging(self):
        if len(self.commands) > 0:
            for c in self.commands:
                self.commandRefs[c] = xp.findCommand(c)
                if self.commandRefs[c] is not None:
                    self.commandRefCons[c] = {"command": c, "before": 1}
                    xp.registerCommandHandler(commandRef=self.commandRefs[c], callback=self.logCommandExecution, before=1, refCon=self.commandRefCons[c])
                    # self.commandRefCons[c+"A"] = {"command": c, "before": 0}
                    # xp.registerCommandHandler(commandRef=self.commandRefs[c], callback=self.logCommandExecution, before=0, refCon=self.commandRefCons[c+"A"])
                    self.debug(f"start_command_logging: installed {c}")
                else:
                    del self.commandRefs[c]
            self.debug(f"start_command_logging: logging {len(self.commandRefs)} command", force=True)

    def stop_command_logging(self):
        if len(self.commandRefs) > 0:
            for c in self.commands:
                if c in self.commandRefs:
                    xp.unregisterCommandHandler(commandRef=self.commandRefs[c], callback=self.logCommandExecution, before=1, refCon=self.commandRefCons[c])
                    self.debug(f"stop_command_logging: uninstalled {c}")
                    # xp.unregisterCommandHandler(commandRef=self.commandRefs[c], callback=self.logCommandExecution, before=0, refCon=self.commandRefCons[c+"A"])
                    # self.debug(f"stop_command_logging: uninstalled {c+"A"}")
            self.commandRefs = {}
            self.debug("stop_command_logging: done", force=True)

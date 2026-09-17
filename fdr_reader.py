import sys
import json
import re
from datetime import date, datetime, timedelta, timezone
from pprint import pprint
from enum import Enum
from traceback import print_exc

from PI_fdr import FDRData, NavAid, Command

HEADER_KEYWORDS = [
    "ACFT",
    "TAIL",
    "TIME",
    "DATE",
    "PRES",
    "TEMP",
    "WIND",
    "DISA",
]

DATA_KEYWORDS = [
    "COMM",
    "DREF",
    "CALI",
    "WARN",
    "TEXT",
    "MARK",
    "EVNT",
    "DATA",
]


def clean(s: str) -> tuple:
    SEP = ","
    a = [b.strip() for b in s.split(SEP)]
    return a[0], SEP.join(a[1:]), s[s.index(SEP) + 1 :].strip()


def best_type(s) -> int | float | str:
    if type(s) is float:
        return s
    if type(s) is int:
        return s
    if type(s) is str:  # type to convert
        try:
            a = int(s)
            return a
        except ValueError:
            pass
        try:
            a = float(s)
            return a
        except ValueError:
            pass
    return s


def get_time(s: str) -> datetime:
    ts = None
    s = s.strip()
    if len(s) > 8:  # "12:45:78.901234"
        ts = datetime.strptime(s, "%H:%M:%S.%f")
    else:
        ts = datetime.strptime(s, "%H:%M:%S")
    return ts


class FDR_STDOUT(Enum):
    NONE = set()
    MIN = {"ground_speed", "altitude"}
    STD = {"ground_speed", "altitude", "heading", "pitch", "roll"}
    ALL = None


class FDRReader:

    def __init__(self, filename: str = "out.fdr") -> None:
        self.filename = filename
        self.fdr_version = 0

        with open(self.filename) as fp:
            self.lines = [l.strip() for l in fp.readlines()]

        self.basedate = None  # datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        self.basetime = None
        self.meta = {k: list() for k in DATA_KEYWORDS}
        self.units = []
        self.header = []
        self.data = []
        self._last_ts = None
        self.fdr_data = {}
        self.navaids = {}
        self.commands = []

    @property
    def duration(self) -> timedelta:
        if len(self.data) > 1:
            start = get_time(self.data[0][0].strip())
            end = get_time(self.data[-1][0].strip())
            return end - start
        return timedelta(0)

    @property
    def length(self) -> int:
        return len(self.data)

    @property
    def has_fdrdata(self) -> bool:
        return len(self.fdr_data) > 0

    def parse(self) -> bool:
        #
        # ACFT, Aircraft/Airbus/ToLiss A321/a321.acf
        # TAIL, OO-PMA
        # DATE, 7/29/2025
        # PRES, 30.0
        # DISA, 0
        # WIND, 270, 2.61
        #
        def name_values(s):
            matches = re.findall(r"(\w+)=('.*?'|\".*?\"|\s*\w+\(.*?\)|[^,=\s\)]+)", text)
            keyval = {}
            for match in matches:
                value = match[1].strip(" ,'").strip('"')
                try:
                    try:
                        value = int(value)
                    except:
                        value = float(value)
                except:
                    pass
                keyval[match[0]] = value if value != "None" else None
            return keyval

        header_out = False

        if self.lines[0] != "A":
            print(f"invalid X-Plane FDR file ({self.lines[0]})")
            return False

        if self.lines[1][0] not in ["3", "4"]:
            print(f"invalid X-Plane FDR file version ({self.lines[1]})")
            return False

        self.fdr_version = int(self.lines[1][0])
        print(f"FDR data format version {self.fdr_version}")

        i = 2
        data_index = 1
        while i < len(self.lines):
            if len(self.lines[i]) == 0:
                i += 1
                continue

            currline = self.lines[i]
            k, data, text = clean(currline)

            if k in HEADER_KEYWORDS:
                if k in self.meta:
                    print(f"warning: header keyword {k} value overwritten {self.meta[k]} -> {currline[5:].strip()}")
                self.meta[k] = text

                if k == "DATE":
                    self.basedate = datetime.strptime(text, "%m/%d/%Y").replace(tzinfo=timezone.utc)
                    if self.basetime is not None:
                        t = self.basetime.split(":")
                        self.basedate = self.basedate.replace(hour=int(t[0]), minute=int(t[1]), second=int(t[2]))
                        print("Date and time:", self.basedate.isoformat())
                    else:
                        print("Date:", self.basedate.isoformat())

                if k == "TIME":
                    self.basetime = text
                    if self.basedate is not None:
                        t = text.split(":")
                        self.basedate = self.basedate.replace(hour=int(t[0]), minute=int(t[1]), second=int(t[2]))
                        print("Date and time:", self.basedate.isoformat())
                    else:
                        print("Time:", self.basetime)

                i += 1
                continue
            elif k in DATA_KEYWORDS and k != "DATA":
                if k == "COMM":  # create meta data for FDR
                    if text.startswith("FDRData("):
                        try:
                            keyval = name_values(text)
                            fdrdata = FDRData(**keyval)
                            fdrdata.data_index = data_index
                            self.fdr_data[fdrdata.name] = fdrdata
                            print(fdrdata.data_index, fdrdata)
                            data_index += 1;
                        except:
                            print("failed to create FDRData, skipped", text)
                            print_exc()
                        i += 1
                        continue
                    if text.startswith("NavAid("):
                        try:
                            keyval = name_values(text)
                            navaid = NavAid(**keyval)
                            navaid_key = f"{navaid.navType}:{navaid.name}"
                            self.navaids[navaid_key] = navaid
                            print(navaid)
                        except:
                            print("failed to create NavAid, skipped", text)
                            print_exc()
                    if text.startswith("Command("):
                        try:
                            keyval = name_values(text)
                            command = Command(**keyval)
                            self.commands.append(command)
                            print(command)
                        except:
                            print("failed to create Command, skipped", text)
                            print_exc()
                        i += 1
                        continue
                self.meta[k].append((self._last_ts, text))
                i += 1
                continue

            # else, probably data...
            # if first data encounted, hope last comment was column headings
            if not header_out and len(self.meta["COMM"]) > 0:
                header_line = self.meta["COMM"][-2][1]
                self.header = [l.strip() for l in header_line.split(",")]
                t = self.header[0]
                if not "time" in self.header[0].lower():
                    self.header = ["UTC Time"] + self.header
                print(f"Header {', '.join(self.header)}")
                header_out = True

            if self.fdr_version == 3 and k == "DATA":
                self.data.append([l.strip() for l in data.split(",")])
                secs = float(self.data[-1][0].strip())
                self._last_ts = self.basedate + timedelta(seconds=secs)
                self.data[-1][0] = self._last_ts.strftime("%H:%M:%S.%f")
            else:
                self.data.append([l.strip() for l in currline.split(",")])
                ts = get_time(self.data[-1][0])
                self._last_ts = ts.replace(tzinfo=timezone.utc, day=self.basedate.day, month=self.basedate.month, year=self.basedate.year)
            i += 1

        if self.has_fdrdata:
            #   print(f"FDRData for {', '.join(self.fdr_data)}")
            if len(self.header) - 1 != len(self.fdr_data):
                print(f"Header column vs FDRData mismatch {len(self.header) - 1}/{len(self.fdr_data)}")

        return True

    def properties(self, data) -> dict:
        props = {}
        for dref, v in zip(self.header[1:], data):
            if self.has_fdrdata:
                meta = self.fdr_data[dref]
                if meta.dref is not None:
                    if meta.dref.dtype == "int":
                        props[dref] = int(float(v))
                    elif meta.dref.dtype == "float":
                        props[dref] = float(v)
                    else:
                        props[dref] = best_type(v)
                else:
                    props[dref] = best_type(v)
            else:
                props[dref] = best_type(v)
        return props  # {self.header[i]: float(data[i].strip()) for i in range(1, len(data))}

    def to_geojson(self, outfile: str, altitude: bool = False, properties: FDR_STDOUT | list | None = None):
        # Assumes all data are float except first one that is a timestamp
        # TS is datetime.now(datetime.UTC).strftime("%H:%M:%S.%f, ")
        features = []
        lines = []
        feature_index = 0
        if type(properties) is FDR_STDOUT:
            properties = properties.value
        if properties is None:
            properties = self.header
        print(properties)
        for row in self.data:
            # coordinates
            p = [float(row[1]), float(row[2])]
            # altitude
            alt = None
            ele = self.fdr_data.get("ellipsoid_height")  # as requested by GeoJSON
            if ele is None:
                ele = self.fdr_data.get("elevation")  # MSL backup without ellipsoid
            if ele is None:
                ele = self.fdr_data.get("altitude")  # desperate
            if ele is not None:
                alt = float(row[ele.data_index]) / 3.28084
            if alt is None:  # really desperate
                alt = float(row[3])
            if altitude and alt is not None:
                p.append(alt)
            lines.append(p)
            # time
            ts = get_time(row[0])
            ts = ts.replace(tzinfo=timezone.utc, day=self.basedate.day, month=self.basedate.month, year=self.basedate.year)
            # properties
            props = {"id": feature_index, self.header[0]: ts.isoformat(), "_raw_ts": ts.timestamp()}

            if len(self.header) != len(row):
                print("length mismatch", len(self.header), len(row))
            props = props | {n: best_type(v) for n, v in zip(self.header[1:], row[1:])}
            t = row[0].strip().split(":")
            f = 0
            try:
                f = float(t[2])
                f = int(f)
            except:
                pass
            ts = self.basedate.replace(hour=int(t[0]), minute=int(t[1]), second=f)
            try:
                f = float(t[2])
                f -= int(f)
                if f > 0:
                    ts.replace(microsecond=int(100000 * f))
            except:
                pass
            props["UTC Time"] = ts.isoformat()
            # feature
            features.append({"type": "Feature", "id": feature_index, "geometry": {"type": "Point", "coordinates": p}, "properties": props})
            feature_index += 1

        # add whole line string
        feature_index += 1
        features.append({"type": "Feature", "id": feature_index, "geometry": {"type": "LineString", "coordinates": lines}, "properties": {"name": "flight path"}})
        # navaids
        for n in self.navaids.values():
            feature_index += 1
            features.append(
                {
                    "type": "Feature",
                    "id": feature_index,
                    "geometry": {"type": "Point", "coordinates": [n.lon, n.lat]},
                    "properties": {
                        "name": n.name,
                        "navType": n.navType.replace("Nav_", ""),
                        "navAidId": n.navAidId,
                        "height": round(n.height, 1),
                        "heading": round(n.heading, 1),
                        "frequency": n.frequency / 100,
                        "reg": n.reg,
                    },
                }
            )
        # commands
        for c in self.commands:
            feature_index += 1
            features.append(
                {
                    "type": "Feature",
                    "id": feature_index,
                    "geometry": features[c.index]["geometry"],
                    "properties": {
                        "command": c.name,
                        "UTC Time": c.when,
                        "index": c.index,
                        "phase": c.phase,
                        "before": c.before,
                    },
                }
            )

        # if 3D, add draped polygon
        if altitude:
            AIRPORT_ALT = min([a[2] for a in lines])
            # whole path with no altitude
            feature_index += 1
            features.append(
                {
                    "type": "Feature",
                    "id": feature_index,
                    "geometry": {"type": "LineString", "coordinates": [[l[0], l[1]] for l in lines]},
                    "properties": {"name": "flight path, no altitude"},
                }
            )
            # whole path with airport altitude
            feature_index += 1
            features.append(
                {
                    "type": "Feature",
                    "id": feature_index,
                    "geometry": {"type": "LineString", "coordinates": [[l[0], l[1], AIRPORT_ALT] for l in lines]},
                    "properties": {"name": "flight path, ground altitude"},
                }
            )
            # draped polygon
            ground = [[l[0], l[1], AIRPORT_ALT] for l in lines[::-1]]
            polygon = lines + ground
            polygon.append(lines[0])  # close it
            feature_index += 1
            features.append({"type": "Feature", "id": feature_index, "geometry": {"type": "Polygon", "coordinates": [polygon]}, "properties": {"name": "draped flight path"}})

        with open(outfile, "w") as geoj:
            json.dump({"type": "FeatureCollection", "features": features}, geoj, indent=4)

    def to_csv(self, outfile: str, properties: list | None = None):
        if type(properties) is FDR_STDOUT:
            properties = properties.value
        if properties is None:
            properties = self.header
        else:
            properties.append("latitude")
            properties.append("longitude")

        with open(outfile, "w") as fp:
            # header
            print(",".join(["_raw_ts", "utc_time"] + self.header[1:]), file=fp)
            # data
            for row in self.data:
                ts = get_time(row[0].strip())
                ts = ts.replace(tzinfo=timezone.utc, day=self.basedate.day, month=self.basedate.month, year=self.basedate.year)
                frow = row[1:]
                print(",".join([str(ts.timestamp()), row[0]] + frow), file=fp)


# ######################################################
#
if __name__ == "__main__":
    if len(sys.argv) > 1:
        for file in sys.argv[1:]:
            a = FDRReader(filename=file)
            if a.parse():
                # print("Fields:", a.header)
                pprint(a.meta, width=120)
                a.to_geojson(outfile=f"{file}.geojson", altitude=True)
                a.to_csv(outfile=f"{file}.csv")
                print(f"{file}.geojson, {file}.csv: {a.length} points written, duration={a.duration}")
            else:
                print(f"{file}: failed to parse")
    else:
        a = FDRReader()
        if a.parse():
            # print("Fields:", a.header)
            # pprint(a.meta, width=120)
            props = FDR_STDOUT.ALL  # FDR_STDOUT.STD  # {"altitude"}
            a.to_geojson(outfile="out.geojson", altitude=True, properties=props)
            a.to_csv(outfile="out.csv", properties=props)
            print(f"{a.length} points written, duration={a.duration}")
        else:
            print("failed to parse")

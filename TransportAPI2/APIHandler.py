import datetime
import os
import re
import time
from math import sqrt
from threading import Thread
from UtilLib.JSONHandler import JSONHandler
from UtilLib.Logging import LoggerClass
from UtilLib.RequestHandler import RequestHandler, RequestError
from TransportAPI2.RequestLink import URL_DATAMALL_API, DATAMALL_PAGE_SIZE

# Global variables
LON_LAT_CONV = 111139
# Max cache age in seconds before a refresh is attempted
CACHE_MAX_AGE = {
    "bus_stops": 24 * 3600,
    "bus_services": 24 * 3600,
    "bus_routes": 7 * 24 * 3600,
}
SEATING = {
    "SEA": {
        "text": "Seating Available",
        "emoji": "🟩"
    },
    "SDA": {
        "text": "Standing Available",
        "emoji": "🟨"
    },
    "LSD": {
        "text": "Limited Standing",
        "emoji": "🟥"
    }
}
BUS_TYPE = {
    "SD": {
        "text": "Single Deck",
    },
    "DD": {
        "text": "Double Deck",
    },
    "BD": {
        "text": "Bendy",
    }
}
DBL_LOOP_DATA = {
        "42": "Lengkong Empat & Fidelio St",
        "92": "Science Pk Dr & Mount Sinai Dr",
        "291": "Tampines St 81 & Tampines St 33",
        "293": "Tampines St 71 & Tampines Ave 7",
        "307": "Choa Chu Kang St 62 & Teck Whye Lane",
        "358": "Pasir Ris Dr 10 & Pasir Ris Dr 4",
        "359": "Pasir Ris St 71 & Pasir Ris Dr 2",
        "811": "Yishun Ave 5 & Yishun Ave 1",
        "812": "Yishun Ave 4 & Yishun Ave 3",
        "911": "Woodlands Ave 2 & Woodlands Ctr Rd",
        "912": "Woodlands Ave 7 & Woodlands Ctr Rd",
        "913": "Woodlands Circle & Woodlands Ave 3"
    }


class TransportAPIHandler:
    """
    TransportAPIHandler - Version 2

    Re-write version of TransportAPIHandler & its predecessors
    """
    def __init__(self, api_key: str):
        """
        Init TransportAPIHandler class
        :param api_key: LTA API Key
        """
        self.api_key = api_key
        self._headers = {"AccountKey": api_key, "accept": "application/json"}
        self.logger = LoggerClass("TransportAPIHandler - V2")
        # Initialise JSON Handlers
        self.json_mem = JSONHandler("MemoryData") # User Memory Handler
        self.bus_stop_data = JSONHandler("BusStopData") # Bus Stop Data Handler
        self.bus_svc_data = JSONHandler("BusServiceData") # Bus Service Data Handler
        self.bus_route_data = JSONHandler("BusRouteData") # Bus Route Data Handler

        # Load cached data; refresh anything missing or stale
        self.refresh_errors = {}
        self.refresh_cache()

    def _get(self, key, **params):
        return RequestHandler(URL_DATAMALL_API[key], headers=self._headers, params=params).get_json()

    def _get_all(self, key):  # pagination, used by all 3 store methods
        out, skip = [], 0
        while True:
            data = self._get(key, **{"$skip": skip})
            if "value" not in data:
                raise RequestError(f"Unexpected response from {key}: no 'value' field")
            out.extend(data["value"])
            if len(data["value"]) < DATAMALL_PAGE_SIZE:
                return out
            skip += DATAMALL_PAGE_SIZE

    def _refresh(self, name, store_fn):
        try:
            store_fn()
        except RequestError as e:
            self.refresh_errors[name] = e
            self.logger.error(f"{name} refresh failed, keeping existing cache: {e}")
        except Exception as e:  # never let a thread die silently
            self.refresh_errors[name] = e
            self.logger.error(f"{name} refresh crashed: {type(e).__name__}: {e}")

    def refresh_cache(self, force: bool = False):
        """
        Load cached DataMall data, refreshing any cache that is missing, stale or forced.
        Failed refreshes fall back to the existing cache file if there is one.
        :param force: Refresh all caches regardless of age
        :return: True if every refresh that was attempted succeeded
        """
        caches = (
            ("bus_stops", self.bus_stop_data, self.store_bus_stop_data),
            ("bus_services", self.bus_svc_data, self.store_bus_svc_data),
            ("bus_routes", self.bus_route_data, self.store_bus_route_data),
        )
        self.refresh_errors = {}
        threads = []

        for name, handler, store_fn in caches:
            if force or self._cache_is_stale(handler, CACHE_MAX_AGE[name]):
                threads.append(Thread(target=self._refresh, args=(name, store_fn)))
            else:
                handler.formulate_json()

        for t in threads: t.start()
        for t in threads: t.join()

        # Fall back to stale cache files for any refresh that failed
        for name, handler, _ in caches:
            if name in self.refresh_errors and os.path.exists(handler.json_fp):
                handler.formulate_json()

        return not self.refresh_errors

    @staticmethod
    def _cache_is_stale(handler: JSONHandler, max_age: int):
        if not os.path.exists(handler.json_fp):
            return True
        return time.time() - os.path.getmtime(handler.json_fp) > max_age

    def request_arrival_time(self, bus_stop_code: str, explicit_buses: list, name: str):
        curr_stop_returner = self.request_bus_stop_name(bus_stop_code)
        arrival_returner = self.request_bus_stop_timing(bus_stop_code, explicit_buses)
        main_returner = []

        if curr_stop_returner[2] is True:
            print(
                f"=======================================================================================\n"
                f"{curr_stop_returner[0]} @ {curr_stop_returner[1]} [{bus_stop_code}]\n"
                f"======================================================================================="
            )
            main_returner.append(f"{curr_stop_returner[0]} @ {curr_stop_returner[1]} [{bus_stop_code}]")
        else:
            print(
                f"=======================================================================================\n"
                f"Bus Stop No: {bus_stop_code} Services\n"
                f"======================================================================================="
            )
            main_returner.append(f"Bus Stop No: {bus_stop_code} Services")

        if len(arrival_returner) == 0:
            print(
                f"There is no bus services available.\n"
                f"======================================================================================="
            )
            main_returner.append(f"There is no bus services available.")
            return main_returner

        for arrival_data in arrival_returner:
            svc_info_returner = self.return_bus_svc_json(arrival_data[0], 1)

            if svc_info_returner is None or \
                    (svc_info_returner[4] != arrival_data[18] or svc_info_returner[5] != arrival_data[19]):
                svc_info_returner = self.return_bus_svc_json(arrival_data[0], 2) or svc_info_returner

            if svc_info_returner is None:
                svc_info = "This service does not exist."

            elif svc_info_returner[7] is False:
                svc_info = f"{self._stop_name(svc_info_returner[4])} >>> " \
                           f"{self._stop_name(svc_info_returner[5])} " \
                           f"[{svc_info_returner[3]}]"

            else:
                svc_info = f"Loop @ {svc_info_returner[6]} to " \
                           f"{self._stop_name(svc_info_returner[5])} " \
                           f"[{svc_info_returner[3]}]"

            print(
                f"Service [{arrival_data[0]}] | {arrival_data[1]}\n"
                f"{svc_info}\n"
                f"=======================================================================================\n"
                f"{arrival_data[2]} | {arrival_data[5]} | {arrival_data[8]} | Visit: {arrival_data[11]}\n"
                f"{arrival_data[3]} | {arrival_data[6]} | {arrival_data[9]} | Visit: {arrival_data[12]}\n"
                f"{arrival_data[4]} | {arrival_data[7]} | {arrival_data[10]} | Visit: {arrival_data[13]}\n"
            )

            print(
                f"Estimated Duration: {arrival_data[14]} min" if arrival_data[17] is True else
                f"Estimated Duration (Visit 1): {arrival_data[15]} min\n"
                f"Estimated Duration (Visit 2): {arrival_data[16]} min"
            )

            print(
                f"======================================================================================="
            )

            main_returner.append(
                [
                    f"Service [{arrival_data[0]}] | {arrival_data[1]}",
                    f"{svc_info}",
                    f"{arrival_data[2]} | {arrival_data[5]} | {arrival_data[8]} | Visit: {arrival_data[11]}",
                    f"{arrival_data[3]} | {arrival_data[6]} | {arrival_data[9]} | Visit: {arrival_data[12]}",
                    f"{arrival_data[4]} | {arrival_data[7]} | {arrival_data[10]} | Visit: {arrival_data[13]}",
                    f"Estimated Duration: {arrival_data[14]} min" if arrival_data[17] is True else
                    f"Estimated Duration (Visit 1): {arrival_data[15]} min\n"
                    f"Estimated Duration (Visit 2): {arrival_data[16]} min"
                ]
            )
        return main_returner

    def request_bus_stop_svc_list(self, bus_stop_code: str):
        returner = ""

        # Noted that no bus services will list on end of service - Write new method and deprecate old method
        # svc_returner = request_bus_stop_timing(bus_stop_code=bus_stop_code, api_key=self.api_key, svc_num=[],
        #                                        return_svc_list=True)

        svc_returner = self.get_bus_svc_from_bus_stop_code(bus_stop_code)

        for i in range(len(svc_returner)):
            if i == 0:
                returner = str(svc_returner[i])
            else:
                returner += f", {svc_returner[i]}"

        return returner

    # Bus Arrival Functions
    @staticmethod
    def interpret_seating(seating: str, use_emoji: bool = False, retain_sf: bool = False):
        info = SEATING.get(seating)
        if info is None:
            return ""
        if use_emoji:
            return info["emoji"]
        return seating if retain_sf else info["text"]

    @staticmethod
    def interpret_type(bus_type: str, retain_sf: bool = False):
        info = BUS_TYPE.get(bus_type)
        if info is None:
            return ""
        return bus_type if retain_sf else info["text"]

    @staticmethod
    def _parse_eta(next_bus: dict, now: datetime.datetime):
        """
        Parse one NextBus entry.
        :return: (label, [HH, MM, SS], minutes) - minutes is -1 when no bus is in service
        """
        if not next_bus.get("EstimatedArrival"):
            return "Not in Service", ["X", "X", "X"], -1

        eta = datetime.datetime.fromisoformat(next_bus["EstimatedArrival"])  # keeps +08:00
        minutes = round((eta - now).total_seconds() / 60)
        nb_time = eta.strftime("%H:%M:%S").split(":")

        if minutes < 1:
            return "Arriving", nb_time, 0
        return f"{minutes} min", nb_time, minutes

    @staticmethod
    def calculate_est_duration(dur_list: list):
        divisive_num = 0
        total_dur = 0

        for dur in dur_list:
            if 0 < dur < 1000:
                divisive_num += 1
                total_dur += dur

        if divisive_num == 0:
            return total_dur

        est_duration = total_dur / divisive_num

        return round(est_duration, 1)

    def request_bus_stop_timing(self, bus_stop_code: int | str, svc_filter: list | None = None,
                                fallback_header: bool = False, debug: bool = False, return_svc_list: bool = False,
                                no_exact_time=False, short_forms=False, use_emojis=False):
        """
        Core Function to get and return the Timings of Services for a Bus Stop.
        For a specific number in Services, define the Service Number.
        :param bus_stop_code: The 5-digit Bus Stop code. Should be in string, integer not recommended for it may remove
                              leading zeros.
        :param svc_filter: A list of Bus Service Numbers to explicitly see. Optional, either string or integer is accepted in a
                        list.
        :param fallback_header: A boolean state that determines whether the fallback header should be used. (Shows the code)
        :param debug: A boolean state to show debug text
        :param return_svc_list: Returns the Bus Services for the bus stop, WILL NOT RETURN TIMING!
        :param no_exact_time: Boolean parameter to disallow the showing of exact timing for arrivals
        :param short_forms: Show short forms of certain texts
        :param use_emojis: Boolean parameter to use emoji for certain texts
        :return: A Tuple of 23 values (exc. !):
                 [0] -> Service Number,
                 [1] -> Service Operator,
                 [2] -> First Bus Timing in XX min @ XX:XX:XX,
                 [3] -> Second Bus Timing in XX min @ XX:XX:XX,
                 [4] -> Third Bus Timing in XX min @ XX:XX:XX,
                 [5] -> First Bus Seating Availability,
                 [6] -> Second Bus Seating Availability,
                 [7] -> Third Bus Seating Availability,
                 [8] -> First Bus Type,
                 [9] -> Second Bus Type,
                 [10] -> Third Bus Type,
                 [11] -> First Bus Visit Status,
                 [12] -> Second Bus Visit Status,
                 [13] -> Third Bus Visit Status,
                 [14] -> Estimated Duration for all 3 buses,
                 [15] -> Estimated Duration for 1st Visit Buses,
                 [16] -> Estimated Duration for 2nd Visit Buses,
                 [17] -> Boolean State to state whether all buses are on 1st Visit only,
                 [18] -> Origin Bus Stop,
                 [19] -> Destination Bus Stop,
                 [20] -> First Bus Timing Accuracy
                 [21] -> Second Bus Timing Accuracy
                 [22] -> Third Bus Timing Accuracy
                 [!] -> Note: For 14 to 17, bool state is to be used to determine on which type of duration(s) to be shown.
        """

        dt = datetime.datetime.now(datetime.timezone.utc)
        bus_list = []
        bus_stop_list = []

        dict_data = self._get("bus_arrival", BusStopCode=bus_stop_code)

        # Sort Numbers in Ascending Order
        for bus_svc in dict_data["Services"]:
            bus_list.append(bus_svc["ServiceNo"])

        bus_list = self.sort_bus_svc_list(bus_list)

        if return_svc_list:
            return bus_list

        if fallback_header and debug:
            print(
                f"=======================================================================================\n"
                f"Bus Stop No: {bus_stop_code} Services\n"
                f"======================================================================================="
            )

        # for bus_svc in dict_data["Services"]:
        for bus_ref in bus_list:
            # Should there be an explicit to see list of bus stop numbers
            # i.e. 3 to be seen from 3, 34, ...
            if svc_filter and str(bus_ref) not in {str(s).strip() for s in svc_filter}:
                continue

            search_svc = False

            for svc in dict_data["Services"]:
                if svc["ServiceNo"] == str(bus_ref):
                    search_svc = True
                    bus_svc = svc
                    break

            if not search_svc:
                continue

            # Move empty slots to the end so a missing 1st/2nd bus is filled by the next one
            # (whole entries move, so Load/Type/Visit/Monitored/Origin/Destination stay together)
            slots = [bus_svc["NextBus"], bus_svc["NextBus2"], bus_svc["NextBus3"]]
            filled = [b for b in slots if b.get("EstimatedArrival")]
            blank = {key: ("" if key != "Monitored" else 0) for key in slots[0]}
            bus_svc["NextBus"], bus_svc["NextBus2"], bus_svc["NextBus3"] = (filled + [dict(blank) for _ in range(3)])[:3]

            # Handle 1st, 2nd & 3rd Bus
            next_bus, nb_time, duration = self._parse_eta(bus_svc["NextBus"], dt)
            next_bus2, nb_time2, duration2 = self._parse_eta(bus_svc["NextBus2"], dt)
            next_bus3, nb_time3, duration3 = self._parse_eta(bus_svc["NextBus3"], dt)

            # Estimation of Durations
            if (bus_svc['NextBus']['VisitNumber'] == "1" or bus_svc['NextBus']['VisitNumber'] == "") and \
                    (bus_svc['NextBus2']['VisitNumber'] == "1" or bus_svc['NextBus2']['VisitNumber'] == "") and \
                    (bus_svc['NextBus3']['VisitNumber'] == "1" or bus_svc['NextBus3']['VisitNumber'] == ""):
                one_visit = True
                est_dur = self.calculate_est_duration([duration, duration2, duration3])
                est_dur_1 = 0
                est_dur_2 = 0
            else:
                one_visit = False
                visit_1 = []
                visit_2 = []

                for i in range(1, 4):
                    if i == 1:
                        key_ref = 'NextBus'
                        dur = duration
                    else:
                        key_ref = f'NextBus{i}'

                        if i == 2:
                            dur = duration2
                        else:
                            dur = duration3

                    if bus_svc[key_ref]['VisitNumber'] == "1":
                        visit_1.append(dur)
                    else:
                        visit_2.append(dur)

                if len(visit_1) < 3:
                    for i in range(3 - len(visit_1)):
                        visit_1.append(0)

                if len(visit_2) < 3:
                    for i in range(3 - len(visit_2)):
                        visit_2.append(0)

                est_dur = 0
                est_dur_1 = self.calculate_est_duration([visit_1[0], visit_1[1], visit_1[2]])
                est_dur_2 = self.calculate_est_duration([visit_2[0], visit_2[1], visit_2[2]])

            if debug:
                print(
                    f"Service [{bus_svc['ServiceNo']}] | {bus_svc['Operator']}\n"
                    f"=======================================================================================\n"
                    f"1. {next_bus} @ {nb_time[0]}:{nb_time[1]}:{nb_time[2]} ({bus_svc['NextBus']['EstimatedArrival']})"
                    f" | {self.interpret_seating(bus_svc['NextBus']['Load'])} | {self.interpret_type(bus_svc['NextBus']['Type'])}"
                    f" | Visit: {bus_svc['NextBus']['VisitNumber']} | Accurate: {bool(bus_svc['NextBus']['Monitored'])}\n"
                    f"2. {next_bus2} @ {nb_time2[0]}:{nb_time2[1]}:{nb_time2[2]} "
                    f"({bus_svc['NextBus2']['EstimatedArrival']}) | {self.interpret_seating(bus_svc['NextBus2']['Load'])} | "
                    f"{self.interpret_type(bus_svc['NextBus2']['Type'])}"
                    f" | Visit: {bus_svc['NextBus2']['VisitNumber']} | Accurate: {bool(bus_svc['NextBus2']['Monitored'])}\n"
                    f"3. {next_bus3} @ {nb_time3[0]}:{nb_time3[1]}:{nb_time3[2]} "
                    f"({bus_svc['NextBus3']['EstimatedArrival']}) | {self.interpret_seating(bus_svc['NextBus3']['Load'])} | "
                    f"{self.interpret_type(bus_svc['NextBus3']['Type'])}"
                    f" | Visit: {bus_svc['NextBus3']['VisitNumber']} | Accurate: {bool(bus_svc['NextBus3']['Monitored'])}\n"
                )

                print(
                    f"Estimated Duration: {est_dur} mins" if one_visit is True else
                    f"Estimated Duration (Visit 1): {est_dur_1} mins\nEstimated Duration (Visit 2): {est_dur_2} mins"
                )

                print(
                    f"======================================================================================="
                )

            # Append Compiled Data
            bus_stop_list.append(
                (
                    bus_svc['ServiceNo'],  # [0]
                    bus_svc['Operator'],  # [1]
                    f"{next_bus} @ {nb_time[0]}:{nb_time[1]}:{nb_time[2]}" if no_exact_time is False  # [2]
                    else f"{next_bus}",  # [2]
                    f"{next_bus2} @ {nb_time2[0]}:{nb_time2[1]}:{nb_time2[2]}" if no_exact_time is False  # [3]
                    else f"{next_bus2}",  # [3]
                    f"{next_bus3} @ {nb_time3[0]}:{nb_time3[1]}:{nb_time3[2]}" if no_exact_time is False  # [4]
                    else f"{next_bus3}",  # [4]
                    self.interpret_seating(bus_svc['NextBus']['Load'], use_emojis, short_forms),  # [5]
                    self.interpret_seating(bus_svc['NextBus2']['Load'], use_emojis, short_forms),  # [6]
                    self.interpret_seating(bus_svc['NextBus3']['Load'], use_emojis, short_forms),  # [7]
                    self.interpret_type(bus_svc['NextBus']['Type'], short_forms),  # [8]
                    self.interpret_type(bus_svc['NextBus2']['Type'], short_forms),  # [9]
                    self.interpret_type(bus_svc['NextBus3']['Type'], short_forms),  # [10]
                    bus_svc['NextBus']['VisitNumber'] if bus_svc['NextBus']['VisitNumber'] != "" else "X",  # [11]
                    bus_svc['NextBus2']['VisitNumber'] if bus_svc['NextBus2']['VisitNumber'] != "" else "X",  # [12]
                    bus_svc['NextBus3']['VisitNumber'] if bus_svc['NextBus3']['VisitNumber'] != "" else "X",  # [13]
                    est_dur,  # [14]
                    est_dur_1,  # [15]
                    est_dur_2,  # [16]
                    one_visit,  # [17]
                    bus_svc['NextBus']['OriginCode'],  # [18]
                    bus_svc['NextBus']['DestinationCode'],  # [19]
                    bool(bus_svc['NextBus']['Monitored']),  # [20]
                    bool(bus_svc['NextBus2']['Monitored']),  # [21]
                    bool(bus_svc['NextBus3']['Monitored'])  # [22]
                )
            )

        return bus_stop_list

    # Bus Stop Info Functions
    def request_bus_stop_name(self, bus_stop_code: int | str):
        """
        Gets and returns the Bus Stop Information of the Bus Stop.

        This method makes use of the data limit to cycle and check through if the codes matches.
        :param bus_stop_code: 5-digit Bus Stop Code
        :return: Tuple containing:
                 [0] -> Description,
                 [1] -> Road Name,
                 [2] -> Acquisition Success (for use in fallback)
        """
        hit = self.return_bus_stop_name_json(str(bus_stop_code))
        return (*hit, True) if hit else (None, None, False)

    def store_bus_stop_data(self):
        self.bus_stop_data.update_json({"value": self._get_all("bus_stops")})
        self.bus_stop_data.update_json_file()
        self.bus_stop_data.formulate_json()
        return None

    def return_bus_stop_name_json(self, bus_stop_code: str):
        for data in self.bus_stop_data.return_specific_json("value"):
            if data["BusStopCode"] == bus_stop_code:
                return (
                    data["Description"],
                    data["RoadName"]
                )

        return None

    def _stop_name(self, bus_stop_code: str):
        hit = self.return_bus_stop_name_json(bus_stop_code)
        return hit[0] if hit else bus_stop_code

    def request_bus_stop_code_from_name(self, stop_name: str, road_name: str = "", return_first_val: bool = False):
        matched_values = []

        for data in self.bus_stop_data.return_specific_json("value"):
            # print(f"{data["Description"].lower()} | {stop_name.lower()} ||| {data["RoadName"].lower()} | {road_name}")
            if data["Description"].lower() == stop_name.lower() and road_name == "":
                if return_first_val:
                    return data["BusStopCode"]
                else:
                    matched_values.append([data["BusStopCode"], data["Description"], data["RoadName"]])

            if data["Description"].lower() == stop_name.lower() and data["RoadName"].lower() == road_name.lower():
                if return_first_val:
                    return data["BusStopCode"]
                else:
                    matched_values.append([data["BusStopCode"], data["Description"], data["RoadName"]])

        if len(matched_values) > 0:
            return matched_values

        return "00000"

    def get_nearby_bus_stops(self, lon: float, lat: float):
        nearby_stops = []
        sorted_nearby_stops = []
        disp_sorter = []

        lon_m = lon * LON_LAT_CONV
        lat_m = lat * LON_LAT_CONV

        for data in self.bus_stop_data.return_specific_json("value"):
            bus_lon_m = data["Longitude"] * LON_LAT_CONV
            bus_lat_m = data["Latitude"] * LON_LAT_CONV

            diff_lon = max(lon_m, bus_lon_m) - min(lon_m, bus_lon_m)
            diff_lat = max(lat_m, bus_lat_m) - min(lat_m, bus_lat_m)

            disp = sqrt(diff_lon * diff_lon + diff_lat * diff_lat)

            if disp <= 500:
                nearby_stops.append(
                    (
                        data["BusStopCode"],
                        data["RoadName"],
                        data["Description"],
                        round(disp)
                    )
                )
                disp_sorter.append(
                    (
                        disp,
                        len(nearby_stops) - 1
                    )
                )

        disp_sorter = sorted(disp_sorter)

        for (disp, i) in disp_sorter:
            sorted_nearby_stops.append(nearby_stops[i])

            if len(sorted_nearby_stops) == 15:
                break

        return sorted_nearby_stops

    # Bus Service Functions
    def store_bus_svc_data(self):
        self.bus_svc_data.update_json({"value": self._get_all("bus_services")})
        self.bus_svc_data.update_json_file()
        self.bus_svc_data.formulate_json()
        return None

    def return_bus_svc_json(self, svc: str, direction: int):
        for data in self.bus_svc_data.return_specific_json("value"):
            is_loop = False
            if data["ServiceNo"] == svc and data["Direction"] == direction:

                if data["Direction"] == 1 and data["LoopDesc"] != "":
                    is_loop = True

                if data["ServiceNo"] in DBL_LOOP_DATA:
                    data["LoopDesc"] = DBL_LOOP_DATA[data["ServiceNo"]]

                return (
                    data["ServiceNo"],
                    data["Operator"],
                    data["Direction"],
                    data["Category"],
                    data["OriginCode"],
                    data["DestinationCode"],
                    data["LoopDesc"],
                    is_loop
                )

        return None

    def get_bus_svc_list(self):
        bus_svc_list = []
        for data in self.bus_svc_data.return_specific_json("value"):
            if data["ServiceNo"] not in bus_svc_list:
                bus_svc_list.append(data["ServiceNo"])

        return self.sort_bus_svc_list(bus_svc_list)

    @staticmethod
    def sort_bus_svc_list(svc_list: list):
        def key(s):
            pre, num, suf = re.match(r'^([A-Za-z]*)(\d*)(.*)$', s).groups()
            return (pre != '', pre, int(num) if num else 0, suf.lower())

        return sorted(set(svc_list), key=key)

    def get_bus_svc_directions(self, svc: str):
        bus_svc_list = []
        for data in self.bus_svc_data.return_specific_json("value"):
            # print(f"{data["ServiceNo"]} || {svc}")
            is_loop = False
            if data["ServiceNo"] == svc:

                if data["Direction"] == 1 and data["LoopDesc"] != "":
                    is_loop = True

                if data["ServiceNo"] in DBL_LOOP_DATA:
                    data["LoopDesc"] = DBL_LOOP_DATA[data["ServiceNo"]]

                bus_svc_list.append((
                    data["ServiceNo"],
                    data["Direction"],
                    data["Category"],
                    data["OriginCode"],
                    data["DestinationCode"],
                    data["LoopDesc"],
                    is_loop
                ))

                # print(f"LEN: {len(bus_svc_list)}")

                if is_loop or len(bus_svc_list) == 2:
                    # print(F"EXIT FUNC: \n {bus_svc_list}")
                    return bus_svc_list

        return bus_svc_list

    # Bus Route Functions
    def store_bus_route_data(self):
        """
        Rebuild the route cache as {ServiceNo: {Direction: {StopSequence: (BusStopCode, Distance)}}}.
        Built from scratch so withdrawn services do not linger.
        """
        routes = {}
        for data in self._get_all("bus_routes"):
            directions = routes.setdefault(data["ServiceNo"], {})
            stops = directions.setdefault(str(data["Direction"]), {})
            stops[str(data["StopSequence"])] = (data["BusStopCode"], data["Distance"])

        self.bus_route_data.update_json(routes)
        self.bus_route_data.update_json_file()
        self.bus_route_data.formulate_json()
        return None

    def get_bus_svc_route(self, svc: str, direction: str):
        return self.bus_route_data.return_specific_json(svc)[direction]

    def get_bus_svc_from_bus_stop_code(self, bus_stop_code: str):
        svc_list = []
        for svc, data in self.bus_route_data.return_json().items():
            # print(f"{svc} | {data}")
            for direction, dir_data in data.items():
                # print(f"{direction} | {dir_data}")
                for stop, stop_data in dir_data.items():
                # print(f"{stop} | {stop_data}")
                #     print(f"{bus_stop_code} | {svc} | {bus_stop_code in stop_data and svc not in svc_list}")
                #     print(f"Bus Stop Code in Stop Data & Service not in Service List: {bus_stop_code in stop_data} & {svc not in svc_list}")
                    if bus_stop_code in stop_data and svc not in svc_list:
                        svc_list.append(svc)
                        break

        return self.sort_bus_svc_list(svc_list)

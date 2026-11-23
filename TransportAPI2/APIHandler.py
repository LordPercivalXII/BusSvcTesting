from threading import Thread

from UtilLib.JSONHandler import JSONHandler

# Global variables
LON_LAT_CONV = 111139
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
        # Initialise JSON Handlers
        self.json_mem = JSONHandler("MemoryData") # User Memory Handler
        self.bus_stop_data = JSONHandler("BusStopData") # Bus Stop Data Handler
        self.bus_svc_data = JSONHandler("BusServiceData") # Bus Service Data Handler
        self.bus_route_data = JSONHandler("BusRouteData") # Bus Route Data Handler

    def _store_bus_stop_data(self):
        """
        Store bus stop data
        :return:
        """
        threads = []

        t1 = Thread(target=self.store_bus_stop_data, args=self.api_key)
        t2 = Thread(target=self.store_bus_svc_data, args=self.api_key)
        t3 = Thread(target=self.store_bus_route_data, args=self.api_key)

        threads.append(t1)
        threads.append(t2)
        threads.append(t3)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

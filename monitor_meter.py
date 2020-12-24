""" Web service that that reads a gas meter, and returns the the usage and rate
    Also has an option to take a picture

It returns the following as a json object:
        ccf:  100 cubic feet cumulative
        cfh:  cubic feet per hour
        kW: cfm converted to kilowatts
        kWh: cf converted to kilowatt hours (cumulative)
        cost_kW: kW adjusted so that it matches electric costs  (based on the constants above)
        cost_kWh: kWh adjusted so that it matches electric costs  (based on the constants above)
        cost_hr: The flow converted to currency based on the given thermCost
        cost: The total cost since the service was started
"""
import meter
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import time
import traceback
import sys
import cv2

clientMap = {}
startTime = time.time()

kwhCost = 0.1165
thermCost = 0.6698
thermCorrection = 1.073
thermsToKwh = 29.31
# Checked on 12/20/20
thermCost = 0.6698
kwhCost = 0.1165
cfh2kWh = 3.250
# how much cheaper it is to use gas for heat than electricity
# assume 90% efficiency
kwhCompare = thermsToKwh * kwhCost / thermCost * .9

class MeterServer(BaseHTTPRequestHandler):

    def _set_headers(self):
        if self.path.endswith("image") or self.path.endswith("find_circles"):
            self.send_header('Content-type', 'image/jpeg')
        elif self.path.endswith("ccf") or self.path.endswith("json"):
            self.send_header('Content-type', 'application/json')
        else:
            self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        global meter, clientMap, startTime
        self.send_response(200)
        if self.path.endswith("image"):
            image = meter.take_picture()
            ret, data = cv2.imencode('.jpg', image)
        elif self.path.endswith("ccf"):
            # Reads the actual dials to determine cumulative use.  The other method just returns usage
            # since the process was started
            image = meter.take_picture()
            value = {"ccf" : meter.read_ccf(image)}
            data = json.dumps(value).encode("utf8")
        elif self.path.endswith("json"):

            ip = self.client_address[0]
            val = clientMap.get(ip, (startTime, meter.starting))
            newTime = time.time()
            # Wait at least 55 seconds before returning new value.  Home assistant likes reading every 30 seconds,
            # but every minute results in smoother usage numbers
            if val[0] + 55 > newTime:
                cf = val[1]
            else:
                cf = meter.cf
                clientMap[ip] = (newTime, cf)
            cfh = (cf - val[1]) / (newTime - val[0]) * 60.0 * 60.0
            ccf = cf / 100.0
            kw = cfh * cfh2kWh
            kwh = ccf * thermCorrection * thermsToKwh
            val = {
                "ccf" : round(ccf, 3),
                "cfh" : round (cfh, 1),
                "kW" : round (kw, 1),
                "kWh" : round(kwh, 1),
                "cost_kW" : round(kw / kwhCompare, 1),
                "cost_kWh" : round(kwh / kwhCompare, 1),
                "cost_hr" : round(cfh * thermCorrection * thermCost / 100, 2),
                "cost" : round(ccf * thermCorrection * thermCost, 2)
            }
            data = json.dumps(val).encode("utf8")
        elif self.path.endswith("find_circles"):
            image = meter.take_picture()
            image = meter.find_circles(image)
            ret, data = cv2.imencode('.jpg', image)
        else:
            html = """
<html>
<body>
<head><title>Gas Meter</title></header>
<h1>Gas Meter</h1>
<iframe src="/ccf"></iframe>
<br>
<img src="/image" width="400">
<br>
<iframe src="/json">
</body> """
            data = html.encode("utf8")

        self.send_header('Content-length', str(len(data)))
        self._set_headers()
        self.wfile.write(data)

    def do_HEAD(self):
        self.send_response(200)
        self._set_headers()

httpd = HTTPServer(("", 8000), MeterServer)
meter.start()
if (meter.on_pi):
    print("Started meter reading")
else:
    print("Started emulated reading")
try:
    httpd.serve_forever()
except KeyboardInterrupt:
    pass
httpd.server_close()
print("Server stopped.")

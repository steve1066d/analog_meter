""" Web service that that reads a gas meter, and returns the the usage and rate
    Also has an option to return last image

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
import logging


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
    def _json(self):
        global meter
        cf = meter.cf
        cfh = meter.cfh
        ccf = cf / 100.0
        kw = cfh * cfh2kWh
        kwh = ccf * thermCorrection * thermsToKwh
        val = {
            "ccf": round(ccf, 3),
            "cfh": round(cfh, 1),
            "kW": round(kw, 1),
            "kWh": round(kwh, 1),
            "cost_kW": round(kw / kwhCompare, 1),
            "cost_kWh": round(kwh / kwhCompare, 1),
            "cost_hr": round(cfh * thermCorrection * thermCost / 100, 2),
            "cost": round(ccf * thermCorrection * thermCost, 2)
        }
        return val

    def mjpg(self):
        self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=--jpgboundary')
        self.end_headers()

        lastImg = None
        while True:
            img = meter.last_image
            if (id(lastImg) != id(img)):
                lastImg = img;
                ret, data = cv2.imencode('.jpg', img)

                self.wfile.write(bytes("--jpgboundary", "utf8"))
                self.send_header('Content-type', 'image/jpeg')
                self.send_header('Content-length', len(data))
                self.end_headers()
                self.wfile.write(data)
                self.send_response(200)
            time.sleep(.1)

    def html(self):
        global meter
        html = f"""
    <html>
    <body>
    <head><title>Gas Meter</title></header>
    <h1>Gas Meter</h1>
    <img src="/image.mjpg" width="400">
    <br>
    <h3>CCF dial read</h3>
    {meter.read_ccf()}
    <br>
    <h3>Current Values</h3>
    <br>
    {self._json()}
    </body> """
        return html.encode("utf8")

    def _set_headers(self):
        if self.path.endswith(".mjpg"):
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=--jpgboundary')
        elif self.path.endswith("image") or self.path.endswith("find_circles"):
            self.send_header('Content-type', 'image/jpeg')
        elif self.path.endswith("ccf") or self.path.endswith("json"):
            self.send_header('Content-type', 'application/json')
        else:
            self.send_header('Content-type', 'text/html')
        self.end_headers()

    def log_message(self, format, *args):
        return

    def do_GET(self):
        global meter
        self.send_response(200)
        try:
            if self.path.endswith('.mjpg'):
                self.mjpg()
            elif self.path.endswith("image"):
                ret, data = cv2.imencode('.jpg', meter.last_image)
            elif self.path.endswith("ccf"):
                # Reads the actual dials to determine cumulative use.  The other method just returns usage
                # since the process was started
                value = {"ccf" : meter.read_ccf()}
                data = json.dumps(value).encode("utf8")
            elif self.path.endswith("json"):
                val = self._json();
                data = json.dumps(val).encode("utf8")
            elif self.path.endswith("find_circles"):
                image = meter.find_circles(image)
                ret, data = cv2.imencode('.jpg', image)
            else:
                data = self.html()
            self.send_header('Content-length', str(len(data)))
            self._set_headers()
            self.wfile.write(data)
        except ConnectionAbortedError:
            return

    def do_HEAD(self):
        self.send_response(200)
        self._set_headers()

httpd = HTTPServer(("", 8000), MeterServer)
meter.start()
if (meter.on_pi):
    logging.info("Started meter reading")
else:
    logging.info("Started emulated reading")
try:
    httpd.serve_forever()
except KeyboardInterrupt:
    pass
httpd.server_close()
logging.info("Server stopped.")

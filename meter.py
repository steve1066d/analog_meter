""" Reads an AC-250 gas meter by monitoring the 2cfm dial
    Steve Devore steve1066d@yahoo.com

    I'm using a Raspberry PI, with the HQ camera (HQ because I needed a lens that could be monted close to the meter).
    It should work fine with the standard camera as well. The basic approach is to use opencv to find the correct dial,
    and save the dial positions. I got more consistent results only looking for the dials one time, as opencv doesn't
    exactly line up the circles between shots.

    It then reads the top ccf dials for the starting position. Next, it looks at the 2cf dial and keeps track of the
    position and revolutions to report the cumulative cubic feet used.

    The take_picture method should return a cropped grayscale photo of the meter display (see example photo)

    For debugging, if it is run on a system without the camera, it will instead use a series of photos instead
    The series can be created by enabling saveImages.

"""

import cv2
import numpy as np
import time
import sys
import pathlib
from os import path
import threading
import json
from datetime import datetime

debug = True
""" If this is true, it will display various images to show how it is working """

secondsBetweenPictures = 2
""" The time to wait between images """

saveImages = False
""" If images should be saved for debugging purposes """

cf = 0
""" The number of cubic feet on the meter """
starting = 0
""" The number of cubic feet that was on the meter when the app was first started """

_file_id = 1000
_camera_lock = threading.Lock()

try:
    from picamera.array import PiRGBArray
    from picamera import PiCamera

    on_pi = True

    # Configure the camera
    camera = PiCamera(resolution=(1280, 720), framerate=1)
    camera.iso = 400
    camera.shutter_speed = 200000
    time.sleep(.2)
    camera.exposure_mode = 'off'
    camera.zoom = (30000.0 / 65535, 6000.0 / 65535, 23000.0 / 65535, 23000.0 / 65535)
    camera.awb_mode = 'off'
    camera.awb_gains = (591.0 / 256, 639.0 / 256)
    rawCapture = PiRGBArray(camera)
except:
    on_pi = False


def four_point_transform(image, pts):
    """ This squares up the and crops the image """
    rect = np.array(pts, dtype="float32")
    (tl, tr, br, bl) = rect
    # compute the width of the new image, which will be the
    # maximum distance between bottom-right and bottom-left
    # x-coordinates or the top-right and top-left x-coordinates
    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))
    # compute the height of the new image, which will be the
    # maximum distance between the top-right and bottom-right
    # y-coordinates or the top-left and bottom-left y-coordinates
    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))
    # now that we have the dimensions of the new image, construct
    # the set of destination points to obtain a "birds eye view",
    # (i.e. top-down view) of the image, again specifying points
    # in the top-left, top-right, bottom-right, and bottom-left
    # order
    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    return warped

def findangle(img, slices=200, min = 0, max = 360):
    """ Find the needle angle by fitting a small pie slice to it"""
    radius = int(img.shape[0] / 2);
    axes = (radius, radius)
    arc = float((max - min)) / slices;
    half_arc = arc / 2
    match_count = img.shape[0] * img.shape[1]
    match_angle = None

    for i in range(0, slices):
        angle = (max - min) * float(i) / slices + min
        imgc = img.copy()
        # the arc might be better as half_arc, but at 200 slices, it might be too skinny.
        imgc = cv2.ellipse(imgc, axes, axes, angle, -arc, arc, 0, thickness=-1)
        histogram = cv2.calcHist([imgc], [0], None, [2], [0, 256])
        count = histogram[1][0]
        if count < match_count:
            match_count = count
            match_angle = angle
    if debug:
        imgc = cv2.ellipse(img, axes, axes, match_angle, -half_arc, half_arc, 255, thickness=-1)
        debug_image("findangle", imgc)
    return match_angle


def scale(img, image_scale):
    width = int(img.shape[1] * image_scale)
    height = int(img.shape[0] * image_scale)
    dim = (width, height)
    # resize image
    return cv2.resize(img, dim, interpolation=cv2.INTER_AREA)


def debug_image(name, img):
    if img.shape[1] < 200:
        img = scale(img, 200 / img.shape[1])
    cv2.imshow(name, img)


def find_circles(img):
    """ It turns out that the camera is more stable than the algorythm to find the dials.  So this is just
        used on demand to get the coordinates, and then its saved.
    """
    global _circles

    original = img
#
    # Might get better results with a blur before trying to find the shapes, but
    # it didn't help in my case
#    img = cv2.GaussianBlur( img, (7, 7), 2, 2 )

    # sizes are based on a 375 height image
    scale = img.shape[0] / 375.0
    circles = cv2.HoughCircles(img, cv2.HOUGH_GRADIENT, 1.5, int(scale * 100), minRadius=int(scale * 50),
                               maxRadius=int(scale * 70))
    # ensure at least some circles were found
    if circles is not None:
        # convert the (x, y) coordinates and radius of the circles to integers
        _circles = np.round(circles[0, :]).astype("int")
        for (x, y, r) in _circles:
            cv2.circle(original, (x, y), r, (0, 255, 0), 4)  # debug
            print("radius: %d adj: %d,  " % (r, r / scale))
        with open('settings.json', 'w') as outfile:
            json.dump(np.ndarray.tolist(_circles), outfile)
    return original

def get_circle(circles, pos, img):
    # gets the correct dial.  the top row are 0-3, bottom 4-5. (last can also use -1)
    circles = circles[np.argsort(circles[:, 1])]

    if pos > 3 or pos < 0:
        circles = circles[-2:]
    else:
        circles = circles[:4]
    circles = circles[np.argsort(circles[:, 0])]
    if pos > 3:
        pos -= 4
    x, y, r = circles[pos]
    if debug:
        cv2.circle(img, (x, y), r, 0, 4)  # debug
        debug_image("circles", img)
    # get the last dial on the bottom row
    img = img[y - r:y + r, x - r:x + r]
    return img

def read_dial(img):
    r = int(img.shape[0] / 2)
    output = np.zeros((r * 2, r * 2, 1), np.uint8)
    white = output.copy()
    white[:] = 255

    # draw a donut mask to look for the arrow only in the outer section of the dial
    cv2.circle(output, (r, r), int(round(.95 * r)), 255, -1)
    cv2.circle(output, (r, r), int(round(.69 * r)), 0, -1)

    # Mask out everything but the donut part of the image
    match = cv2.bitwise_and(output, img)
    # now change everything not in the donut to white
    output = cv2.bitwise_or(~output, match)

    ret, thresh = cv2.threshold(output, 135, 255, cv2.THRESH_BINARY_INV)
    # thresh = cv2.adaptiveThreshold(~output,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,11,2)
    position = findangle(thresh)
    # determine angle, between 0 and 10, with 0 at the top
    position = (position / 36 + 2.5) % 10
    if debug:
        img = output.copy()
        color = (0, 0, 255)
        cv2.putText(img, ("%.1f" % position), (int(r / 2), r), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2,
                    cv2.LINE_AA)
        debug_image("final", img)
    return position


def read2cf(img):
    """ Reads the 2 cf dial of a gas meter
    :param img:  image is roughly that of the cropped view of the meter panel
    :return:  position between 0 and < 10 going clockwise
    """
    return _read_meter(img, True)


def read_ccf(img):
    """ Reads the top ccf dials of the meter.
    """
    return _read_meter(img, False)


def _read_meter(img, rate):
    global _circles

    # find the dials
    position = -1
    if _circles is not None:
        if rate:
            img = get_circle(_circles, -1, img)
            position = read_dial(img)
        else:
            position = 0
            mult = 10
            for i in reversed(range(4)):
                img2 = get_circle(_circles, i, img)
                val = read_dial(img2)
                # every other dial goes ccw
                if i % 2 == 0:
                    val = 10 - val
                if i == 3:
                    position = round(val, 1)
                else:
                    # easy to eyeball, hard to code.. but I think this should
                    # work to read given that if its close to the 0, you need to look
                    # at the one to the right to figure out what position it should be
                    position = (np.floor(val - (last_position / 10.0 - .5)) % 10) * mult + position
                    mult *= 10
                last_position = val
    return position

def take_picture():
    global _camera_lock, last_file, _file_id
    _camera_lock.acquire()
    try:
        if on_pi:
            camera.capture(rawCapture, format="bgr")
            image = rawCapture.array
            rawCapture.truncate(0)
            if saveImages:
                cv2.imwrite("%d.jpg" % file_id, image)
        else:
            last_file = "c:/meter/images/%d.jpg" % _file_id
            image = cv2.imread(last_file)
            if image is None:
                exit(0)
        _file_id += 1
    finally:
        _camera_lock.release()
    points = np.array([(32, 74), (1132,45), (1165, 651), (49, 718)])
    image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    image = four_point_transform(image, points)
    return image;

def run():
    """ Periodically takes a picture and calculates the new cf value """
    last_time = 0
    last_meter_pos = 0
    current = 0
    cfm = 0
    global cf
    print("cf is: ",cf)
    while True:
        timer = time.time()
        image = take_picture()
        if on_pi:
            # grab an image from the camera
            new_time = time.time()
        else:
            path = pathlib.Path(last_file)
            new_time = path.stat().st_mtime
            if debug:
                print(last_file, datetime.fromtimestamp(new_time))

        position = read2cf(image)
        meter_pos = np.interp(position, [0, 10], [2, 0])
        new_pos = meter_pos
        if (new_pos + 1) <= last_meter_pos:
            new_pos += 2
        skip = False
        if last_time == 0:
            last_time = new_time
            last_meter_pos = new_pos
        # Only consider it a new value if it is at last .1 cf over previous value
        # (prevents a stationary dial from reading as having done almost a full revolution)
        if new_pos > last_meter_pos:
            if last_time != 0:
                current = (new_pos - last_meter_pos)
                cfm = current / (new_time - last_time) * 60
                # if we get over 10 cfm, it must be because there was a dial misread.. Ignore it and wait for
                # something better
                if cfm > 10:
                    skip = True
                    print("skipping... %.1f" % position)
            if not skip:
                print("pos: %.1f, elapsed: %.1f, cf: %.1f, cfm: %.1f" % (position, (new_time - last_time), cf, cfm))
                cf += current
                last_time = new_time
                last_meter_pos = meter_pos
        if debug:
            key = cv2.waitKey(int(secondsBetweenPictures * 1000))
            if key == 27:  # exit on esc
                exit(0)
        else:
            time.sleep(secondsBetweenPictures)
        sys.stdout.flush()

def initialize():
    global _circles, cf, starting
    image = take_picture()
    if path.isfile('settings.json'):
        with open('settings.json') as json_file:
            _circles = np.array(json.load(json_file))
    else:
        find_circles(image)
    cf = read_ccf(image) * 100
    starting = cf
    print("initialized: ", cf)

def start():
    """ Start processing in the background """
    global debug
    # never run in debug if it is run as a daemon process
    debug = False
    initialize()
    threading.Thread(target=run, args=(), daemon=True).start()


if __name__ == "__main__":
    initialize()
    run()
